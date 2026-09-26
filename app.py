import pandas as pd
import streamlit as st
import json
import re
import random
import os
import time
from PIL import Image
import docx
import urllib.request
import urllib.parse
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
    client = gspread.authorize(creds)
    return client

try:
    gs_client = init_gsheets_client()
    SHEET_URL = st.secrets["sheet_url"]
except Exception as e:
    st.error("⚠️ Google Sheets 連線設定錯誤：" + str(e))
    st.stop()

st.sidebar.markdown("<h2 style='font-size: 24px;'>⚙️ 系統導覽與設定</h2>", unsafe_allow_html=True)
st.sidebar.markdown("---")
main_menu = st.sidebar.radio(
    "選擇主要功能：",
    ["✨ 智慧單字新增", "📖 字庫管理與搜尋", "🎯 沉浸式閃卡複習", "🎮 拼字王挑戰遊戲"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")
user_api_key = st.sidebar.text_input("輸入 Gemini API Key (必填以啟用 AI 字典)", type="password", value=st.secrets.get("gemini_api_key", ""))
if user_api_key:
    st.session_state.gemini_api_key = user_api_key
    if HAS_GEMINI:
        genai.configure(api_key=user_api_key)
    st.sidebar.success("✅ AI 字典引擎已啟用")
else:
    st.session_state.gemini_api_key = ""
    st.sidebar.warning("⚠️ 請務必輸入 API Key 才能自動查字典")

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
        st.sidebar.warning("⚠️ 找不到分頁，已自動切換至：" + active_worksheet.title)
except Exception as e:
    st.error("⚠️ Google Sheets 連線失敗：" + str(e))
    st.stop()

st.sidebar.markdown("---")
st.sidebar.info("💡 雲端同步中：已連線至工作表【" + active_worksheet.title + "】")

def load_vocab_dataframe(_worksheet, force_reload=False):
    cache_key = "vocab_df_" + _worksheet.title
    if force_reload or cache_key not in st.session_state:
        try:
            records = _worksheet.get_all_records()
        except Exception:
            records = []
            
        if not records:
            all_values = _worksheet.get_all_values()
            if len(all_values) > 1:
                headers = [str(h).strip().lower() for h in all_values[0]]
                data_rows = all_values[1:]
                df_temp = pd.DataFrame(data_rows, columns=headers[:len(all_values[0])])
            else:
                df_temp = pd.DataFrame(columns=['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'basic_sentence', 'advanced_sentence', 'collocations', 'unit_tag', 'srs_stage'])
        else:
            df_temp = pd.DataFrame(records)
            
        df_temp.columns = [str(c).strip().lower() for c in df_temp.columns]
        required_cols = ['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'basic_sentence', 'advanced_sentence', 'collocations', 'unit_tag', 'srs_stage']
        for idx, col in enumerate(required_cols):
            if col not in df_temp.columns:
                if idx < len(df_temp.columns):
                    df_temp = df_temp.rename(columns={df_temp.columns[idx]: col})
                else:
                    df_temp[col] = ""
                    
        df_temp = df_temp[df_temp['word'].astype(str).str.strip() != '']
        df_temp = df_temp[df_temp['word'].notna()]
        
        for idx, row in df_temp.iterrows():
            for col in df_temp.columns:
                val = str(df_temp.at[idx, col])
                if val == "nan" or val.lower() == "none":
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

def get_word_record_data_via_ai(word, level="國中部"):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    
    default_result = {
        "word": w_clean,
        "phonetic": "/" + w_lower + "/",
        "part_of_speech": "n.",
        "definition": f"{w_clean} (請補充中文釋義)",
        "basic_sentence": f"This is an example sentence for {w_clean}."
    }

    if HAS_GEMINI and st.session_state.get("gemini_api_key"):
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = (
                f"你是一個專業的英語字典與教師。請針對英文單字或片語「{w_clean}」（適用級別：{level}），"
                "嚴格回傳以下純 JSON 格式（不要包含任何 markdown 程式碼標記如 ```json）：\n"
                "{\n"
                '    "phonetic": "/音標/",\n'
                '    "part_of_speech": "詞性 (例如 n., v., adj.,phr.)",\n'
                '    "definition": "精準流暢的繁體中文含義",\n'
                '    "sentence": "實用且道地的英文例句"\n'
                "}"
            )
            response = model.generate_content(prompt)
            raw_text = response.text.strip()
            
            raw_text = re.sub(r"^```(json)?", "", raw_text, flags=re.IGNORECASE).strip()
            raw_text = re.sub(r"```$", "", raw_text).strip()
            
            data = json.loads(raw_text)
            
            phonetic = data.get("phonetic", "/" + w_lower + "/")
            pos = data.get("part_of_speech", "n.")
            definition = data.get("definition", w_clean)
            sentence = data.get("sentence", f"This is an example sentence for {w_clean}.")
            
            return {
                "word": w_clean,
                "phonetic": phonetic if phonetic else "/" + w_lower + "/",
                "part_of_speech": simple_s2t_convert(pos),
                "definition": simple_s2t_convert(definition),
                "basic_sentence": sentence
            }
        except Exception:
            pass
            
    return default_result

def update_single_word_in_sheet(_worksheet, target_word, new_word, new_phonetic, new_pos, new_def, new_basic, new_adv, new_coll):
    try:
        df = load_vocab_dataframe(_worksheet)
        row_idx = df.index[df['word'] == target_word].tolist()[0] + 2
        
        row_values = _worksheet.row_values(row_idx)
        row_id = row_values[0] if len(row_values) > 0 else 1
        unit_tag = row_values[8] if len(row_values) > 8 else "未分類"
        srs = row_values[9] if len(row_values) > 9 else 0
        
        new_row = [row_id, new_word, new_phonetic, new_pos, simple_s2t_convert(new_def), new_basic, new_adv, new_coll, unit_tag, srs]
        _worksheet.update('A' + str(row_idx) + ':J' + str(row_idx), [new_row])
        time.sleep(0.5)
        load_vocab_dataframe(_worksheet, force_reload=True)
        return True, "成功"
    except Exception as e:
        return False, str(e)

def delete_words_from_sheet(_worksheet, word_list):
    if not word_list: return
    df = load_vocab_dataframe(_worksheet)
    rows_to_delete = sorted([df.index[df['word'] == w].tolist()[0] + 2 for w in word_list if w in df['word'].values], reverse=True)
    for r in rows_to_delete:
        _worksheet.delete_rows(r)
        time.sleep(0.3)
    load_vocab_dataframe(_worksheet, force_reload=True)

@st.cache_data(show_spinner=False)
def generate_audio_bytes(text, lang='en'):
    tts = gTTS(text=text, lang=lang)
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
with col_m1:
    st.metric(label="雲端總單字數", value=str(total_words) + " 個")
with col_m2:
    st.metric(label="目前模式", value=main_menu + " (" + selected_level + ")")

st.markdown("<br>", unsafe_allow_html=True)

if main_menu == "✨ 智慧單字新增":
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        if selected_level == "國中部":
            semester = st.selectbox("選擇年級學期：", ["國一上", "國一下", "國二上", "國二下", "國三上", "國三下"])
        elif selected_level == "高中部":
            semester = st.selectbox("選擇年級學期：", ["高一上", "高一下", "高二上", "高二下", "高三上", "高三下"])
        else:
            semester = st.selectbox("選擇階段：", ["多益核心", "多益進階", "商用英文"])
            
    with col_u2:
        unit = st.selectbox("選擇課次單元：", ["第一課", "第二課", "第三課", "第四課", "第五課", "第六課"])
        
    current_unit_tag = semester + " > " + unit
    st.info("📌 即時同步至 Google Sheets 【" + active_worksheet.title + "】分頁：**" + current_unit_tag + "**")
    st.markdown("---")

    col_input1, col_input2 = st.columns(2, gap="large")
    with col_input1:
        st.subheader("📝 單筆快速建檔 (AI 字典)")
        single_word = st.text_input("輸入想要學習的英文單字：", placeholder="例如：resilient")
        if st.button("🚀 AI 查字典並寫入雲端", type="primary", use_container_width=True):
            if single_word:
                with st.spinner("🤖 AI 正在查閱字典並生成中文與例句中..."):
                    data = get_word_record_data_via_ai(single_word, level=selected_level)
                    df_check = load_vocab_dataframe(active_worksheet)
                    word = data.get('word')
                    if not df_check.empty and word in df_check['word'].values:
                        r_idx = df_check.index[df_check['word'] == word].tolist()[0] + 2
                        r_vals = active_worksheet.row_values(r_idx)
                        r_id = r_vals[0] if len(r_vals) > 0 else 1
                        srs_val = r_vals[9] if len(r_vals) > 9 else
