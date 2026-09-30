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

# 🎨 簡約排版與自動適應亮/暗色主題優化
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

@st.cache_resource(show_spinner=False)
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

@st.cache_resource(show_spinner=False)
def get_active_worksheet(_client, sheet_url, sheet_name):
    try:
        spreadsheet = _client.open_by_url(sheet_url)
    except Exception as ex:
        raise RuntimeError(f"無法開啟 Google 試算表網址，請檢查 secrets 中的 sheet_url 是否正確。錯誤：{ex}")
    
    try:
        return spreadsheet.worksheet(sheet_name)
    except Exception:
        try:
            return spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols="10")
        except Exception as ex:
            raise RuntimeError(f"無法讀取或建立分頁「{sheet_name}」，請確認試算表內是否有此分頁。錯誤：{ex}")

try:
    active_worksheet = get_active_worksheet(gs_client, SHEET_URL, current_sheet_name)
except Exception as e:
    st.error(f"⚠️ {e}")
    st.stop()

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
                
    return df_temp

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
                "definition": cleaned_def,
                "advanced_sentence": pasted_eng_def or f"An English term meaning {cleaned_def}.",
                "basic_sentence": pasted_sent or f"Example sentence for {w_clean}.",
                "collocations": pasted_colloc or f"{w_clean} collocation"
            })
        return records

    matches = re.findall(r'(v\.|n\.|adj\.|adv\.|prep\.|conj\.|pron\.|phr\.|aux\.)', cleaned_def, flags=re.IGNORECASE)
    if matches and len(matches) > 0:
        pure_def = cleaned_def
        for m in matches:
            pure_def = pure_def.replace(m, "")
        pure_def = pure_def.strip().strip(';').strip(',').strip('；').strip()
        
        for idx, m in enumerate(matches):
            p_formatted = m.lower()
            if not p_formatted.endswith('.'): p_formatted += '.'
            
            records.append({
                "word": w_clean,
                "phonetic": f"/{w_lower}/",
                "part_of_speech": simple_s2t_convert(p_formatted),
                "definition": simple_s2t_convert(pure_def),
                "advanced_sentence": pasted_eng_def or f"An English term referring to {w_clean}.",
                "basic_sentence": pasted_sent or f"Example sentence for {w_clean}.",
                "collocations": pasted_colloc or f"{w_clean} related expression"
            })
        if records:
            return records

    fallback_pos = "phr." if " " in w_clean else "n."
    records.append({
        "word": w_clean,
        "phonetic": f"/{w_lower}/",
        "part_of_speech": fallback_pos,
        "definition": cleaned_def,
        "advanced_sentence": pasted_eng_def or f"A standard English expression referring to {w_clean}.",
        "basic_sentence": pasted_sent or f"Example sentence for {w_clean}.",
        "collocations": pasted_colloc or f"Common collocation with {w_clean}"
    })
    
    return records

def parse_raw_vocab_line_advanced(line):
    line_clean = re.sub(r'^\d+[\.\s]*', '', line).strip()
    if not line_clean:
        return []

    if '|' in line_clean:
        parts = [p.strip() for p in line_clean.split('|')]
        w = parts[0].strip()
        d = parts[1].strip() if len(parts) > 1 else ""
        pasted_p = parts[2].strip() if len(parts) > 2 else ""
        pasted_eng = parts[3].strip() if len(parts) > 3 else ""
        pasted_s = parts[4].strip() if len(parts) > 4 else ""
        pasted_c = parts[5].strip() if len(parts) > 5 else ""
        return parse_mixed_vocab_input(w, raw_def=d, pasted_pos=pasted_p, pasted_eng_def=pasted_eng, pasted_sent=pasted_s, pasted_colloc=pasted_c)

    match_split = re.search(r'([\u4e00-\u9fa5]|v\.|n\.|adj\.|adv\.|prep\.|conj\.|pron\.|phr\.)', line_clean, re.IGNORECASE)
    if not match_split:
        return [{
            "word": line_clean,
            "phonetic": f"/{line_clean.lower()}/",
            "part_of_speech": "n.",
            "definition": "",
            "advanced_sentence": f"An English term referring to {line_clean}.",
            "basic_sentence": f"Example for {line_clean}.",
            "collocations": f"Collocation for {line_clean}"
        }]
    
    word_end_idx = match_split.start()
    word = line_clean[:word_end_idx].strip()
    rest = line_clean[word_end_idx:].strip()
    
    if not word:
        parts = line_clean.split(maxsplit=1)
        word = parts[0] if len(parts) > 0 else line_clean
        rest = parts[1] if len(parts) > 1 else ""

    return parse_mixed_vocab_input(word, raw_def=rest)

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
        st.cache_data.clear()
        return True, "成功"
    except Exception as e:
        return False, str(e)

@st.cache_data(show_spinner=False)
def generate_audio_bytes(text, tld='com'):
    try:
        tts = gTTS(text=text, lang='en', tld=tld)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        return fp.getvalue()
    except Exception:
        return b""

def parse_lesson_number(unit_str):
    match = re.search(r'第([一二三四五六七八九十百0-9]+)課', unit_str)
    if match:
        num_str = match.group(1)
        try:
            return int(num_str)
        except ValueError:
            cn_map = {'一':1, '二':2, '三':3, '四':4, '五':5, '六':6, '七':7, '八':8, '九':9, '十':10,
                      '十一':11, '十二':12, '十三':13, '十四':14, '十五':15, '十六':16, '十七':17, '十八':18, '十九':19, '二十':20}
            if num_str in cn_map:
                return cn_map[num_str]
    return 999

def get_hierarchical_units(df):
    semesters = []
    semester_to_units = {}
    if 'unit_tag' in df.columns:
        for ut in df['unit_tag'].dropna().unique():
            ut_str = str(ut).strip()
            if not ut_str:
                continue
            if ' > ' in ut_str:
                sem, un = ut_str.split(' > ', 1)
                sem = sem.strip()
                un = un.strip()
                if sem not in semesters:
                    semesters.append(sem)
                if sem not in semester_to_units:
                    semester_to_units[sem] = []
                if un not in semester_to_units[sem]:
                    semester_to_units[sem].append(un)
                    
    for sem in semester_to_units:
        semester_to_units[sem].sort(key=parse_lesson_number)
        
    return sorted(semesters), semester_to_units

def create_multi_audio_buttons(b64_us, b64_uk, b64_au, justify="flex-start"):
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                margin: 0; padding: 0; background-color: transparent;
                display: flex; align-items: center; justify-content: {justify}; gap: 10px;
                overflow: hidden; height: 100vh;
            }}
            button {{
                background-color: rgba(255, 255, 255, 0.2) !important; 
                border: 1px solid rgba(255, 255, 255, 0.5) !important; 
                border-radius: 6px;
                cursor: pointer; 
                font-size: 15px; 
                padding: 8px 16px;
                outline: none; 
                transition: all 0.2s ease-in-out;
                color: #ffffff !important; 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                font-weight: 600;
            }}
            button:hover {{
                border-color: #ff4b4b; 
                color: #ff4b4b;
                background-color: rgba(255, 255, 255, 0.3) !important;
            }}
            button:active {{
                transform: scale(0.95);
            }}
            @media (prefers-color-scheme: light) {{
                button {{ color: #333333 !important; border-color: rgba(0, 0, 0, 0.2) !important; }}
                button:hover {{ color: #ff4b4b !important; border-color: #ff4b4b !important; }}
            }}
        </style>
    </head>
    <body>
        <audio id="snd_us" src="data:audio/mp3;base64,{b64_us}"></audio>
        <audio id="snd_uk" src="data:audio/mp3;base64,{b64_uk}"></audio>
        <audio id="snd_au" src="data:audio/mp3;base64,{b64_au}"></audio>
        
        <button onclick="document.getElementById('snd_us').play()" title="點擊播放美式發音">US 美式</button>
        <button onclick="document.getElementById('snd_uk').play()" title="點擊播放英式發音">GB 英式</button>
        <button onclick="document.getElementById('snd_au').play()" title="點擊播放澳洲腔">AU 澳洲</button>
    </body>
    </html>
    """

st.title("📚 我愛背單字")

with st.spinner("⏳ 正在從雲端載入單字資料庫..."):
    try:
        df_vocab = load_vocab_dataframe(active_worksheet, current_sheet_name)
    except Exception as e:
        st.error(f"⚠️ 載入資料失敗：{e}")
        st.stop()

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
        single_def = st.text_input("中文釋義（選填）：", placeholder="例如：v.張貼；n.職位")
        single_sent = st.text_input("真實例句（選填）：", placeholder="例如：Sentence here")
        single_colloc = st.text_input("搭配詞（選填）：", placeholder="例如：Collocation here")
        if st.button("🚀 瞬間寫入雲端", type="primary", use_container_width=True):
            if single_word:
                records = parse_mixed_vocab_input(single_word, raw_def=single_def, pasted_sent=single_sent, pasted_colloc=single_colloc)
                df_current = load_vocab_dataframe(active_worksheet, current_sheet_name).copy()
                
                for data in records:
                    word = data.get('word')
                    pos = data.get('part_of_speech', '')
                    match_mask = (df_current['word'].astype(str).str.strip().str.lower() == word.lower()) & (df_current['part_of_speech'].astype(str).str.strip().str.lower() == pos.lower())
                    if not df_current.empty and match_mask.any():
                        idx = df_current.index[match_mask].tolist()[0]
                        df_current.at[idx, 'phonetic'] = data.get('phonetic', '')
                        if data.get('definition'): df_current.at[idx, 'definition'] = data.get('definition')
                        df_current.at[idx, 'advanced_sentence'] = data.get('advanced_sentence', '')
                        if single_sent: df_current.at[idx, 'basic_sentence'] = single_sent
                        if single_colloc: df_current.at[idx, 'collocations'] = single_colloc
                        df_current.at[idx, 'unit_tag'] = current_unit_tag
                    else:
                        next_id = len(df_current) + 1
                        new_row = pd.DataFrame([{
                            'id': next_id,
                            'word': word,
                            'phonetic': data.get('phonetic', ''),
                            'part_of_speech': pos,
                            'definition': data.get('definition', ''),
                            'advanced_sentence': data.get('advanced_sentence', ''),
                            'basic_sentence': single_sent,
                            'collocations': single_colloc,
                            'unit_tag': current_unit_tag,
                            'srs_stage': 0
                        }])
                        df_current = pd.concat([df_current, new_row], ignore_index=True)
                    
                save_all_vocab_to_sheet(active_worksheet, df_current)
                st.success(f"🎉 成功新增：{single_word}")
                st.rerun()

    with col_input2:
        st.subheader("📋 智慧多格式快速貼上匯入")
        st.markdown(f"📍 **[狀態欄] 目前目標分類：** `{selected_level} ({current_unit_tag})`")
        
        pasted_text = st.text_area("貼上完整單字清單", placeholder="source | 來源 | n. | A place... | Sentence | Collocation", height=140, label_visibility="collapsed")
        
        valid_lines = [l for l in pasted_text.strip().split('\n') if l.strip()] if pasted_text else []
        total_preview_count = len(valid_lines)
        if total_preview_count > 0:
            st.info(f"📊 **狀態預覽：** 偵測到 **{total_preview_count}** 個項目準備匯入至「{current_unit_tag}」")
        else:
            st.caption(f"📊 **狀態預覽：** 尚未貼上資料（目標：{current_unit_tag}）")

        status_box = st.empty()

        if st.button("📥 批次秒速匯入", use_container_width=True):
            if pasted_text:
                lines = [l for l in pasted_text.strip().split('\n') if l.strip()]
                df_current = load_vocab_dataframe(active_worksheet, current_sheet_name).copy()
                count = 0
                
                for line in lines:
                    records = parse_raw_vocab_line_advanced(line)
                    if records:
                        for data in records:
                            target_pos = data.get('part_of_speech', '')
                            match_mask = (df_current['word'].astype(str).str.strip().str.lower() == data.get('word','').lower()) & (df_current['part_of_speech'].astype(str).str.strip().str.lower() == target_pos.lower())
                            
                            if not df_current.empty and match_mask.any():
                                idx = df_current.index[match_mask].tolist()[0]
                                df_current.at[idx, 'phonetic'] = data.get('phonetic', '')
                                if data.get('definition'): df_current.at[idx, 'definition'] = simple_s2t_convert(data.get('definition'))
                                df_current.at[idx, 'advanced_sentence'] = data.get('advanced_sentence', '')
                                if data.get('basic_sentence'): df_current.at[idx, 'basic_sentence'] = data.get('basic_sentence')
                                if data.get('collocations'): df_current.at[idx, 'collocations'] = data.get('collocations')
                                df_current.at[idx, 'unit_tag'] = current_unit_tag
                            else:
                                next_id = len(df_current) + 1
                                new_row = pd.DataFrame([{
                                    'id': next_id,
                                    'word': data.get('word', ''),
                                    'phonetic': data.get('phonetic', ''),
                                    'part_of_speech': target_pos,
                                    'definition': simple_s2t_convert(data.get('definition', '')),
                                    'advanced_sentence': data.get('advanced_sentence', ''),
                                    'basic_sentence': data.get('basic_sentence', ''),
                                    'collocations': data.get('collocations', ''),
                                    'unit_tag': current_unit_tag,
                                    'srs_stage': 0
                                }])
                                df_current = pd.concat([df_current, new_row], ignore_index=True)
                        count += 1
                save_all_vocab_to_sheet(active_worksheet, df_current)
                status_box.success(f"🎊 成功秒速匯入 {count} 個項目！")
                st.rerun()

elif main_menu == "📖 字彙管理":
    if df_vocab.empty:
        st.info("📭 目前雲端尚無單字，請至側邊欄新增！")
    else:
        semesters, sem_to_units = get_hierarchical_units(df_vocab)
        
        col_sel1, col_sel2 = st.columns(2, gap="medium")
        with col_sel1:
            sem_options = ["全部單字"] + semesters
            selected_sem = st.selectbox("1️⃣ 選擇學期/階段：", sem_options)
        with col_sel2:
            if selected_sem == "全部單字":
                selected_unit_filter = "全部單字"
                st.selectbox("2️⃣ 選擇課次單元：", ["全部課次"], disabled=True)
            else:
                unit_options = ["全部課次"] + sem_to_units.get(selected_sem, [])
                selected_unit = st.selectbox("2️⃣ 選擇課次單元：", unit_options)
                if selected_unit == "全部課次":
                    selected_unit_filter = selected_sem
                else:
                    selected_unit_filter = f"{selected_sem} > {selected_unit}"

        if selected_unit_filter == "全部單字":
            filtered_df = df_vocab
        elif " > " not in selected_unit_filter:
            filtered_df = df_vocab[df_vocab['unit_tag'].astype(str).str.startswith(selected_unit_filter)]
        else:
            filtered_df = df_vocab[df_vocab['unit_tag'] == selected_unit_filter]

        col_f1, col_f2 = st.columns(2, gap="medium")
        with col_f1:
            search_query = st.text_input("🔍 搜尋單字或釋義：")
            if search_query:
                filtered_df = filtered_df[filtered_df['word'].str.contains(search_query, case=False, na=False) | filtered_df['definition'].str.contains(search_query, case=False, na=False)]
        with col_f2:
            sub_col1, sub_col2 = st.columns([3, 1], gap="small")
            with sub_col1:
                word_to_delete = st.selectbox("🗑️ 快速刪除單字：", ["--請選擇要刪除的單字--"] + filtered_df['word'].tolist() if not filtered_df.empty else ["--請選擇要刪除的單字--"])
                if word_to_delete != "--請選擇要刪除的單字--":
                    if st.button(f"確認刪除：{word_to_delete}", type="primary", use_container_width=True):
                        df_current = load_vocab_dataframe(active_worksheet, current_sheet_name).copy()
                        df_current = df_current[df_current['word'].astype(str).str.strip().str.lower() != word_to_delete.strip().lower()]
                        if not df_current.empty:
                            df_current['id'] = range(1, len(df_current) + 1)
                        save_all_vocab_to_sheet(active_worksheet, df_current)
                        st.success(f"已刪除：{word_to_delete}")
                        st.rerun()
            with sub_col2:
                st.write("") 
                st.write("")
                if st.button("🗑️ 刪除該課", type="secondary", use_container_width=True):
                    if selected_unit_filter == "全部單字" or " > " not in selected_unit_filter:
                        st.warning("⚠️ 請先在上方選單選擇到具體某一課，才能執行刪除該課！")
                    else:
                        df_current = load_vocab_dataframe(active_worksheet, current_sheet_name).copy()
                        df_current = df_current[df_current['unit_tag'] != selected_unit_filter]
                        if not df_current.empty:
                            df_current['id'] = range(1, len(df_current) + 1)
                        save_all_vocab_to_sheet(active_worksheet, df_current)
                        st.success(f"🗑️ 已成功刪除「{selected_unit_filter}」整課單字！")
                        st.rerun()

        st.markdown("---")

        with st.expander("📋 單字總表", expanded=True):
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

elif main_menu == "🎯 背誦單字":
    if df_vocab.empty:
        st.warning(f"📭 目前雲端沒有單字！")
    else:
        semesters, sem_to_units = get_hierarchical_units(df_vocab)
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            sel_sem_flash = st.selectbox("🎯 選擇學期/階段：", ["全部單字"] + semesters, key="flash_sem_select")
        with col_f2:
            if sel_sem_flash == "全部單字":
                sel_unit_flash = "全部單字"
                st.selectbox("🎯 選擇課次單元：", ["全部課次"], disabled=True, key="flash_unit_disabled")
            else:
                sel_unit_flash = st.selectbox("🎯 選擇課次單元：", ["全部課次"] + sem_to_units.get(sel_sem_flash, []), key="flash_unit_select")

        if sel_sem_flash == "全部單字":
            df_filtered_flash = df_vocab
        elif sel_unit_flash == "全部課次":
            df_filtered_flash = df_vocab[df_vocab['unit_tag'].astype(str).str.startswith(sel_sem_flash)]
        else:
            df_filtered_flash = df_vocab[df_vocab['unit_tag'] == f"{sel_sem_flash} > {sel_unit_flash}"]
        
        if not df_filtered_flash.empty:
            if "flashcard_index" not in st.session_state: st.session_state.flashcard_index = 0
            total_count = len(df_filtered_flash)
            st.session_state.flashcard_index = st.session_state.flashcard_index % total_count
            row = df_filtered_flash.iloc[st.session_state.flashcard_index]
            
            with st.container(border=True):
                audio_us = generate_audio_bytes(row['word'], 'com')
                audio_uk = generate_audio_bytes(row['word'], 'co.uk')
                audio_au = generate_audio_bytes(row['word'], 'com.au')
                b64_us = base64.b64encode(audio_us).decode() if audio_us else ""
                b64_uk = base64.b64encode(audio_uk).decode() if audio_uk else ""
                b64_au = base64.b64encode(audio_au).decode() if audio_au else ""
                
                st.markdown(f"<h1 style='text-align: center; font-size: 54px; margin-bottom: 5px;'>{row['word']}</h1>", unsafe_allow_html=True)
                
                if b64_us and b64_uk and b64_au:
                    components.html(create_multi_audio_buttons(b64_us, b64_uk, b64_au, justify="center"), height=50)
                
                st.markdown(f"<p style='text-align: center; color: gray; margin-top: 5px;'>{row.get('phonetic','')} | {row.get('part_of_speech','')}</p>", unsafe_allow_html=True)
                
                st.markdown("---")
                st.markdown(f"<h4>中文釋義：{row['definition']}</h4>", unsafe_allow_html=True)
                if row.get('advanced_sentence'):
                    st.markdown(f"<p style='font-size: 19px;'>📖 英文釋義：{row.get('advanced_sentence')}</p>", unsafe_allow_html=True)
                if row.get('basic_sentence'):
                    st.markdown(f"<p style='font-style: italic; font-size: 19px;'>💬 例句：{row.get('basic_sentence')}</p>", unsafe_allow_html=True)
                if row.get('collocations'):
                    st.markdown(f"<p style='font-size: 17px;'>🔗 搭配詞：{row.get('collocations')}</p>", unsafe_allow_html=True)
            
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
        semesters, sem_to_units = get_hierarchical_units(df_vocab)
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            sel_sem_game = st.selectbox("選擇學期/階段範圍：", ["全部單字"] + semesters, key="game_sem_select")
        with col_g2:
            if sel_sem_game == "全部單字":
                sel_unit_game = "全部單字"
                st.selectbox("選擇課次單元範圍：", ["全部課次"], disabled=True, key="game_unit_disabled")
            else:
                sel_unit_game = st.selectbox("選擇課次單元範圍：", ["全部課次"] + sem_to_units.get(sel_sem_game, []), key="game_unit_select")

        if sel_sem_game == "全部單字":
            df_filtered_game = df_vocab
        elif sel_unit_game == "全部課次":
            df_filtered_game = df_vocab[df_vocab['unit_tag'].astype(str).str.startswith(sel_sem_game)]
        else:
            df_filtered_game = df_vocab[df_vocab['unit_tag'] == f"{sel_sem_game} > {sel_unit_game}"]
        
        df_game_queue_source = df_filtered_game.drop_duplicates(subset=['word'])

        if not df_filtered_game.empty:
            state_key = f"game_started_{game_mode}"
            if state_key not in st.session_state or st.session_state.get("current_game_unit") != f"{sel_sem_game}_{sel_unit_game}":
                st.session_state[state_key] = True
                st.session_state.current_game_unit = f"{sel_sem_game}_{sel_unit_game}"
                st.session_state.game_queue = df_game_queue_source.sample(frac=1).to_dict('records')
                st.session_state.game_index = 0
                st.session_state.wrong_answers = []
                st.session_state.is_finished = False
                st.session_state.last_feedback = None

            if st.session_state.game_index >= len(st.session_state.game_queue):
                st.session_state.is_finished = True

            if st.session_state.get("is_finished", False):
                st.balloons()
                st.markdown("## 🎉 測驗圓滿結束！")
                if st.button("🔄 重新挑戰本範圍", type="primary", use_container_width=True):
                    del st.session_state[state_key]
                    st.rerun()
            else:
                current_item = st.session_state.game_queue[st.session_state.game_index]
                target_word = str(current_item['word']).strip()
                target_def = str(current_item['definition']).strip() if str(current_item['definition']).strip() else "(尚無中文釋義)"
                target_adv_def = str(current_item.get('advanced_sentence', '')).strip() or f"An English term referring to {target_word}."
                hint_masked = "".join([" _ " if c.isalpha() else "    " for c in target_word])
                
                total_q_count = len(st.session_state.game_queue)
                current_q_num = st.session_state.game_index + 1
                remaining_count = total_q_count - current_q_num + 1

                with st.container(border=True):
                    q_col1, q_col2 = st.columns([5, 1])
                    with q_col2:
                        st.markdown(f"<div style='text-align: right; color: gray; font-size: 15px; font-weight: bold;'>剩餘題數：{remaining_count}</div>", unsafe_allow_html=True)

                    if "標準模式" in game_mode:
                        audio_us = generate_audio_bytes(target_word, 'com')
                        audio_uk = generate_audio_bytes(target_word, 'co.uk')
                        audio_au = generate_audio_bytes(target_word, 'com.au')
                        b64_us = base64.b64encode(audio_us).decode() if audio_us else ""
                        b64_uk = base64.b64encode(audio_uk).decode() if audio_uk else ""
                        b64_au = base64.b64encode(audio_au).decode() if audio_au else ""
                        
                        r_col1, r_col2 = st.columns([2, 3])
                        with r_col1:
                            st.markdown(f"<h3 style='margin: 0; padding-top: 5px;'>中文：{target_def}</h3>", unsafe_allow_html=True)
                        with r_col2:
                            if b64_us:
                                components.html(create_multi_audio_buttons(b64_us, b64_uk, b64_au, justify="flex-start"), height=45)
                                
                        st.markdown(f"<div style='margin-top: 15px; margin-bottom: 15px;'><b>單字提示：</b> `{hint_masked}`</div>", unsafe_allow_html=True)
                    else:
                        audio_us = generate_audio_bytes(target_adv_def, 'com')
                        audio_uk = generate_audio_bytes(target_adv_def, 'co.uk')
                        audio_au = generate_audio_bytes(target_adv_def, 'co.uk')
                        b64_us = base64.b64encode(audio_us).decode() if audio_us else ""
                        b64_uk = base64.b64encode(audio_uk).decode() if audio_uk else ""
                        b64_au = base64.b64encode(audio_au).decode() if audio_au else ""
                        
                        st.markdown(f"<h3 style='margin-bottom: 5px;'>🔊 英文解釋聽力提示：</h3>", unsafe_allow_html=True)
                        st.markdown(f"<p style='font-size: 17px; font-weight: 500; margin-bottom: 10px;'>{target_adv_def}</p>", unsafe_allow_html=True)
                        if b64_us:
                            components.html(create_multi_audio_buttons(b64_us, b64_uk, b64_au, justify="flex-start"), height=45)
                        st.markdown(f"<div style='margin-top: 15px; margin-bottom: 15px;'><b>單字提示：</b> `{hint_masked}`</div>", unsafe_allow_html=True)

                    if st.session_state.get("last_feedback"):
                        fb = st.session_state.last_feedback
                        if fb["type"] == "success": st.success(fb["msg"])
                        else: st.error(fb["msg"])
                        if st.button("➡️ 點擊進入下一題", type="primary", use_container_width=True):
                            st.session_state.last_feedback = None
                            st.session_state.game_index += 1
                            st.rerun()
                    else:
                        with st.form(key=f"quiz_form_{st.session_state.game_index}"):
                            f_col1, f_col2 = st.columns([4, 1], gap="small")
                            with f_col1:
                                user_ans = st.text_input("輸入答案", placeholder="在此輸入拼寫答案...", key=f"ans_input_{st.session_state.game_index}", label_visibility="collapsed").strip().lower()
                            with f_col2:
                                submitted = st.form_submit_button("🚀 送出", type="primary", use_container_width=True)
                                
                            if submitted:
                                if user_ans == target_word.lower():
                                    st.session_state.last_feedback = {"type": "success", "msg": f"🎉 答對了！就是 `{target_word}`"}
                                else:
                                    st.session_state.wrong_answers.append(current_item)
                                    st.session_state.last_feedback = {"type": "error", "msg": f"❌ 答錯囉！正確答案是：`{target_word}`"}
                                st.rerun()
