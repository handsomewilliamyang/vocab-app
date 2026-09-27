import pandas as pd
import streamlit as st
import json
import os
import time
import docx
import random
import requests
import re  
from gtts import gTTS
import io
import base64
import streamlit.components.v1 as components

import gspread
from google.oauth2.service_account import Credentials

try:
    import fitz  # PyMuPDF 用於高效解析 PDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

st.set_page_config(
    page_title="我愛背單字",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .stDataFrame [data-testid="stTable"] td, .stDataFrame div[data-baseweb="table"] td, div[data-testid="stDataFrame"] div.dvn-scroller td {
        white-space: normal !important;
        word-wrap: break-word !important;
        height: auto !important;
        padding-top: 10px !important;
        padding-bottom: 10px !important;
    }
    audio {
        display: none !important;
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
    ["✨ 新增單字", "📖 字彙管理", "🎯 背誦單字", "🎮 我是拼字王"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")
st.sidebar.markdown("##### 📚 選擇目標語料庫級別：")

selected_level = st.sidebar.radio(
    "選擇目前目標級別：",
    ["國中部", "高中部", "TOEIC"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "<p style='text-align: center; color: gray; font-size: 13px; margin-top: 20px;'>版權所有，切勿模仿</p>",
    unsafe_allow_html=True
)

hidden_api_key = st.secrets.get("gemini_api_key", "")
if hidden_api_key and HAS_GEMINI:
    genai.configure(api_key=hidden_api_key)
    st.session_state.gemini_api_key = hidden_api_key
else:
    st.session_state.gemini_api_key = ""

level_sheet_mapping = {
    "國中部": "國中部",
    "高中部": "高中部",
    "TOEIC": "多益"
}
current_sheet_name = level_sheet_mapping.get(selected_level, "國中部")

try:
    spreadsheet = gs_client.open_by_url(SHEET_URL)
    try:
        active_worksheet = spreadsheet.worksheet(current_sheet_name)
    except Exception:
        try:
            active_worksheet = spreadsheet.add_worksheet(title=current_sheet_name, rows="1000", cols="10")
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
    "默认": "預設", "句": "句", "词": "词", "语法": "語法"
}

def simple_s2t_convert(text):
    if not text: return text
    for s, t in S2T_DICT.items():
        text = text.replace(s, t)
    return text

def is_bad_example_sentence(sentence):
    s = str(sentence or "").strip()
    if not s or s.lower() == "nan" or len(s) < 8:
        return True
    return False

def fetch_tatoeba_example(word):
    w_clean = word.strip().lower()
    try:
        url = f"https://api.tatoeba.org/unstable/sentences?q={w_clean}&from=eng&limit=3"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=2)
        if res.status_code == 200:
            data = res.json()
            results = data.get('results', [])
            for item in results:
                sent = item.get('text', '').strip()
                if sent and not is_bad_example_sentence(sent):
                    return sent, "Tatoeba 句庫"
    except Exception:
        pass
    return "", ""

def fetch_all_free_dictionaries(word):
    w_clean = word.strip().lower()
    real_def = ""
    real_example = ""
    phonetic = ""
    pos = ""
    source_used = "無"

    try:
        url_fd = f"https://api.dictionaryapi.dev/api/v2/entries/en/{w_clean}"
        res_fd = requests.get(url_fd, timeout=2)
        if res_fd.status_code == 200:
            data = res_fd.json()
            if isinstance(data, list) and len(data) > 0:
                entry = data[0]
                if 'phonetic' in entry:
                    phonetic = entry['phonetic']
                elif 'phonetics' in entry and len(entry['phonetics']) > 0:
                    for p in entry['phonetics']:
                        if p.get('text'):
                            phonetic = p.get('text')
                            break
                
                for meaning in entry.get('meanings', []):
                    if not pos:
                        pos = meaning.get('partOfSpeech', '')
                    for definition_obj in meaning.get('definitions', []):
                        if not real_def:
                            real_def = definition_obj.get('definition', '')
                        ex_candidate = definition_obj.get('example', '')
                        if ex_candidate and not is_bad_example_sentence(ex_candidate):
                            real_example = ex_candidate
                        if real_def and real_example:
                            break
                    if real_def and real_example:
                        break
                if real_def:
                    source_used = "DictionaryAPI.dev"
    except Exception:
        pass

    if not real_example or not real_def:
        try:
            url_harika = f"https://dictionary-api-7hmy.onrender.com/define?word={w_clean}"
            res_h = requests.get(url_harika, timeout=2)
            if res_h.status_code == 200:
                h_data = res_h.json()
                if not real_def and h_data.get('definition'):
                    real_def = h_data.get('definition')
                ex_candidate = h_data.get('example', '')
                if not real_example and ex_candidate and not is_bad_example_sentence(ex_candidate):
                    real_example = ex_candidate
                if not pos and h_data.get('partOfSpeech'):
                    pos = h_data.get('partOfSpeech')
                if real_def and source_used == "無":
                    source_used = "Harika Dictionary API"
        except Exception:
            pass

    if not real_example:
        tatoeba_sent, t_src = fetch_tatoeba_example(w_clean)
        if tatoeba_sent:
            real_example = tatoeba_sent
            if source_used == "無":
                source_used = t_src

    return real_def, real_example, phonetic, pos, source_used

def get_word_record_data_via_ai(word, raw_def="", raw_sentence="", raw_collocations="", level="高中部"):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    cleaned_def = simple_s2t_convert(raw_def) if raw_def else f"{w_clean} 的中文釋義"

    trace_logs = []
    trace_logs.append(f"🎯 開始處理單字: 【{w_clean}】 (目標級別: {level})")

    final_sentence = raw_sentence.strip() if raw_sentence else ""
    final_collocations = raw_collocations.strip() if raw_collocations else ""

    if final_sentence:
        trace_logs.append(f"📂 偵測到上傳講義中已內建例句: 「{final_sentence}」")
    else:
        trace_logs.append(f"📂 上傳講義中無內建例句，開始向外部免費 API 查詢...")

    real_eng_def, real_example, fetched_phonetic, fetched_pos, dict_source = fetch_all_free_dictionaries(w_clean)
    
    trace_logs.append(f"🌐 外部字典回應來源: {dict_source}")
    trace_logs.append(f"   - 抓到的外部例句: {real_example if real_example else '(無)'}")

    final_eng_def = real_eng_def
    final_phonetic = fetched_phonetic
    final_pos = simple_s2t_convert(fetched_pos) if fetched_pos else ""

    if not final_sentence and real_example:
        final_sentence = real_example
        trace_logs.append(f"✅ 採用外部字典的例句: 「{final_sentence}」")

    missing_data = not final_eng_def or not final_sentence or not final_collocations
    ai_triggered = False

    if (missing_data or is_bad_example_sentence(final_sentence)) and HAS_GEMINI and st.session_state.get("gemini_api_key"):
        ai_triggered = True
        trace_logs.append(f"🤖 發現資料不齊全或例句為空，啟動 Gemini AI 進行動態補強...")
        genai.configure(api_key=st.session_state["gemini_api_key"])
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = f"""You are an expert English material creator for students in Taiwan.
Target Word: "{w_clean}"
Chinese Meaning: "{cleaned_def}"
Target Level: "{level}"

Please generate comprehensive learning materials for this word.
Output ONLY valid JSON in this exact format:
{{
  "phonetic": "/.../",
  "part_of_speech": "n. / v. / adj. / adv. / phr.",
  "english_definition": "Short and clear English definition.",
  "basic_sentence": "A highly natural, everyday conversational example sentence using the word.",
  "collocations": "2-3 common collocations or useful phrases"
}}"""
        
        ai_success = False
        for attempt in range(3):
            try:
                response = model.generate_content(prompt, generation_config={"temperature": 0.7})
                raw_text = response.text.strip()
                if "{" in raw_text and "}" in raw_text:
                    raw_text = raw_text[raw_text.find("{"):raw_text.rfind("}") + 1]
                data = json.loads(raw_text)
                
                ai_def = data.get("english_definition", "")
                ai_sent = data.get("basic_sentence", "")
                ai_colloc = data.get("collocations", "")
                
                if ai_def and not final_eng_def:
                    final_eng_def = ai_def
                if ai_sent and (not final_sentence or is_bad_example_sentence(final_sentence)):
                    final_sentence = ai_sent
                if ai_colloc and not final_collocations:
                    final_collocations = ai_colloc
                if not final_phonetic and data.get("phonetic"):
                    final_phonetic = data.get("phonetic")
                if not final_pos and data.get("part_of_speech"):
                    final_pos = simple_s2t_convert(data.get("part_of_speech", ""))
                
                trace_logs.append(f"✨ AI 補強成功！產出例句: {ai_sent}")
                ai_success = True
                break
            except Exception as e:
                # 捕獲 429 資源耗盡錯誤，強制加長等待時間避免崩潰
                if "429" in str(e) or "exhausted" in str(e).lower() or "quota" in str(e).lower():
                    trace_logs.append(f"⚠️ 觸發 AI 頻率限制 (429 Rate Limit)，等待 10 秒後重試...")
                    time.sleep(10)
                else:
                    trace_logs.append(f"⚠️ AI 第 {attempt+1} 次嘗試解析失敗: {e}")
                    time.sleep(2)
        
        if not ai_success:
            trace_logs.append(f"❌ AI 補強全數失敗，將維持空白，不再產生廢話罐頭句。")
    elif not ai_triggered:
        trace_logs.append(f"🎯 資料已經完全由檔案或外部字典滿足，無需呼叫 AI。")

    if not final_phonetic:
        final_phonetic = f"/{w_lower.replace(' ', '')}/"
    if not final_pos:
        final_pos = "phr." if " " in w_clean else "n."

    st.session_state["last_trace_log"] = trace_logs

    return {
        "word": w_clean,
        "phonetic": final_phonetic,
        "part_of_speech": final_pos,
        "definition": cleaned_def,
        "advanced_sentence": final_eng_def,
        "basic_sentence": final_sentence,
        "collocations": final_collocations
    }

def save_all_vocab_to_sheet(_worksheet, df):
    cache_key = f"vocab_df_{_worksheet.title}"
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
        st.session_state[cache_key] = df.copy()
        return True, "成功"
    except Exception as e:
        st.session_state[cache_key] = df.copy() 
        return False, str(e)

@st.cache_data(show_spinner=False)
def generate_audio_bytes(text, tld='com'):
    tts = gTTS(text=text, lang='en', tld=tld)
    fp = io.BytesIO()
    tts.write_to_fp(fp)
    return fp.getvalue()

st.title("📚 我愛背單字")

try:
    df_vocab = load_vocab_dataframe(active_worksheet)
except Exception:
    time.sleep(2)
    df_vocab = load_vocab_dataframe(active_worksheet, force_reload=True)

total_words = len(df_vocab)
col_m1, col_m2 = st.columns(2)
col_m1.metric(label="雲端總單字數", value=f"{total_words} 個")

clean_mode_name = main_menu.replace("✨ ", "").replace("📖 ", "").replace("🎯 ", "").replace("🎮 ", "")
col_m2.metric(label="目前模式", value=f"{clean_mode_name}【{selected_level}】")

st.markdown("<br>", unsafe_allow_html=True)

if main_menu == "✨ 新增單字":
    if selected_level == "國中部":
        semester = st.selectbox("選擇年級學期：", ["國一上", "國一下", "國二上", "國二下", "國三上", "國三下"])
    elif selected_level == "高中部":
        semester = st.selectbox("選擇年級學期：", ["高一上", "高一下", "高二上", "高二下", "高三上", "高三下"])
    else:
        semester = st.selectbox("選擇階段：", ["TOEIC核心", "TOEIC進階", "商用英文"])
    unit = st.selectbox("選擇課次單元：", ["第一課", "第二課", "第三課", "第四課", "第五課", "第六課"])
    current_unit_tag = f"{semester} > {unit}"
    
    st.markdown("---")

    col_input1, col_input2 = st.columns(2, gap="large")
    with col_input1:
        st.subheader("📝 單筆快速建檔")
        single_word = st.text_input("輸入想要學習的英文單字：", placeholder="例如：resilient")
        if st.button("🚀 查字典並寫入雲端", type="primary", use_container_width=True):
            if single_word:
                with st.spinner("🤖 正在透過雲端字典與 AI 產生完整學習模組..."):
                    data = get_word_record_data_via_ai(single_word, level=selected_level)
                    word = data.get('word')
                    
                    df_current = load_vocab_dataframe(active_worksheet)
                    if not df_current.empty and word.lower() in df_current['word'].str.lower().values:
                        idx = df_current.index[df_current['word'].str.lower() == word.lower()].tolist()[0]
                        for k in data:
                            if k != 'word' and data.get(k):
                                df_current.at[idx, k] = data.get(k)
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
                            'collocations': data.get('collocations', ''),
                            'unit_tag': current_unit_tag,
                            'srs_stage': 0
                        }])
                        df_current = pd.concat([df_current, new_row], ignore_index=True)
                        
                    save_all_vocab_to_sheet(active_worksheet, df_current)
                    st.success(f"🎉 成功新增單字：{word} | 中文：{data.get('definition')}")
                    time.sleep(0.5)
                    st.rerun()

    with col_input2:
        st.subheader("📂 多格式檔案智慧匯入")
        
        with st.container(border=True):
            st.markdown(f"**📌 目前目標分類：** `{current_unit_tag}`")
            st.markdown(f"**📊 雲端現有總單字數：** `{total_words} 個單字`")
            
        uploaded_files = st.file_uploader("上傳 Word、PDF 講義或單字照片", type=["docx", "pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        
        if uploaded_files:
            if st.button("📖 批次解析檔案並匯入", use_container_width=True):
                extracted_data_list = []
                with st.spinner("🔍 正在智慧讀取檔案中的單字與原創例句..."):
                    for uploaded_file in uploaded_files:
                        file_name = uploaded_file.name.lower()
                        if file_name.endswith(".docx"):
                            temp_path = f"temp_{uploaded_file.name}"
                            try:
                                with open(temp_path, "wb") as f:
                                    f.write(uploaded_file.getbuffer())
                                doc = docx.Document(temp_path)
                                for table in doc.tables:
                                    for row in table.rows:
                                        # 💡 智慧解析表格：無視欄位順序，自動判斷哪段是單字、哪段是中文、哪段是例句
                                        texts = []
                                        for c in row.cells:
                                            txt = c.text.strip().replace('\n', ' ')
                                            if txt and txt not in texts:
                                                texts.append(txt)
                                        
                                        w_c, d_c, s_c, c_c = "", "", "", ""
                                        for t in texts:
                                            if re.search(r'[\u4e00-\u9fff]', t): 
                                                d_c = d_c + " / " + t if d_c else t
                                            elif len(re.findall(r'[a-zA-Z]+', t)) >= 4: 
                                                if not s_c:
                                                    s_c = t
                                                else:
                                                    c_c = t
                                            elif not w_c and len(re.findall(r'[a-zA-Z]+', t)) <= 3 and not re.search(r'[\u4e00-\u9fff]', t):
                                                w_c = t
                                        
                                        w_c = re.sub(r'[^a-zA-Z\-\']', '', w_c)
                                        if w_c and len(w_c) > 1:
                                            if not any(item['word'].lower() == w_c.lower() for item in extracted_data_list):
                                                extracted_data_list.append({"word": w_c, "definition": d_c, "sentence": s_c, "collocations": c_c})
                                if os.path.exists(temp_path): os.remove(temp_path)
                            except:
                                if os.path.exists(temp_path): os.remove(temp_path)
                        elif file_name.endswith(".pdf") and HAS_FITZ:
                            temp_path = f"temp_{uploaded_file.name}"
                            try:
                                with open(temp_path, "wb") as f:
                                    f.write(uploaded_file.getbuffer())
                                doc = fitz.open(temp_path)
                                pdf_text = ""
                                for page in doc:
                                    pdf_text += page.get_text() + "\n"
                                doc.close()
                                if os.path.exists(temp_path): os.remove(temp_path)
                                if HAS_GEMINI and st.session_state.get("gemini_api_key"):
                                    genai.configure(api_key=st.session_state["gemini_api_key"])
                                    model = genai.GenerativeModel("gemini-1.5-flash")
                                    prompt = f"從以下PDF文字中萃取出所有英文單字、中文釋義、例句與搭配詞，嚴格以純 JSON 陣列格式回傳（範例：[{{\"word\": \"apple\", \"definition\": \"蘋果\", \"sentence\": \"I ate an apple.\", \"collocations\": \"red apple\"}}]）：\n{pdf_text[:4000]}"
                                    res = model.generate_content(prompt)
                                    raw_t = res.text.strip()
                                    if "[" in raw_t and "]" in raw_t:
                                        raw_t = raw_t[raw_t.find("["):raw_t.rfind("]") + 1]
                                        parsed_items = json.loads(raw_t)
                                        for pi in parsed_items:
                                            if "word" in pi and "definition" in pi:
                                                if not any(item['word'].lower() == pi['word'].lower() for item in extracted_data_list):
                                                    extracted_data_list.append({
                                                        "word": pi['word'].strip(), 
                                                        "definition": pi['definition'].strip(), 
                                                        "sentence": pi.get('sentence', '').strip(),
                                                        "collocations": pi.get('collocations', '').strip()
                                                    })
                            except:
                                if os.path.exists(temp_path): os.remove(temp_path)
                        elif file_name.endswith((".png", ".jpg", ".jpeg")) and HAS_GEMINI and st.session_state.get("gemini_api_key"):
                            try:
                                image_bytes = uploaded_file.getvalue()
                                genai.configure(api_key=st.session_state["gemini_api_key"])
                                model = genai.GenerativeModel("gemini-1.5-flash")
                                image_part = {"mime_type": uploaded_file.type, "data": image_bytes}
                                prompt = "請辨識這張圖片中的所有英文單字、中文釋義、例句與搭配詞，嚴格以純 JSON 陣列格式回傳（範例：[{{\"word\": \"apple\", \"definition\": \"蘋果\", \"sentence\": \"I ate an apple.\", \"collocations\": \"red apple\"}}]）"
                                response = model.generate_content([image_part, prompt])
                                raw_t = response.text.strip()
                                if "[" in raw_t and "]" in raw_t:
                                    raw_t = raw_t[raw_t.find("["):raw_t.rfind("]") + 1]
                                    parsed_items = json.loads(raw_t)
                                    for pi in parsed_items:
                                        if "word" in pi and "definition" in pi:
                                            if not any(item['word'].lower() == pi['word'].lower() for item in extracted_data_list):
                                                extracted_data_list.append({
                                                    "word": pi['word'].strip(), 
                                                    "definition": pi['definition'].strip(), 
                                                    "sentence": pi.get('sentence', '').strip(),
                                                    "collocations": pi.get('collocations', '').strip()
                                                })
                            except:
                                pass
                
                total_words_to_process = len(extracted_data_list)
                st.success(f"🎯 實際成功掃描並萃取出 **{total_words_to_process}** 個有效單字！")
                
                if total_words_to_process > 0:
                    progress_bar = st.progress(0)
                    df_current = load_vocab_dataframe(active_worksheet)
                    total_success_count = 0
                    
                    for i, item in enumerate(extracted_data_list):
                        word = item["word"]
                        raw_def = item["definition"]
                        raw_sent = item.get("sentence", "")
                        raw_col = item.get("collocations", "")
                        
                        w_data = get_word_record_data_via_ai(word, raw_def=raw_def, raw_sentence=raw_sent, raw_collocations=raw_col, level=selected_level)
                        
                        if not df_current.empty and word.lower() in df_current['word'].str.lower().values:
                            idx = df_current.index[df_current['word'].str.lower() == word.lower()].tolist()[0]
                            for k in w_data:
                                if k != 'word' and w_data.get(k):
                                    df_current.at[idx, k] = w_data.get(k)
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
                                'collocations': w_data.get('collocations', ''),
                                'unit_tag': current_unit_tag,
                                'srs_stage': 0
                            }])
                            df_current = pd.concat([df_current, new_row], ignore_index=True)
                            
                        total_success_count += 1
                        progress_bar.progress((i + 1) / total_words_to_process)
                        # 💡 保護 Gemini 免費版 15 RPM 限流：強制休息 4.5 秒，避免 AI 崩潰導致例句全空！
                        time.sleep(4.5)
                        
                    success, msg = save_all_vocab_to_sheet(active_worksheet, df_current)
                    if success:
                        st.success(f"🎊 檔案解析與匯入完成！成功寫入 {total_success_count} 個單字至雲端。")
                    else:
                        st.warning(f"⚠️ 雲端寫入遇到延遲，但資料已暫存於本地 ({msg})。")
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.warning("⚠️ 在上傳的檔案中找不到可識別的單字表格或內容。")

    st.markdown("---")
    with st.expander("🔍 最近一次單字解析與追蹤診斷報告 (Trace Log)", expanded=False):
        if "last_trace_log" in st.session_state and st.session_state["last_trace_log"]:
            st.markdown("以下是系統在處理上一個單字時的完整執行軌跡與決策過程：")
            for log_line in st.session_state["last_trace_log"]:
                st.text(log_line)
        else:
            st.info("尚無執行記錄，請嘗試新增一個單字來查看診斷報告。")

elif main_menu == "📖 字彙管理":
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
            if st.button("🔄 資料重組 (強制修復空白例句)", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                df_current = load_vocab_dataframe(active_worksheet, force_reload=True).copy()
                
                if selected_unit_filter != "全部單字":
                    target_indices = df_current[df_current['unit_tag'] == selected_unit_filter].index
                else:
                    target_indices = df_current.index
                
                total_fix = len(target_indices)
                fixed_count = 0
                
                for idx in target_indices:
                    row = df_current.loc[idx]
                    w = str(row['word']).strip()
                    d = str(row.get('definition', '')).strip()
                    current_sent = str(row.get('basic_sentence', '')).strip()
                    current_adv = str(row.get('advanced_sentence', '')).strip()
                    
                    if not current_sent or is_bad_example_sentence(current_sent) or "I often use" in current_sent:
                        new_data = get_word_record_data_via_ai(w, raw_def=d, level=selected_level)
                        for k in new_data:
                            if k != 'word' and new_data.get(k):
                                df_current.at[idx, k] = new_data.get(k)
                        time.sleep(4.5)
                    
                    fixed_count += 1
                    if total_fix > 0:
                        progress_bar.progress(fixed_count / total_fix)
                    
                success, msg = save_all_vocab_to_sheet(active_worksheet, df_current)
                if success:
                    st.success("✅ 資料重組完成！已成功為您清除爛例句並補齊資料。")
                else:
                    st.warning(f"⚠️ Google 雲端儲存稍有延遲 ({msg})，但畫面資料已更新成功！")
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

        with st.expander("📋 單字總表與快速編輯", expanded=True):
            st.dataframe(
                filtered_df[['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'advanced_sentence', 'basic_sentence', 'collocations']],
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
                    "collocations": st.column_config.TextColumn("搭配詞", width="medium"),
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
                            edit_colloc = st.text_input("搭配詞 (Collocations)", value=target_row.get('collocations', ''))
                            
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
                                    df_current.at[idx, 'collocations'] = edit_colloc
                                    save_all_vocab_to_sheet(active_worksheet, df_current)
                                    st.success("✅ 雲端修改成功！")
                                    time.sleep(0.5)
                                    st.rerun()

elif main_menu == "🎯 背誦單字":
    if df_vocab.empty:
        st.warning(f"📭 目前雲端沒有單字！")
    else:
        unit_list_flash = ["全部單字"] + sorted(df_vocab['unit_tag'].dropna().unique().tolist()) if 'unit_tag' in df_vocab.columns else ["全部單字"]
        selected_flash_unit = st.selectbox("🎯 選擇要複習的單元：", unit_list_flash, key="flash_unit_select")
        
        df_filtered_flash = df_vocab if selected_flash_unit == "全部單字" else df_vocab[df_vocab['unit_tag'] == selected_flash_unit]
        
        if df_filtered_flash.empty:
            st.warning("📭 該分類中沒有單字！")
        else:
            if "current_flash_unit" not in st.session_state or st.session_state.current_flash_unit != selected_flash_unit:
                st.session_state.current_flash_unit = selected_flash_unit
                st.session_state.flashcard_index = 0
                
            if "flashcard_index" not in st.session_state: st.session_state.flashcard_index = 0
            
            total_count = len(df_filtered_flash)
            st.session_state.flashcard_index = st.session_state.flashcard_index % total_count
            row = df_filtered_flash.iloc[st.session_state.flashcard_index]
            
            with st.container(border=True):
                st.markdown(f"<h1 style='text-align: center; font-size: 54px; margin-bottom: 0;'>{row['word']}</h1>", unsafe_allow_html=True)
                st.markdown(f"<p style='text-align: center; color: gray; margin-top: 5px;'>{row.get('phonetic','')} | {row.get('part_of_speech','')}</p>", unsafe_allow_html=True)
                
                ac_col1, ac_col2, ac_col3 = st.columns(3)
                with ac_col1:
                    if st.button("🔊 美式發音 (US)", use_container_width=True, key=f"us_{st.session_state.flashcard_index}"):
                        safe_w = row['word'].replace("'", "\\'").replace('"', '\\"')
                        components.html(f"""
                        <script>
                            if ('speechSynthesis' in window) {{
                                window.speechSynthesis.cancel();
                                var utterance = new SpeechSynthesisUtterance("{safe_w}");
                                utterance.lang = 'en-US';
                                utterance.rate = 0.9;
                                window.speechSynthesis.speak(utterance);
                            }}
                        </script>
                        """, height=0)
                with ac_col2:
                    if st.button("🔊 英式發音 (UK)", use_container_width=True, key=f"uk_{st.session_state.flashcard_index}"):
                        safe_w = row['word'].replace("'", "\\'").replace('"', '\\"')
                        components.html(f"""
                        <script>
                            if ('speechSynthesis' in window) {{
                                window.speechSynthesis.cancel();
                                var utterance = new SpeechSynthesisUtterance("{safe_w}");
                                utterance.lang = 'en-GB';
                                utterance.rate = 0.9;
                                window.speechSynthesis.speak(utterance);
                            }}
                        </script>
                        """, height=0)
                with ac_col3:
                    if st.button("🔊 澳洲發音 (AU)", use_container_width=True, key=f"au_{st.session_state.flashcard_index}"):
                        safe_w = row['word'].replace("'", "\\'").replace('"', '\\"')
                        components.html(f"""
                        <script>
                            if ('speechSynthesis' in window) {{
                                window.speechSynthesis.cancel();
                                var utterance = new SpeechSynthesisUtterance("{safe_w}");
                                utterance.lang = 'en-AU';
                                utterance.rate = 0.9;
                                window.speechSynthesis.speak(utterance);
                            }}
                        </script>
                        """, height=0)
                
                st.markdown("---")
                st.markdown(f"<h4 style='color: #4CAF50;'>中文釋義：{row['definition']}</h4>", unsafe_allow_html=True)
                st.markdown(f"<p style='color: #2196F3; font-weight: bold; font-size: 19px;'>📖 英文釋義：{row.get('advanced_sentence', 'No definition available.')}</p>", unsafe_allow_html=True)
                
                if row.get('basic_sentence'):
                    st.markdown(f"<p style='font-style: italic; font-weight: 500; font-size: 19px; color: #FFC107;'>💬 例句：{row.get('basic_sentence')}</p>", unsafe_allow_html=True)
                
                if row.get('collocations'):
                    st.markdown(f"<p style='font-weight: 500; font-size: 17px; color: #E91E63;'>🔗 搭配詞：{row.get('collocations')}</p>", unsafe_allow_html=True)
            
            c1, c2 = st.columns(2)
            if c1.button("⬅️ 上一個", use_container_width=True):
                st.session_state.flashcard_index = (st.session_state.flashcard_index - 1) % total_count
                st.rerun()
            if c2.button("➡️ 下一個", use_container_width=True):
                st.session_state.flashcard_index = (st.session_state.flashcard_index + 1) % total_count
                st.rerun()

elif main_menu == "🎮 我是拼字王":
    if df_vocab.empty:
        st.warning("📭 目前沒有足夠的單字來進行遊戲！")
    else:
        game_mode = st.radio("選擇遊戲模式：🎮", ["標準模式 (中文提示 + 發音)", "進階挑戰模式 (聽英文解釋拼單字)"], horizontal=True)
        st.markdown("---")
        
        unit_list_game = ["全部單字"] + sorted(df_vocab['unit_tag'].dropna().unique().tolist()) if 'unit_tag' in df_vocab.columns else ["全部單字"]
        selected_game_unit = st.selectbox("選擇遊戲挑戰的單元範圍：", unit_list_game, key="game_unit_select")
        
        df_filtered_game = df_vocab if selected_game_unit == "全部單字" else df_vocab[df_vocab['unit_tag'] == selected_game_unit]
        
        if df_filtered_game.empty:
            st.warning("📭 該分類中沒有單字！")
        else:
            state_key = f"game_started_{game_mode}"
            if state_key not in st.session_state or st.session_state.get("current_game_unit") != selected_game_unit or st.session_state.get("current_game_mode") != game_mode:
                st.session_state[state_key] = True
                st.session_state.current_game_unit = selected_game_unit
                st.session_state.current_game_mode = game_mode
                st.session_state.game_queue = df_filtered_game.sample(frac=1).to_dict('records')
                st.session_state.game_index = 0
                st.session_state.wrong_answers = []
                st.session_state.is_finished = False
                st.session_state.last_feedback = None

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
                    st.markdown(f"### ❌ 總共錯誤題數：{wrong_q} 題（錯題與英文解釋總複習）：")
                    for w_item in st.session_state.wrong_answers:
                        st.markdown(f"- **單字：** `{w_item['word']}` | **中文：** {w_item['definition']} \n  - 📖 **英文解釋：** _{w_item.get('advanced_sentence', '無')}_")
                else:
                    st.success("🏆 太神啦！全部答對，完美過關！")

                if st.button("🔄 重新挑戰本單元", type="primary", use_container_width=True):
                    del st.session_state[state_key]
                    st.rerun()
            else:
                current_item = st.session_state.game_queue[st.session_state.game_index]
                target_word = str(current_item['word']).strip()
                target_def = str(current_item['definition']).strip() if str(current_item['definition']).strip() else "(尚無中文釋義)"
                target_adv_def = str(current_item.get('advanced_sentence', '')).strip() or "No English definition provided."
                hint_masked = "".join([" _ " if c.isalpha() else "    " for c in target_word])
                
                current_idx = st.session_state.game_index + 1
                total_q_len = len(st.session_state.game_queue)
                
                def play_audio_compact_game(text_to_speak, label_key="🔊"):
                    safe_text = text_to_speak.replace("'", "\\'").replace('"', '\\"')
                    html_code = f"""
                    <!DOCTYPE html>
                    <html>
                    <head>
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <style>
                        body {{ margin: 0; padding: 0; background: transparent; }}
                        .speak-btn {{
                            width: 100%;
                            padding: 0.35rem 0.5rem;
                            background-color: transparent;
                            color: canvasText;
                            border: 1px solid rgba(128, 128, 128, 0.4);
                            border-radius: 0.4rem;
                            font-size: 14px;
                            font-family: inherit;
                            cursor: pointer;
                            text-align: center;
                            transition: all 0.2s ease;
                        }}
                        @media (prefers-color-scheme: dark) {{
                            .speak-btn {{ color: #ffffff; border-color: rgba(255, 255, 255, 0.3); }}
                        }}
                        .speak-btn:hover {{
                            background-color: rgba(128, 128, 128, 0.15);
                            border-color: #ff4b4b;
                            color: #ff4b4b;
                        }}
                    </style>
                    </head>
                    <body>
                        <button class="speak-btn" onclick="speakText()">{label_key}</button>
                        <script>
                            function speakText() {{
                                if ('speechSynthesis' in window) {{
                                    window.speechSynthesis.cancel();
                                    var utterance = new SpeechSynthesisUtterance("{safe_text}");
                                    utterance.lang = 'en-US';
                                    utterance.rate = 0.9;
                                    window.speechSynthesis.speak(utterance);
                                }}
                            }}
                        </script>
                    </body>
                    </html>
                    """
                    components.html(html_code, height=40)

                with st.container(border=True):
                    col_h1, col_h2, col_h3 = st.columns([5, 1, 1])
                    with col_h1:
                        if game_mode.startswith("標準"):
                            st.markdown(f"<h2 style='color: #4CAF50; margin: 0;'>中文釋義：{target_def}</h2>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<h4 style='color: #2196F3; margin: 0;'>📖 英文解釋：{target_adv_def}</h4>", unsafe_allow_html=True)
                    with col_h2:
                        try:
                            if game_mode.startswith("標準"):
                                play_audio_compact_game(target_word, "🔊 發音")
                            else:
                                play_audio_compact_game(target_adv_def, "🔊 發音")
                        except: pass
                    with col_h3:
                        st.markdown(f"<p style='text-align: right; color: gray; font-size: 18px; font-weight: bold; margin: 0; padding-top: 5px;'>{current_idx} / {total_q_len}</p>", unsafe_allow_html=True)
                    
                    st.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)
                    st.markdown(f"**🔤 拼字提示：** `{hint_masked}` &nbsp;&nbsp; (長度: {len(target_word)} 字母)")

                if st.session_state.get("last_feedback"):
                    fb = st.session_state.last_feedback
                    if fb["type"] == "success":
                        st.success(fb["msg"])
                    else:
                        st.error(fb["msg"])
                    
                    if st.button("➡️ 點擊進入下一題", type="primary", use_container_width=True):
                        st.session_state.last_feedback = None
                        st.session_state.game_index += 1
                        st.rerun()
                else:
                    with st.form(key=f"quiz_form_{st.session_state.game_index}"):
                        user_ans = st.text_input("📝 請輸入您的拼寫答案：", key=f"ans_input_{st.session_state.game_index}").strip().lower()
                        
                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1:
                            submit_ans = st.form_submit_button("🚀 送出答案", type="primary", use_container_width=True)
                        with col_btn2:
                            skip_ans = st.form_submit_button("⏭️ 略過本題", use_container_width=True)
                            
                        if submit_ans:
                            if user_ans == target_word.lower():
                                st.session_state.last_feedback = {"type": "success", "msg": f"🎉 答對了！就是 `{target_word}`"}
                            else:
                                if current_item not in st.session_state.wrong_answers:
                                    st.session_state.wrong_answers.append(current_item)
                                st.session_state.last_feedback = {"type": "error", "msg": f"❌ 答錯囉！正確答案是：`{target_word}` (英文解釋: {target_adv_def})"}
                            st.rerun()
                            
                        if skip_ans:
                            if current_item not in st.session_state.wrong_answers:
                                st.session_state.wrong_answers.append(current_item)
                            st.session_state.last_feedback = {"type": "error", "msg": f"⏩ 已略過。正確答案是：`{target_word}` (英文解釋: {target_adv_def})"}
                            st.rerun()
