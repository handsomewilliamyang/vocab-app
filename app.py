import pandas as pd
import streamlit as st
import json
import os
import time
import random
import requests
import re  
import urllib.parse
from gtts import gTTS
import io
import base64
import streamlit.components.v1 as components

import gspread
from google.oauth2.service_account import Credentials

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
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 14px !important;
        border: 1px solid rgba(128, 128, 128, 0.2) !important;
        padding: 20px !important;
        background-color: rgba(128, 128, 128, 0.03) !important;
        animation: fadeIn 0.25s ease-in-out;
    }

    @keyframes fadeIn {
        from { opacity: 0.4; transform: translateY(4px); }
        to { opacity: 1; transform: translateY(0); }
    }

    div[data-testid="stForm"] [data-testid="stHorizontalBlock"] {
        align-items: flex-end !important;
    }

    .stDataFrame [data-testid="stTable"] td, .stDataFrame div[data-baseweb="table"] td, div[data-testid="stDataFrame"] div.dvn-scroller td {
        white-space: normal !important;
        word-wrap: break-word !important;
        height: auto !important;
        padding-top: 12px !important;
        padding-bottom: 12px !important;
        font-size: 15px !important;
    }

    [data-testid="stSidebar"] .stRadio label p {
        font-size: 18px !important;
        font-weight: 500 !important;
    }
    [data-testid="stSidebar"] h5 {
        font-size: 17px !important;
        font-weight: 600;
    }
    .stSelectbox label, .stTextInput label, .stTextArea label, .stRadio label {
        font-size: 16px !important;
        font-weight: 500 !important;
    }

    @media (max-width: 768px) {
        [data-testid="stSidebar"] .stRadio label p { font-size: 16px !important; }
        [data-testid="stSidebar"] h5 { font-size: 15px !important; }
    }
    </style>
""", unsafe_allow_html=True)

main_menu = st.sidebar.radio(
    "選擇主要功能：",
    ["✨ 新增單字", "📖 字彙管理", "🎯 背誦單字", "🎮 我是拼字王"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")
st.sidebar.markdown("##### 📚 選擇級別")

selected_level = st.sidebar.radio(
    "選擇級別：",
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

current_sheet_name = selected_level

st.title("📚 我愛背單字")

@st.cache_resource(show_spinner=False)
def init_gsheets_client():
    if "gcp_service_account" not in st.secrets or "sheet_url" not in st.secrets:
        raise RuntimeError("請在 Streamlit Secrets 中設定 gcp_service_account 與 sheet_url！")
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scopes
    )
    return gspread.authorize(creds)

@st.cache_resource(show_spinner=False)
def get_active_worksheet(_client, sheet_url, sheet_name):
    spreadsheet = _client.open_by_url(sheet_url)
    try:
        return spreadsheet.worksheet(sheet_name)
    except Exception:
        try:
            return spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols="10")
        except Exception as ex:
            raise RuntimeError(f"無法讀取或建立分頁「{sheet_name}」。錯誤：{ex}")

@st.cache_data(ttl=300, show_spinner=False)
def load_vocab_dataframe(_worksheet, cache_key):
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

    if 'unit_tag' in df_temp.columns:
        def normalize_tag(tag):
            t = str(tag).strip()
            if '>' in t:
                parts = t.split('>', 1)
                return f"{parts[0].strip()} > {parts[1].strip()}"
            return t
        df_temp['unit_tag'] = df_temp['unit_tag'].apply(normalize_tag)
                
    return df_temp

try:
    with st.spinner("⏳ 正在從雲端載入單字資料庫..."):
        gs_client = init_gsheets_client()
        SHEET_URL = st.secrets["sheet_url"]
        active_worksheet = get_active_worksheet(gs_client, SHEET_URL, current_sheet_name)
        df_vocab = load_vocab_dataframe(active_worksheet, current_sheet_name)
except Exception as e:
    st.error(f"⚠️ 連線或讀取 Google 試算表發生錯誤：{e}")
    st.stop()

total_words = len(df_vocab)
col_m1, col_m2 = st.columns(2)
col_m1.metric(label="雲端總單字數", value=f"{total_words} 個")

clean_mode_name = main_menu.replace("✨ ", "").replace("📖 ", "").replace("🎯 ", "").replace("🎮 ", "")
col_m2.metric(label="目前模式", value=f"{clean_mode_name}【{selected_level}】")

st.markdown("<br>", unsafe_allow_html=True)

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

def parse_mixed_vocab_input(word, raw_def="", pasted_pos="", pasted_eng_def="", pasted_sent="", pasted_colloc=""):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    cleaned_def = simple_s2t_convert(raw_def) if raw_def else ""
    records = []
    
    if pasted_pos:
        pos_list = [p.strip() for p in re.split(r'[,/]', pasted_pos) if p.strip()]
        for p in pos_list:
            records.append({
                "word": w_clean,
                "phonetic": f"/{w_lower}/",
                "part_of_speech": simple_s2t_convert(p),
