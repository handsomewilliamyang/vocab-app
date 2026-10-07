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
    }
    .stDataFrame td { white-space: normal !important; }
    [data-testid="stSidebar"] .stRadio label p { font-size: 18px !important; font-weight: 500 !important; }
    </style>
""", unsafe_allow_html=True)

main_menu = st.sidebar.radio("選擇主要功能：", ["✨ 新增單字", "📖 字彙管理", "🎯 背誦單字", "🎮 我是拼字王"], label_visibility="collapsed")

st.sidebar.markdown("---")
st.sidebar.markdown("##### 📚 選擇級別")
selected_level = st.sidebar.radio("選擇級別：", ["國中部", "高中部", "TOEIC"], label_visibility="collapsed")

current_sheet_name = selected_level
st.title("📚 我愛背單字")

@st.cache_resource(show_spinner=False)
def init_gsheets_client():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    )
    return gspread.authorize(creds)

@st.cache_resource(show_spinner=False)
def get_active_worksheet(_client, sheet_url, sheet_name):
    spreadsheet = _client.open_by_url(sheet_url)
    try:
        return spreadsheet.worksheet(sheet_name)
    except Exception:
        return spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols="10")

@st.cache_data(ttl=300, show_spinner=False)
def load_vocab_dataframe(_worksheet, cache_key):
    try:
        all_values = _worksheet.get_all_values()
    except Exception:
        all_values = []
        
    if len(all_values) > 1:
        headers = [str(h).strip().lower() for h in all_values[0]]
        df_temp = pd.DataFrame(all_values[1:], columns=headers[:len(all_values[0])])
    else:
        df_temp = pd.DataFrame(columns=['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'advanced_sentence', 'basic_sentence', 'collocations', 'unit_tag', 'srs_stage'])
        
    required_cols = ['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'advanced_sentence', 'basic_sentence', 'collocations', 'unit_tag', 'srs_stage']
    for col in required_cols:
        if col not in df_temp.columns:
            df_temp[col] = ""
            
    return df_temp[df_temp['word'].astype(str).str.strip() != '']

try:
    gs_client = init_gsheets_client()
    active_worksheet = get_active_worksheet(gs_client, st.secrets["sheet_url"], current_sheet_name)
    df_vocab = load_vocab_dataframe(active_worksheet, current_sheet_name)
except Exception as e:
    st.error(f"⚠️ 連線錯誤：{e}")
    st.stop()

def parse_lesson_number(unit_str):
    order_map = {'第一課': 1, '第二課': 2, '第三課': 3, '第四課': 4, '第五課': 5, '第六課': 6, '第七課': 7, '第八課': 8, '第九課': 9, '第十課': 10}
    for k, v in order_map.items():
        if k in unit_str:
            return v
    return 99

def get_hierarchical_units(df):
    semesters = []
    semester_to_units = {}
    if 'unit_tag' in df.columns:
        for ut in df['unit_tag'].dropna().unique():
            ut_str = str(ut).strip()
            if '>' in ut_str:
                sem, un = ut_str.split('>', 1)
                sem, un = sem.strip(), un.strip()
                if sem not in semesters: semesters.append(sem)
                if sem not in semester_to_units: semester_to_units[sem] = []
                if un not in semester_to_units[sem]: semester_to_units[sem].append(un)
    for sem in semester_to_units:
        semester_to_units[sem].sort(key=parse_lesson_number)
    return sorted(semesters), semester_to_units

if main_menu == "✨ 新增單字":
    if selected_level in ["國中部", "高中部"]:
        semester = st.selectbox("選擇年級學期：", ["高一上", "高一下", "高二上", "高二下", "高三上", "高三下"])
        unit = st.selectbox("選擇課次單元：", ["第一課", "第二課", "第三課", "第四課", "第五課", "第六課", "第七課", "第八課", "第九課", "第十課"])
    else:
        semester = st.selectbox("選擇 TOEIC 主題篇章：", ["旅館篇", "旅遊篇", "交通篇", "公司篇", "醫療篇"])
        unit = st.selectbox("選擇課次：", ["第一課", "第二課", "第三課", "第四課"])
        
    current_unit_tag = f"{semester} > {unit}"
    st.markdown(f"📍 目前目標分類：`{selected_level} ({current_unit_tag})`")
    
    single_word = st.text_input("輸入單字：")
    single_def = st.text_input("中文釋義：")
    if st.button("🚀 寫入雲端", type="primary"):
        if single_word:
            new_row = pd.DataFrame([{
                'id': len(df_vocab) + 1, 'word': single_word, 'phonetic': f"/{single_word.lower()}/",
                'part_of_speech': 'n.', 'definition': single_def, 'advanced_sentence': '',
                'basic_sentence': '', 'collocations': '', 'unit_tag': current_unit_tag, 'srs_stage': 0
            }])
            updated_df = pd.concat([df_vocab, new_row], ignore_index=True)
            active_worksheet.clear()
            active_worksheet.update([updated_df.columns.tolist()] + updated_df.values.tolist())
            st.success(f"🎉 成功新增：{single_word}")
            st.rerun()

elif main_menu == "📖 字彙管理":
    st.subheader("📋 單字總表")
    if not df_vocab.empty:
        st.dataframe(df_vocab, use_container_width=True, hide_index=True)
    else:
        st.info("目前尚無單字資料。")

elif main_menu == "🎯 背誦單字":
    st.subheader("🎯 單字卡背誦")
    if not df_vocab.empty:
        row = df_vocab.iloc[0]
        st.markdown(f"<h1>{row['word']}</h1>", unsafe_allow_html=True)
        st.markdown(f"<h4>中文釋義：{row['definition']}</h4>", unsafe_allow_html=True)
    else:
        st.warning("目前沒有單字可供背誦。")

elif main_menu == "🎮 我是拼字王":
    st.subheader("🎮 拼字王挑戰")
    st.info("請先至「新增單字」建立題目，即可在此開始遊戲！")
