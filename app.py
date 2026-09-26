import pandas as pd
import streamlit as st
import json
import os
import time
import docx
import random
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

# 注入自訂 CSS，讓表格儲存格文字自動換行與撐開高度
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
    st.sidebar.info("💡 未填寫 API Key 時將啟用精確情境組合引擎")

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
            f"The secret passage is hidden securely {w_lower} the old stone wall.",
            f"Light streamed gently {w_lower} the cracks of the wooden shutters."
        ]
        return random.choice(templates)
        
    elif w_lower in ["maybe", "perhaps", "actually", "probably", "certainly", "definitely"]:
        templates = [
            f"To be honest, I {w_lower} think we should reconsider our original plan.",
            f"She {w_lower} surprised everyone by finishing the difficult project ahead of schedule.",
            f"It is {w_lower} vital that we double-check all the details before submission."
        ]
        return random.choice(templates)
        
    elif w_lower in ["usually", "always", "often", "sometimes", "never", "seldom", "rarely"]:
        templates = [
            f"Despite her busy schedule, she {w_lower} finds time to read inspirational books.",
            f"Our team {w_lower} gathers on Monday mornings to discuss weekly milestones."
        ]
        return random.choice(templates)
        
    elif w_lower in ["but", "yet", "and", "or", "so"]:
        templates = [
            f"The experiment faced several unexpected setbacks, {w_lower} the researchers refused to give up.",
            f"You can choose to work on the report now, {w_lower} you can finish it tomorrow morning."
        ]
        return random.choice(templates)
    elif w_lower in ["however", "therefore", "moreover"]:
        return f"The initial results looked quite promising; {w_lower}, we need further testing to confirm."
    elif w_lower in ["although", "though", "because", "since", "if", "when", "while"]:
        templates = [
            f"{w_clean.capitalize()} the weather conditions turned severe, the flight departed on time.",
            f"We decided to postpone the outdoor event {w_lower} heavy rain was forecasted."
        ]
        return random.choice(templates)

    elif any(k in d_clean for k in ["吃", "喝", "做", "跑", "走", "看", "聽", "寫", "買", "賣", "說", "想", "玩", "學", "教", "去", "來", "幫助", "使用", "打破", "裂"]):
        templates = [
            f"It is essential to learn how to {w_clean} effectively in real-world situations.",
            f"They gathered together to {w_clean} and share their creative ideas with each other.",
            f"She always tries her best to {w_clean} whenever someone asks for assistance."
        ]
        return random.choice(templates)

    elif any(k in d_clean for k in ["顏色", "紅", "藍", "綠", "黃", "黑", "白", "灰", "棕", "紫", "粉", "橘"]):
        templates = [
            f"The interior designer chose a striking {w_clean} hue to brighten up the living room.",
            f"He wore a classic suit accented with a subtle {w_clean} tie for the interview."
        ]
        return random.choice(templates)

    elif any(k in d_clean for k in ["牆", "門", "窗", "地板", "天花板", "屋頂", "樓梯"]):
        templates = [
            f"Sunlight poured directly through the large glass {w_clean} into the studio.",
            f"They decorated the old brick {w_clean} with vintage posters and photographs."
        ]
        return random.choice(templates)

    elif any(k in d_clean for k in ["浴室", "廁所", "洗手間", "馬桶"]):
        templates = [
            f"Please ensure the {w_clean} is kept clean and well-ventilated after use.",
            f"Visitors can find the public {w_clean} just past the main reception desk."
        ]
        return random.choice(templates)

    elif any(k in d_clean for k in ["人", "員", "父母", "父親", "母親", "朋友", "學生", "老師", "家", "孩", "男", "女", "師", "長", "客"]):
        templates = [
            f"The dedicated {w_clean} worked tirelessly to ensure the project succeeded.",
            f"We were deeply impressed by how friendly and helpful the local {w_clean} were."
        ]
        return random.choice(templates)
        
    elif any(k in d_clean for k in ["地方", "室", "房", "家", "廚房", "客廳", "學校", "銀行", "店", "館", "園", "場", "站", "區", "餐廳"]):
        templates = [
            f"Locals often gather at this popular {w_clean} to socialize on weekends.",
            f"We spent hours exploring the charming old {w_clean} located downtown."
        ]
        return random.choice(templates)
        
    elif any(k in d_clean for k in ["筆記本", "書", "紙", "筆", "鉛筆", "本子"]):
        if is_plural:
            templates = [
                f"He always keeps several neat {w_clean} on his desk for daily notes.",
                f"She organized all her old {w_clean} neatly on the wooden bookshelf."
            ]
        else:
            templates = [
                f"She opened her brand new {w_clean} and began jotting down important ideas.",
                f"He always carries a small {w_clean} with him to write down sudden inspirations."
            ]
        return random.choice(templates)

    elif any(k in d_clean for k in ["桌", "椅", "沙發", "床", "家具", "物品", "禮物", "盒", "車", "包", "杯", "瓶", "衣", "鞋"]):
        if is_plural:
            templates = [
                f"Please put all these heavy {w_clean} into the storage room carefully.",
                f"She received many wonderful {w_clean} from her friends on her birthday."
            ]
        else:
            templates = [
                f"There is a beautiful wooden {w_clean} placed right in the center of the room.",
                f"He bought a very expensive {w_clean} as a reward for his hard work this year."
            ]
        return random.choice(templates)

    elif any(k in d_clean for k in ["餅乾", "食物", "水", "蘋果", "麵包", "茶", "咖啡", "肉", "果", "菜", "蛋", "奶", "湯", "飯"]):
        templates = [
            f"Having some fresh {w_clean} is a great way to start your energetic morning.",
            f"We ordered some delicious {w_clean} to share while watching the late-night movie."
        ]
        return random.choice(templates)
        
    elif any(k in d_clean for k in ["鼠", "動物", "貓", "狗", "鳥", "魚", "兔", "牛", "羊", "馬", "豬", "蟲", "魔術"]):
        templates = [
            f"Researchers observed how the rare {w_clean} adapts to seasonal environmental shifts.",
            f"A fascinating documentary about {w_clean} captured our attention all evening."
        ]
        return random.choice(templates)
        
    elif any(k in d_clean for k in ["特別", "重要", "好", "壞", "大", "小", "高", "低", "長", "短", "新", "舊", "老", "少", "多", "餓", "累", "快樂", "傷心", "生氣", "忙", "冷", "熱", "漂亮", "聰明", "困難", "簡單", "清楚", "魔幻"]):
        templates = [
            f"It was a truly {w_clean} moment that everyone in the room will always remember.",
            f"She approached the challenge with a remarkably {w_clean} perspective.",
            f"Finding a reliable solution to this issue proved to be quite {w_clean}."
        ]
        return random.choice(templates)
        
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

    # 動態智能英文釋義備用庫（當無 API Key 時自動精確對應）
    fallback_eng_def = f"A term or concept referring to {w_clean}."
    if w_lower in ["cookie", "food"]:
        fallback_eng_def = "Something that people eat or provide for nourishment."
    elif w_lower in ["notebook"]:
        fallback_eng_def = "A book of blank pages for writing notes in."
    elif w_lower in ["dining room"]:
        fallback_eng_def = "A room in a house or hotel where meals are eaten."
    elif w_lower in ["magic"]:
        fallback_eng_def = "The power of apparently influencing events by using mysterious or supernatural forces."
    elif w_lower in ["eat"]:
        fallback_eng_def = "To put food into the mouth, chew it, and swallow it."

    if HAS_GEMINI and st.session_state.get("gemini_api_key"):
        for attempt in range(2):
            try:
                genai.configure(api_key=st.session_state["gemini_api_key"])
                model = genai.GenerativeModel("gemini-1.5-flash")
                prompt = (
                    f"你是一個專業的英語字典與教師。請針對英文單字或片語「{w_clean}」（中文解釋為：{cleaned_def}，適用級別：{level}），"
                    "請提供一句簡明扼要的英文釋義（English definition，例如：A book of blank pages for notes.）與一句道地的英文例句。"
                    "嚴格回傳以下純 JSON 格式，絕對不要包含任何其他文字或標記：\n"
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
                    start_idx = raw_text.find("{")
                    end_idx = raw_text.rfind("}") + 1
                    raw_text = raw_text[start_idx:end_idx]
                    
                data = json.loads(raw_text)
                return {
                    "word": w_clean,
                    "phonetic": data.get("phonetic", f"/{w_lower.replace(' ', '')}/"),
                    "part_of_speech": simple_s2t_convert(data.get("part_of_speech", "n.")),
                    "definition": cleaned_def,
                    "advanced_sentence": data.get("english_definition", fallback_eng_def),
                    "basic_sentence": data.get("sentence", generate_dynamic_single_sentence(w_clean, cleaned_def))
                }
            except Exception:
                time.sleep(1)
            
    return {
        "word": w_clean,
        "phonetic": f"/{w_lower.replace(' ', '')}/",
        "part_of_speech": "n.",
        "definition": cleaned_def,
        "advanced_sentence": fallback_eng_def,
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
                with st.spinner("🤖 正在查閱字典並生成中英文解釋與例句中..."):
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
                    st.info(f"📑 結構化解析完畢！共鎖定表格找到 **{total_words_to_process}** 個有效單字與中文解釋。")
                    
                    progress_bar = st.progress(0)
                    status_ui = st.empty()
                    
                    df_current = load_vocab_dataframe(active_worksheet)
                    total_success_count = 0
                    
                    for i, item in enumerate(extracted_data_list):
                        word = item["word"]
                        raw_def = item["definition"]
                        remaining_words = total_words_to_process - (i + 1)
                        
                        status_ui.markdown(
                            f"**⏳ 匯入進度：** `{(i+1)} / {total_words_to_process}`\n\n"
                            f"👉 目前正在處理： **{word}** (中文: {raw_def})\n\n"
                            f"🎯 還剩下 **{remaining_words}** 個單字即可完成！"
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
                        time.sleep(0.02)
                        
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
            st.markdown("#### 🚨 單字中英文釋義與例句一鍵升級專區")
            st.warning("點擊下方按鈕，系統將為所有現有單字自動補齊「英文釋義」與道地例句並寫回雲端：")
            if st.button("🧹 一鍵升級中英文釋義與例句", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                df_current = load_vocab_dataframe(active_worksheet).copy()
                total_fix = len(df_current)
                fixed_count = 0
                
                for idx, row in df_current.iterrows():
                    w = str(row['word']).strip()
                    d = str(row.get('definition', '')).strip()
                    status_text.text(f"🤖 正在為單字補齊中英文釋義 ({fixed_count+1}/{total_fix}): {w}")
                    
                    new_data = get_word_record_data_via_ai(w, raw_def=d, level=selected_level)
                    df_current.at[idx, 'advanced_sentence'] = new_data.get('advanced_sentence', '')
                    df_current.at[idx, 'basic_sentence'] = new_data.get('basic_sentence', '')
                    
                    fixed_count += 1
                    progress_bar.progress(fixed_count / total_fix)
                    time.sleep(0.01)
                    
                save_all_vocab_to_sheet(active_worksheet, df_current)
                status_text.success(f"🎉 成功完成升級！總共更新了 {fixed_count} 個單字。")
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
