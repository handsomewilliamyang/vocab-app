import pandas as pd
import streamlit as st
import json
import os
import time
import docx
import random
import requests
import re  # 新增：用來過濾維基詞典的 HTML 標籤
from gtts import gTTS
import io

import gspread
from google.oauth2.service_account import Credentials

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

st.set_page_config(
    page_title="我愛背單字 (雲端拼字測驗版)",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 注入自訂 CSS
st.markdown("""
    <style>
    .stDataFrame [data-testid="stTable"] td, .stDataFrame div[data-baseweb="table"] td, div[data-testid="stDataFrame"] div.dvn-scroller td {
        white-space: normal !important;
        word-wrap: break-word !important;
        height: auto !important;
        padding-top: 10px !important;
        padding-bottom: 10px !important;
    }
    </style>
""", unsafe_allow_html=True)

@st.cache_resource
def init_gsheets_client():
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scopes
    )
    return gspread.authorize(creds)

try:
    gs_client = init_gsheets_client()
    SHEET_URL = st.secrets["sheet_url"]
except Exception as e:
    st.error(f"⚠️ Google Sheets 連線設定錯誤：{e}")
    st.stop()

st.sidebar.markdown("<h2>⚙️ 系統導覽與設定</h2>", unsafe_allow_html=True)
st.sidebar.markdown("---")
main_menu = st.sidebar.radio(
    "選擇主要功能：",
    ["✨ 智慧單字新增", "📖 字庫管理與搜尋", "🎯 沉浸式閃卡複習", "🎮 拼字王挑戰遊戲"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")
user_api_key = st.sidebar.text_input("輸入 Gemini API Key (選填)", type="password", value=st.secrets.get("gemini_api_key", ""))
if user_api_key:
    st.session_state.gemini_api_key = user_api_key
    if HAS_GEMINI:
        genai.configure(api_key=user_api_key)
    st.sidebar.success("✅ AI 字典引擎已啟用")
else:
    st.session_state.gemini_api_key = ""
    st.sidebar.info("💡 未填寫 API Key 時將啟用「多重免費字典串聯」引擎")

st.sidebar.markdown("---")
selected_level = st.sidebar.radio(
    "選擇目前目標級別：",
    ["國中部", "高中部", "多益 (TOEIC)"],
    label_visibility="collapsed"
)

level_sheet_mapping = {
    "國中部": "國中部",
    "高中部": "高中部",
    "多益 (TOEIC)": "多益"
}
current_sheet_name = level_sheet_mapping.get(selected_level, "國中部")

try:
    spreadsheet = gs_client.open_by_url(SHEET_URL)
    try:
        active_worksheet = spreadsheet.worksheet(current_sheet_name)
    except Exception:
        active_worksheet = spreadsheet.get_worksheet(0)
except Exception as e:
    st.error(f"⚠️ Google Sheets 連線失敗：{e}")
    st.stop()

def load_vocab_dataframe(_worksheet, force_reload=False):
    cache_key = f"vocab_df_{_worksheet.title}"
    if force_reload or cache_key not in st.session_state:
        try:
            all_values = _worksheet.get_all_values()
        except Exception:
            all_values = []
            
        if len(all_values) > 1:
            headers = [str(h).strip().lower() for h in all_values[0]]
            data_rows = all_values[1:]
            df_temp = pd.DataFrame(data_rows, columns=headers[:len(all_values[0])])
        else:
            df_temp = pd.DataFrame(columns=['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'advanced_sentence', 'basic_sentence', 'collocations', 'unit_tag', 'srs_stage'])
            
        required_cols = ['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'advanced_sentence', 'basic_sentence', 'collocations', 'unit_tag', 'srs_stage']
        for col in required_cols:
            if col not in df_temp.columns:
                df_temp[col] = ""
                
        df_temp = df_temp[df_temp['word'].astype(str).str.strip() != '']
        df_temp = df_temp[df_temp['word'].notna()]
        
        for idx in df_temp.index:
            for col in df_temp.columns:
                val = str(df_temp.at[idx, col])
                if val == "nan" or val.lower() == "none" or val.strip() == "":
                    df_temp.at[idx, col] = ""
                    
        st.session_state[cache_key] = df_temp
    
    return st.session_state[cache_key]

S2T_DICT = {
    "餐厅": "餐廳", "饭厅": "餐廳", "计算机": "電腦", "网络": "網路", 
    "软件": "軟體", "硬件": "硬體", "信息": "資訊", "视频": "影片", 
    "音频": "音訊", "文件": "檔案", "打印": "列印", "鼠标": "滑鼠", 
    "键盘": "鍵盤", "屏幕": "螢幕", "项目": "專案", "组": "組", 
    "默认": "預設", "句": "句", "词": "詞", "语法": "語法"
}

def simple_s2t_convert(text):
    if not text: return text
    for s, t in S2T_DICT.items():
        text = text.replace(s, t)
    return text

def fetch_real_english_definition(word):
    """三大免費開源字典 API 串聯 (Datamuse -> Free Dictionary -> Wiktionary)"""
    w_clean = word.strip().lower()
    
    # 引擎 1：Datamuse API (字庫極大，穩定)
    try:
        url_dm = f"https://api.datamuse.com/words?sp={w_clean}&md=d&max=1"
        res_dm = requests.get(url_dm, timeout=3)
        if res_dm.status_code == 200:
            data = res_dm.json()
            if data and 'defs' in data[0]:
                raw_def = data[0]['defs'][0]
                clean_def = raw_def.split('\t', 1)[-1] if '\t' in raw_def else raw_def
                if clean_def:
                    return clean_def.capitalize()
    except Exception:
        pass

    # 引擎 2：Free Dictionary API
    try:
        url_fd = f"https://api.dictionaryapi.dev/api/v2/entries/en/{w_clean}"
        res_fd = requests.get(url_fd, timeout=3)
        if res_fd.status_code == 200:
            data = res_fd.json()
            real_def = data[0]['meanings'][0]['definitions'][0]['definition']
            if real_def:
                return real_def
    except Exception:
        pass
        
    # 引擎 3：Wiktionary API (維基詞典，涵蓋片語與偏門字)
    try:
        url_wk = f"https://en.wiktionary.org/api/rest_v1/page/definition/{w_clean.replace(' ', '_')}"
        res_wk = requests.get(url_wk, timeout=3)
        if res_wk.status_code == 200:
            data = res_wk.json()
            for lang in data.values():
                for item in lang:
                    if 'definitions' in item and len(item['definitions']) > 0:
                        raw_html = item['definitions'][0]['definition']
                        clean_text = re.sub(r'<[^>]+>', '', raw_html).strip() # 去除 HTML 標籤
                        if clean_text:
                            return clean_text
    except Exception:
        pass

    # 若三大引擎全數失敗的極致保底
    return f"A common term referring to {word}."

def generate_dynamic_single_sentence(word, definition):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    d_clean = definition.strip()
    
    random.seed(w_lower)
    is_plural = w_clean.lower().endswith("es") or (w_clean.lower().endswith("s") and w_clean.lower() not in ["bus", "class", "address", "always", "sometimes"]) or "複數" in d_clean
    
    if w_lower in ["above", "below", "behind", "under", "between", "beside", "near", "inside", "outside", "across", "along", "through", "with", "without", "about", "from", "into", "onto"]:
        templates = [
            f"The adventurous travelers hiked {w_lower} the dense forest to reach the peak.",
            f"We managed to set up our camp safely right {w_lower} the massive cliff.",
            f"The secret passage is hidden securely {w_lower} the old stone wall."
        ]
        return random.choice(templates)
        
    elif w_lower in ["maybe", "perhaps", "actually", "probably", "certainly", "definitely"]:
        templates = [
            f"To be honest, I {w_lower} think we should reconsider our original plan.",
            f"She {w_lower} surprised everyone by finishing the difficult project ahead of schedule."
        ]
        return random.choice(templates)
        
    elif w_lower in ["usually", "always", "often", "sometimes", "never", "seldom", "rarely"]:
        return f"Despite her busy schedule, she {w_lower} finds time to read inspirational books."
        
    elif w_lower in ["but", "yet", "and", "or", "so"]:
        return f"The experiment faced several unexpected setbacks, {w_lower} the researchers refused to give up."

    elif any(k in d_clean for k in ["吃", "喝", "做", "跑", "走", "看", "聽", "寫", "買", "賣", "說", "想", "玩", "學", "教"]):
        return f"It is essential to learn how to {w_clean} effectively in real-world situations."

    elif any(k in d_clean for k in ["顏色", "紅", "藍", "綠", "黃", "黑", "白"]):
        return f"The interior designer chose a striking {w_clean} hue to brighten up the living room."

    elif any(k in d_clean for k in ["人", "員", "父母", "父親", "母親", "朋友", "學生", "老師"]):
        return f"The dedicated {w_clean} worked tirelessly to ensure the project succeeded."
        
    elif any(k in d_clean for k in ["地方", "室", "房", "家", "廚房", "客廳", "學校", "銀行", "店"]):
        return f"Locals often gather at this popular {w_clean} to socialize on weekends."
        
    elif any(k in d_clean for k in ["筆記本", "書", "紙", "筆"]):
        return f"She opened her brand new {w_clean} and began jotting down important ideas."

    elif any(k in d_clean for k in ["餅乾", "食物", "水", "蘋果", "麵包", "茶", "咖啡", "肉", "果"]):
        return f"Having some fresh {w_clean} is a great way to start your energetic morning."
        
    elif any(k in d_clean for k in ["鼠", "動物", "貓", "狗", "鳥", "魚", "兔"]):
        return f"Researchers observed how the rare {w_clean} adapts to seasonal environmental shifts."
        
    elif any(k in d_clean for k in ["特別", "重要", "好", "壞", "大", "小", "高", "低", "長", "短", "新", "舊"]):
        return f"She approached the challenge with a remarkably {w_clean} perspective."
        
    else:
        templates = [
            f"Experts have emphasized the growing significance of {w_clean} in modern studies.",
            f"We discussed various practical applications of {w_clean} during the workshop."
        ]
        return random.choice(templates)

def get_word_record_data_via_ai(word, raw_def="", level="國中部"):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    cleaned_def = simple_s2t_convert(raw_def) if raw_def else f"{w_clean} 的中文釋義"

    # 呼叫三大免費字典引擎串聯機制
    real_eng_def = fetch_real_english_definition(w_clean)

    if HAS_GEMINI and st.session_state.get("gemini_api_key"):
        for attempt in range(2):
            try:
                genai.configure(api_key=st.session_state["gemini_api_key"])
                model = genai.GenerativeModel("gemini-1.5-flash")
                prompt = (
                    f"你是一個專業的英語字典。請針對單字「{w_clean}」（中文解釋：{cleaned_def}），"
                    "嚴格回傳純 JSON 格式，不含其他文字：\n"
                    "{\n"
                    '    "phonetic": "/音標/",\n'
                    '    "part_of_speech": "詞性",\n'
                    '    "english_definition": "簡明的英文釋義",\n'
                    '    "sentence": "一句道地的英文例句"\n'
                    "}"
                )
                response = model.generate_content(prompt)
                raw_text = response.text.strip()
                
                if "{" in raw_text and "}" in raw_text:
                    raw_text = raw_text[raw_text.find("{"):raw_text.rfind("}") + 1]
                    
                data = json.loads(raw_text)
                
                # 如果 AI 解釋為空或是無意義保底，就強制用串聯字典的結果取代
                final_eng_def = data.get("english_definition", "")
                if not final_eng_def or "A term or concept referring to" in final_eng_def:
                    final_eng_def = real_eng_def

                return {
                    "word": w_clean,
                    "phonetic": data.get("phonetic", f"/{w_lower.replace(' ', '')}/"),
                    "part_of_speech": simple_s2t_convert(data.get("part_of_speech", "n.")),
                    "definition": cleaned_def,
                    "advanced_sentence": final_eng_def,
                    "basic_sentence": data.get("sentence", generate_dynamic_single_sentence(w_clean, cleaned_def))
                }
            except Exception:
                time.sleep(1)
            
    # 如果沒有 Gemini 或失敗，直接使用多重字典與動態例句組合
    return {
        "word": w_clean,
        "phonetic": f"/{w_lower.replace(' ', '')}/",
        "part_of_speech": "n.",
        "definition": cleaned_def,
        "advanced_sentence": real_eng_def,
        "basic_sentence": generate_dynamic_single_sentence(w_clean, cleaned_def)
    }

def save_all_vocab_to_sheet(_worksheet, df):
    try:
        _worksheet.clear()
        headers = ['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'advanced_sentence', 'basic_sentence', 'collocations', 'unit_tag', 'srs_stage']
        rows = [headers]
        for _, row in df.iterrows():
            rows.append([
                str(row.get('id', '')),
                str(row.get('word', '')),
                str(row.get('phonetic', '')),
                str(row.get('part_of_speech', '')),
                str(row.get('definition', '')),
                str(row.get('advanced_sentence', '')),
                str(row.get('basic_sentence', '')),
                str(row.get('collocations', '')),
                str(row.get('unit_tag', '') if pd.notna(row.get('unit_tag')) else ''),
                str(row.get('srs_stage', 0))
            ])
        _worksheet.update(rows)
        load_vocab_dataframe(_worksheet, force_reload=True)
        return True, "成功"
    except Exception as e:
        return False, str(e)

@st.cache_data(show_spinner=False)
def generate_audio_bytes(text, tld='com'):
    tts = gTTS(text=text, lang='en', tld=tld)
    fp = io.BytesIO()
    tts.write_to_fp(fp)
    return fp.getvalue()

st.title("📚 我愛背單字 (雲端拼字測驗版)")

try:
    df_vocab = load_vocab_dataframe(active_worksheet)
except Exception:
    time.sleep(2)
    df_vocab = load_vocab_dataframe(active_worksheet, force_reload=True)

total_words = len(df_vocab)
col_m1, col_m2 = st.columns(2)
col_m1.metric(label="雲端總單字數", value=f"{total_words} 個")
col_m2.metric(label="目前模式", value=f"{main_menu} ({selected_level})")

st.markdown("<br>", unsafe_allow_html=True)

if main_menu == "✨ 智慧單字新增":
    if selected_level == "國中部":
        semester = st.selectbox("選擇年級學期：", ["國一上", "國一下", "國二上", "國二下", "國三上", "國三下"])
    elif selected_level == "高中部":
        semester = st.selectbox("選擇年級學期：", ["高一上", "高一下", "高二上", "高二下", "高三上", "高三下"])
    else:
        semester = st.selectbox("選擇階段：", ["多益核心", "多益進階", "商用英文"])
    unit = st.selectbox("選擇課次單元：", ["第一課", "第二課", "第三課", "第四課", "第五課", "第六課"])
    current_unit_tag = f"{semester} > {unit}"
    
    st.info(f"📌 即時同步至 Google Sheets 【{active_worksheet.title}】分頁：**{current_unit_tag}**")
    st.markdown("---")

    col_input1, col_input2 = st.columns(2, gap="large")
    with col_input1:
        st.subheader("📝 單筆快速建檔")
        single_word = st.text_input("輸入想要學習的英文單字：", placeholder="例如：resilient")
        if st.button("🚀 查字典並寫入雲端", type="primary", use_container_width=True):
            if single_word:
                with st.spinner("🤖 正在調用三大免費字典庫聯網生成中..."):
                    data = get_word_record_data_via_ai(single_word, level=selected_level)
                    word = data.get('word')
                    
                    df_current = load_vocab_dataframe(active_worksheet)
                    if not df_current.empty and word.lower() in df_current['word'].str.lower().values:
                        idx = df_current.index[df_current['word'].str.lower() == word.lower()].tolist()[0]
                        df_current.at[idx, 'phonetic'] = data.get('phonetic', '')
                        df_current.at[idx, 'part_of_speech'] = data.get('part_of_speech', '')
                        df_current.at[idx, 'definition'] = simple_s2t_convert(data.get('definition', ''))
                        df_current.at[idx, 'advanced_sentence'] = data.get('advanced_sentence', '')
                        df_current.at[idx, 'basic_sentence'] = data.get('basic_sentence', '')
                        df_current.at[idx, 'unit_tag'] = current_unit_tag
                    else:
                        next_id = len(df_current) + 1
                        new_row = pd.DataFrame([{
                            'id': next_id,
                            'word': word,
                            'phonetic': data.get('phonetic', ''),
                            'part_of_speech': data.get('part_of_speech', ''),
                            'definition': simple_s2t_convert(data.get('definition', '')),
                            'advanced_sentence': data.get('advanced_sentence', ''),
                            'basic_sentence': data.get('basic_sentence', ''),
                            'collocations': '',
                            'unit_tag': current_unit_tag,
                            'srs_stage': 0
                        }])
                        df_current = pd.concat([df_current, new_row], ignore_index=True)
                        
                    save_all_vocab_to_sheet(active_worksheet, df_current)
                    st.success(f"🎉 成功新增單字：{word} | 中文：{data.get('definition')}")
                    time.sleep(0.5)
                    st.rerun()

    with col_input2:
        st.subheader("📂 Word 檔案智慧匯入 (表格結構化解析)")
        uploaded_docxs = st.file_uploader("上傳 Word 講義檔案", type=["docx"], accept_multiple_files=True)
        if uploaded_docxs:
            if st.button("📖 批次解析 Word 並匯入", use_container_width=True):
                extracted_data_list = []
                
                with st.spinner("🔍 正在結構化解析 Word 表格欄位..."):
                    for uploaded_docx in uploaded_docxs:
                        temp_path = f"temp_{uploaded_docx.name}"
                        try:
                            with open(temp_path, "wb") as f:
                                f.write(uploaded_docx.getbuffer())
                            doc = docx.Document(temp_path)
                            
                            for table in doc.tables:
                                for row in table.rows:
                                    cells = row.cells
                                    if len(cells) >= 3:
                                        raw_word = cells[1].text.strip()
                                        raw_def = cells[2].text.strip()
                                    elif len(cells) == 2:
                                        raw_word = cells[0].text.strip()
                                        raw_def = cells[1].text.strip()
                                    else:
                                        continue
                                        
                                    w_cleaned = raw_word.split('\n')[0].strip()
                                    d_cleaned = raw_def.split('\n')[0].strip()
                                    
                                    if (w_cleaned and 
                                        len(w_cleaned) < 35 and 
                                        not any(('\u4e00' <= c <= '\u9fff') for c in w_cleaned) and 
                                        not any(char in w_cleaned for char in ['/', '[', ']', '(', ')', '=', '：', ':', '□'])):
                                        
                                        if not any(item['word'].lower() == w_cleaned.lower() for item in extracted_data_list):
                                            extracted_data_list.append({
                                                "word": w_cleaned,
                                                "definition": d_cleaned
                                            })
                                            
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                        except Exception:
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                
                total_words_to_process = len(extracted_data_list)
                
                if total_words_to_process > 0:
                    st.info(f"📑 結構化解析完畢！共鎖定表格找到 **{total_words_to_process}** 個有效單字。")
                    
                    progress_bar = st.progress(0)
                    status_ui = st.empty()
                    
                    df_current = load_vocab_dataframe(active_worksheet)
                    total_success_count = 0
                    
                    for i, item in enumerate(extracted_data_list):
                        word = item["word"]
                        raw_def = item["definition"]
                        
                        status_ui.markdown(
                            f"**⏳ 匯入進度：** `{(i+1)} / {total_words_to_process}`\n\n"
                            f"👉 目前正在串接多重字典處理： **{word}**\n\n"
                        )
                        
                        w_data = get_word_record_data_via_ai(word, raw_def=raw_def, level=selected_level)
                        
                        if not df_current.empty and word.lower() in df_current['word'].str.lower().values:
                            idx = df_current.index[df_current['word'].str.lower() == word.lower()].tolist()[0]
                            df_current.at[idx, 'phonetic'] = w_data.get('phonetic', '')
                            df_current.at[idx, 'part_of_speech'] = w_data.get('part_of_speech', '')
                            df_current.at[idx, 'definition'] = simple_s2t_convert(w_data.get('definition', ''))
                            df_current.at[idx, 'advanced_sentence'] = w_data.get('advanced_sentence', '')
                            df_current.at[idx, 'basic_sentence'] = w_data.get('basic_sentence', '')
                            df_current.at[idx, 'unit_tag'] = current_unit_tag
                        else:
                            next_id = len(df_current) + 1
                            new_row = pd.DataFrame([{
                                'id': next_id,
                                'word': word,
                                'phonetic': w_data.get('phonetic', ''),
                                'part_of_speech': w_data.get('part_of_speech', ''),
                                'definition': simple_s2t_convert(w_data.get('definition', '')),
                                'advanced_sentence': w_data.get('advanced_sentence', ''),
                                'basic_sentence': w_data.get('basic_sentence', ''),
                                'collocations': '',
                                'unit_tag': current_unit_tag,
                                'srs_stage': 0
                            }])
                            df_current = pd.concat([df_current, new_row], ignore_index=True)
                            
                        total_success_count += 1
                        progress_bar.progress((i + 1) / total_words_to_process)
                        time.sleep(0.5) 
                        
                    status_ui.markdown("🔄 **正在將所有資料同步至 Google Sheets，請稍候...**")
                    save_all_vocab_to_sheet(active_worksheet, df_current)
                    
                    status_ui.success(f"🎊 批次匯入完成！成功結構化解析並匯入 {total_success_count} 個單字。")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.warning("⚠️ 在上傳的 Word 表格中找不到符合的結構化單字。")

elif main_menu == "📖 字庫管理與搜尋":
    if df_vocab.empty:
        st.info("📭 目前雲端尚無單字，請至側邊欄新增！")
    else:
        unit_list = sorted(df_vocab['unit_tag'].dropna().unique().tolist()) if 'unit_tag' in df_vocab.columns else []
        unit_list = ["全部單字"] + [u for u in unit_list if u.strip() != ""]
        
        col_f1, col_f2 = st.columns([1.5, 1])
        with col_f1:
            selected_unit_filter = st.selectbox("依學習單元篩選顯示：", unit_list)
        with col_f2:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            if st.button("🔄 重新整理畫面快取", type="primary", use_container_width=True):
                load_vocab_dataframe(active_worksheet, force_reload=True)
                st.success("✅ 快取已清除！")
                time.sleep(0.5)
                st.rerun()

        st.markdown("---")
        with st.container(border=True):
            st.markdown("#### 🚨 終極字典聯網一鍵補齊專區")
            st.warning("點擊下方按鈕，系統將透過『三大免費開源字典 API (Datamuse/FreeDict/Wiktionary)』為所有單字尋找最道地的英文解釋：")
            if st.button("🧹 一鍵聯網補齊真實英文釋義", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                df_current = load_vocab_dataframe(active_worksheet).copy()
                total_fix = len(df_current)
                fixed_count = 0
                
                for idx, row in df_current.iterrows():
                    w = str(row['word']).strip()
                    d = str(row.get('definition', '')).strip()
                    status_text.text(f"🤖 正在從多重字典庫中搜尋 ({fixed_count+1}/{total_fix}): {w}")
                    
                    new_data = get_word_record_data_via_ai(w, raw_def=d, level=selected_level)
                    df_current.at[idx, 'advanced_sentence'] = new_data.get('advanced_sentence', '')
                    
                    # 避免洗掉已存在的良好例句
                    if not row.get('basic_sentence'):
                        df_current.at[idx, 'basic_sentence'] = new_data.get('basic_sentence', '')
                    
                    fixed_count += 1
                    progress_bar.progress(fixed_count / total_fix)
                    time.sleep(0.5)
                    
                save_all_vocab_to_sheet(active_worksheet, df_current)
                status_text.success(f"🎉 成功完成真實字典釋義補齊！總共更新了 {fixed_count} 個單字。")
                time.sleep(1.5)
                st.rerun()

        filtered_df = df_vocab if selected_unit_filter == "全部單字" else df_vocab[df_vocab['unit_tag'] == selected_unit_filter]
        
        col_s1, col_s2 = st.columns([2, 1])
        with col_s1:
            search_query = st.text_input("🔍 搜尋單字或釋義：")
        with col_s2:
            words_to_delete = st.multiselect("🗑️ 勾選要刪除的單字：", filtered_df['word'].tolist(), placeholder="選擇要刪除的單字...")

        if search_query:
            filtered_df = filtered_df[filtered_df['word'].str.contains(search_query, case=False, na=False) | filtered_df['definition'].str.contains(search_query, case=False, na=False)]
        
        if words_to_delete:
            if st.button("⚠️ 確認刪除已勾選的單字", type="primary"):
                df_current = load_vocab_dataframe(active_worksheet)
                df_current = df_current[~df_current['word'].isin(words_to_delete)]
                save_all_vocab_to_sheet(active_worksheet, df_current)
                st.success("已成功刪除勾選的單字！")
                st.rerun()

        with st.expander("📋 單字總表與快速編輯（精緻適中寬度）", expanded=True):
            st.dataframe(
                filtered_df[['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'advanced_sentence', 'basic_sentence']],
                use_container_width=False,
                hide_index=True,
                column_config={
                    "id": st.column_config.NumberColumn("編號", width="small"),
                    "word": st.column_config.TextColumn("單字", width="medium"),
                    "phonetic": st.column_config.TextColumn("音標", width="small"),
                    "part_of_speech": st.column_config.TextColumn("詞性", width="small"),
                    "definition": st.column_config.TextColumn("中文釋義", width="medium"),
                    "advanced_sentence": st.column_config.TextColumn("英文釋義", width="large"),
                    "basic_sentence": st.column_config.TextColumn("真實例句", width="large"),
                }
            )
            
            st.markdown("<br>", unsafe_allow_html=True)
            with st.container(border=True):
                st.markdown("#### ✏️ 雲端單字快速編輯修正")
                if not filtered_df.empty:
                    word_options = {f"{row['word']} ({row['definition'] if row['definition'] else '無中文'})": row for _, row in filtered_df.iterrows()}
                    selected_option = st.selectbox("選擇要編輯的單字：", list(word_options.keys()), key="table_edit_select")
                    
                    if selected_option:
                        target_row = word_options[selected_option]
                        with st.form(key=f"table_edit_form_{target_row['word']}"):
                            col_e1, col_e2, col_e3 = st.columns(3)
                            with col_e1:
                                edit_word = st.text_input("單字 (Word)", value=target_row['word'])
                            with col_e2:
                                edit_phonetic = st.text_input("音標 (Phonetic)", value=target_row.get('phonetic', ''))
                            with col_e3:
                                edit_pos = st.text_input("詞性 (POS)", value=target_row.get('part_of_speech', ''))
                                
                            edit_def = st.text_input("中文釋義 (Definition)", value=target_row.get('definition', ''))
                            edit_adv = st.text_input("英文釋義 (English Def)", value=target_row.get('advanced_sentence', ''))
                            edit_basic = st.text_area("真實例句 (Sentence)", value=target_row.get('basic_sentence', ''))
                            
                            submit_table_edit = st.form_submit_button("💾 儲存修改至雲端", type="primary")
                            
                            if submit_table_edit:
                                df_current = load_vocab_dataframe(active_worksheet)
                                idxs = df_current.index[df_current['word'] == target_row['word']].tolist()
                                if idxs:
                                    idx = idxs[0]
                                    df_current.at[idx, 'word'] = edit_word
                                    df_current.at[idx, 'phonetic'] = edit_phonetic
                                    df_current.at[idx, 'part_of_speech'] = edit_pos
                                    df_current.at[idx, 'definition'] = simple_s2t_convert(edit_def)
                                    df_current.at[idx, 'advanced_sentence'] = edit_adv
                                    df_current.at[idx, 'basic_sentence'] = edit_basic
                                    save_all_vocab_to_sheet(active_worksheet, df_current)
                                    st.success("✅ 雲端修改成功！")
                                    time.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error("❌ 修改失敗：找不到該單字")

elif main_menu == "🎯 沉浸式閃卡複習":
    if df_vocab.empty:
        st.warning("📭 目前雲端沒有單字！")
    else:
        if "flashcard_index" not in st.session_state: st.session_state.flashcard_index = 0
        total_count = len(df_vocab)
        st.session_state.flashcard_index = st.session_state.flashcard_index % total_count
        row = df_vocab.iloc[st.session_state.flashcard_index]
        
        with st.container(border=True):
            st.markdown(f"<h1 style='text-align: center; font-size: 54px;'>🔤 {row['word']}</h1>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align: center; color: gray;'>{row.get('phonetic','')} | {row.get('part_of_speech','')}</p>", unsafe_allow_html=True)
            
            # 常駐顯示的中英文解釋與例句區塊
            st.markdown("---")
            st.markdown(f"<h4 style='color: #4CAF50;'>📌 中文釋義：{row['definition']}</h4>", unsafe_allow_html=True)
            st.markdown(f"<p style='color: #2196F3; font-weight: bold;'>📖 英文釋義：{row.get('advanced_sentence', 'No definition available.')}</p>", unsafe_allow_html=True)
            if row.get('basic_sentence'):
                st.markdown(f"<p style='font-style: italic; color: #555;'>💬 例句：{row.get('basic_sentence')}</p>", unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            # 多國口音發音按鈕區
            st.markdown("<p style='text-align: center; font-weight: bold;'>🔊 點擊聆聽多國口音發音：</p>", unsafe_allow_html=True)
            ac_col1, ac_col2, ac_col3 = st.columns(3)
            with ac_col1:
                if st.button("🇺🇸 美式發音 (US)", use_container_width=True):
                    try:
                        audio_us = generate_audio_bytes(row['word'], tld='com')
                        st.audio(audio_us, format="audio/mp3", autoplay=True)
                    except:
                        pass
            with ac_col2:
                if st.button("🇬🇧 英式發音 (UK)", use_container_width=True):
                    try:
                        audio_uk = generate_audio_bytes(row['word'], tld='co.uk')
                        st.audio(audio_uk, format="audio/mp3", autoplay=True)
                    except:
                        pass
            with ac_col3:
                if st.button("🇦🇺 澳洲發音 (AU)", use_container_width=True):
                    try:
                        audio_au = generate_audio_bytes(row['word'], tld='com.au')
                        st.audio(audio_au, format="audio/mp3", autoplay=True)
                    except:
                        pass
        
        c1, c2 = st.columns(2)
        if c1.button("⬅️ 上一個", use_container_width=True):
            st.session_state.flashcard_index = (st.session_state.flashcard_index - 1) % total_count
            st.rerun()
        if c2.button("➡️ 下一個", use_container_width=True):
            st.session_state.flashcard_index = (st.session_state.flashcard_index + 1) % total_count
            st.rerun()

elif main_menu == "🎮 拼字王挑戰遊戲":
    if df_vocab.empty:
        st.warning("📭 目前沒有足夠的單字來進行遊戲！")
    else:
        unit_list_game = ["全部單字"] + sorted(df_vocab['unit_tag'].dropna().unique().tolist()) if 'unit_tag' in df_vocab.columns else ["全部單字"]
        selected_game_unit = st.selectbox("選擇遊戲挑戰的單元範圍：", unit_list_game, key="game_unit_select")
        
        df_filtered_game = df_vocab if selected_game_unit == "全部單字" else df_vocab[df_vocab['unit_tag'] == selected_game_unit]
        
        if df_filtered_game.empty:
            st.warning("📭 該分類中沒有單字！")
        else:
            if "game_started" not in st.session_state or st.session_state.get("current_game_unit") != selected_game_unit:
                st.session_state.game_started = True
                st.session_state.current_game_unit = selected_game_unit
                st.session_state.game_queue = df_filtered_game.sample(frac=1).to_dict('records')
                st.session_state.game_index = 0
                st.session_state.wrong_answers = []
                st.session_state.is_finished = False
                st.session_state.last_feedback = None
                
                if "user_spelling_input" not in st.session_state:
                    st.session_state.user_spelling_input = ""

            def process_answer(is_skip=False):
                if st.session_state.game_index >= len(st.session_state.game_queue):
                    return
                    
                current_item = st.session_state.game_queue[st.session_state.game_index]
                target_word = str(current_item['word']).strip()
                user_ans = st.session_state.user_spelling_input.strip().lower()

                if is_skip:
                    if current_item not in st.session_state.wrong_answers:
                        st.session_state.wrong_answers.append(current_item)
                    st.session_state.last_feedback = {
                        "type": "error", 
                        "msg": f"⏩ 已略過。正確答案是：`{target_word}`"
                    }
                else:
                    if user_ans == target_word.lower():
                        st.session_state.last_feedback = {
                            "type": "success", 
                            "msg": f"🎉 上題答對了！就是 `{target_word}`"
                        }
                    else:
                        if current_item not in st.session_state.wrong_answers:
                            st.session_state.wrong_answers.append(current_item)
                        st.session_state.last_feedback = {
                            "type": "error", 
                            "msg": f"❌ 上題答錯囉！正確答案是：`{target_word}`"
                        }
                
                st.session_state.game_index += 1
                st.session_state.user_spelling_input = ""

            if st.session_state.game_index >= len(st.session_state.game_queue):
                st.session_state.is_finished = True

            if st.session_state.get("is_finished", False):
                st.balloons()
                st.markdown("## 🎉 測驗圓滿結束！")
                total_q = len(st.session_state.game_queue)
                wrong_q = len(st.session_state.wrong_answers)
                correct_q = total_q - wrong_q
                
                col_res1, col_res2 = st.columns(2)
                col_res1.metric(label="總題數", value=f"{total_q} 題")
                col_res2.metric(label="答對題數", value=f"{correct_q} 題")
                
                if wrong_q > 0:
                    st.markdown("---")
                    st.markdown(f"### ❌ 總共錯誤題數：{wrong_q} 題（錯題訂正複習）：")
                    for w_item in st.session_state.wrong_answers:
                        st.markdown(f"- **中文釋義：** {w_item['definition']} ➡️ **正確英文單字：** `{w_item['word']}`")
                else:
                    st.success("🏆 太神啦！全部答對，完美過關！")

                if st.button("🔄 重新挑戰本單元", type="primary", use_container_width=True):
                    del st.session_state["game_started"]
                    st.rerun()
                    
            else:
                current_item = st.session_state.game_queue[st.session_state.game_index]
                target_word = str(current_item['word']).strip()
                target_def = str(current_item['definition']).strip() if str(current_item['definition']).strip() else "(尚無中文釋義)"
                hint_masked = "".join([" _ " if c.isalpha() else "   " for c in target_word])
                
                st.markdown(f"### 📊 進度：第 `{st.session_state.game_index + 1}` 題 / 共 `{len(st.session_state.game_queue)}` 題")
                
                with st.container(border=True):
                    st.markdown(f"<h2 style='color: #4CAF50;'>📌 中文釋義：{target_def}</h2>", unsafe_allow_html=True)
                    st.markdown(f"**🔤 拼字提示：** `{hint_masked}` &nbsp;&nbsp; (長度: {len(target_word)} 字母)")
                    
                    audio = generate_audio_bytes(target_word)
                    try: 
                        st.audio(audio, format="audio/mp3")
                    except: 
                        pass

                if st.session_state.get("last_feedback"):
                    fb = st.session_state.last_feedback
                    if fb["type"] == "success":
                        st.success(fb["msg"])
                    else:
                        st.error(fb["msg"])
                        
                current_wrong_count = len(st.session_state.wrong_answers)
                if current_wrong_count > 0:
                    st.markdown(f"<h4 style='color: #E53935;'>🛑 目前累積錯題數：{current_wrong_count} 題</h4>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<h4 style='color: #757575;'>🛑 目前累積錯題數：0 題 (完美狀態 ✨)</h4>", unsafe_allow_html=True)
                st.markdown("---")

                st.text_input(
                    "📝 請輸入您的拼寫答案 (輸入完畢可直接按 Enter 送出)：", 
                    key="user_spelling_input",
                    on_change=process_answer,
                    kwargs={"is_skip": False}
                )
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    st.button(
                        "🚀 送出答案", 
                        type="primary", 
                        use_container_width=True, 
                        on_click=process_answer, 
                        kwargs={"is_skip": False}
                    )
                with col_btn2:
                    st.button(
                        "⏭️ 略過本題", 
                        use_container_width=True, 
                        on_click=process_answer, 
                        kwargs={"is_skip": True}
                    )
