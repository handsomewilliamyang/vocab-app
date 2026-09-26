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
    st.error(f"⚠️ Google Sheets 連線設定錯誤：{e}")
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
        st.sidebar.warning(f"⚠️ 找不到分頁，已自動切換至：{active_worksheet.title}")
except Exception as e:
    st.error(f"⚠️ Google Sheets 連線失敗：{e}")
    st.stop()

st.sidebar.markdown("---")
st.sidebar.info(f"💡 雲端同步中：已連線至工作表【{active_worksheet.title}】")

@st.cache_data(ttl=300, show_spinner=False)
def get_vocab_from_sheets(_worksheet):
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

    return df_temp

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
    
    if HAS_GEMINI and st.session_state.get("gemini_api_key"):
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = (
                f"你是一個專業的英語字典。請針對英文單字「{w_clean}」（適用級別：{level}），"
                "提供以下 JSON 格式的解析，不要包含其他贅字：\n"
                "{\n"
                '    "phonetic": "/音標/",\n'
                '    "part_of_speech": "詞性 (例如 n., v., adj.)",\n'
                '    "definition": "精準的繁體中文解釋與翻譯",\n'
                '    "sentence": "一句道地的英文例句"\n'
                "}"
            )
            response = model.generate_content(prompt)
            clean_text = response.text.replace("```json", "").replace("
