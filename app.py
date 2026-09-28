import pandas as pd
import streamlit as st
import json
import os
import time
import docx
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
    /* 放大側邊欄選項字體，提升操作體驗 */
    [data-testid="stSidebar"] .stRadio label p {
        font-size: 19px !important;
        font-weight: 500 !important;
    }
    [data-testid="stSidebar"] h5 {
        font-size: 18px !important;
    }
    /* 主畫面輸入框與下拉選單標題字體放大 */
    .stSelectbox label, .stTextInput label, .stTextArea label, .stRadio label {
        font-size: 17px !important;
        font-weight: 600 !important;
    }
    /* 針對手機與平板模式（螢幕寬度較小）進行響應式微調，避免過大跑版 */
    @media (max-width: 768px) {
        [data-testid="stSidebar"] .stRadio label p {
            font-size: 16px !important;
        }
        [data-testid="stSidebar"] h5 {
            font-size: 15px !important;
        }
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

def fetch_all_meanings_from_dictionary(word):
    w_clean = word.strip().lower()
    results = []
    phonetic = f"/{w_clean}/"
    try:
        encoded_word = urllib.parse.quote(w_clean)
        url_fd = f"https://api.dictionaryapi.dev/api/v2/entries/en/{encoded_word}"
        res_fd = requests.get(url_fd, timeout=3)
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
                    raw_pos = meaning.get('partOfSpeech', 'n.')
                    pos_map = {
                        'noun': 'n.', 'verb': 'v.', 'adjective': 'adj.', 
                        'adverb': 'adv.', 'pronoun': 'pron.', 'preposition': 'prep.', 
                        'conjunction': 'conj.', 'interjection': 'interj.', 'phr.': 'phr.'
                    }
                    pos = pos_map.get(raw_pos.lower(), raw_pos if raw_pos.endswith('.') else raw_pos + '.')
                    
                    def_text = ""
                    ex_text = ""
                    for def_obj in meaning.get('definitions', []):
                        if not def_text:
                            def_text = def_obj.get('definition', '')
                        if not ex_text and def_obj.get('example'):
                            ex_text = def_obj.get('example')
                        if def_text and ex_text:
                            break
                    
                    results.append({
                        'pos': pos,
                        'definition': def_text,
                        'example': ex_text,
                        'phonetic': phonetic
                    })
    except Exception:
        pass
    return results

def parse_mixed_vocab_input(word, raw_def="", pasted_pos="", pasted_eng_def="", pasted_sent="", pasted_colloc=""):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    cleaned_def = simple_s2t_convert(raw_def) if raw_def else ""
    
    records = []
    
    # 1. 若明確給定詞性（如透過管道符號）
    if pasted_pos:
        pos_list = [p.strip() for p in re.split(r'[,/]', pasted_pos) if p.strip()]
        for p in pos_list:
            records.append({
                "word": w_clean,
                "phonetic": f"/{w_lower}/",
                "part_of_speech": simple_s2t_convert(p),
                "definition": cleaned_def,
                "advanced_sentence": pasted_eng_def or f"An English term meaning {cleaned_def}.",
                "basic_sentence": pasted_sent,
                "collocations": pasted_colloc
            })
        return records

    pos_tokens = ['adj.', 'adv.', 'prep.', 'conj.', 'pron.', 'phr.', 'aux.', 'det.', 'int.', 'n.', 'v.']
    
    # 2. 檢查是否為「交錯型多重詞性」（例如 "v.張貼 ; 郵寄=mail; n.職位" 或 "v.宣判; n.句子"）
    pos_pattern = r'(v\.|n\.|adj\.|adv\.|prep\.|conj\.|pron\.|phr\.|aux\.)'
    parts = re.split(pos_pattern, cleaned_def, flags=re.IGNORECASE)
    if len(parts) >= 3:
        i = 1
        while i < len(parts) - 1:
            p = parts[i].strip().lower()
            if not p.endswith('.'): p += '.'
            d = parts[i+1].strip().strip(';').strip(',').strip('；').strip()
            if d:
                records.append({
                    "word": w_clean,
                    "phonetic": f"/{w_lower}/",
                    "part_of_speech": simple_s2t_convert(p),
                    "definition": simple_s2t_convert(d),
                    "advanced_sentence": pasted_eng_def or f"An English term referring to {w_clean}.",
                    "basic_sentence": pasted_sent,
                    "collocations": pasted_colloc
                })
            i += 2
        if records:
            return records

    # 3. 檢查是否為「字尾黏著多重詞性」（例如 "v.n.", "n.v.adj."）
    if not records:
        temp_def = cleaned_def
        extracted_pos = []
        while True:
            temp_lower = temp_def.lower().strip()
            matched = False
            for p in sorted(pos_tokens, key=len, reverse=True):
                if temp_lower.endswith(p):
                    extracted_pos.insert(0, p)
                    temp_def = temp_def[:-len(p)].strip().strip(';').strip(',').strip('；').strip()
                    matched = True
                    break
            if not matched:
                break
        
        if extracted_pos and len(extracted_pos) > 0:
            definition = temp_def
            def_parts = re.split(r'[；;,]', definition)
            def_parts = [dp.strip() for dp in def_parts if dp.strip()]
            
            if len(extracted_pos) > 1 and len(def_parts) == len(extracted_pos):
                for p, dp in zip(extracted_pos, def_parts):
                    records.append({
                        "word": w_clean,
                        "phonetic": f"/{w_lower}/",
                        "part_of_speech": simple_s2t_convert(p),
                        "definition": simple_s2t_convert(dp),
                        "advanced_sentence": pasted_eng_def or f"An English term referring to {w_clean}.",
                        "basic_sentence": pasted_sent,
                        "collocations": pasted_colloc
                    })
            elif len(extracted_pos) > 1 and len(def_parts) == 1:
                for p in extracted_pos:
                    records.append({
                        "word": w_clean,
                        "phonetic": f"/{w_lower}/",
                        "part_of_speech": simple_s2t_convert(p),
                        "definition": simple_s2t_convert(def_parts[0]),
                        "advanced_sentence": pasted_eng_def or f"An English term referring to {w_clean}.",
                        "basic_sentence": pasted_sent,
                        "collocations": pasted_colloc
                    })
            elif len(extracted_pos) > 1:
                for i, p in enumerate(extracted_pos):
                    dp = def_parts[i] if i < len(def_parts) else def_parts[-1] if def_parts else definition
                    records.append({
                        "word": w_clean,
                        "phonetic": f"/{w_lower}/",
                        "part_of_speech": simple_s2t_convert(p),
                        "definition": simple_s2t_convert(dp),
                        "advanced_sentence": pasted_eng_def or f"An English term referring to {w_clean}.",
                        "basic_sentence": pasted_sent,
                        "collocations": pasted_colloc
                    })
            else:
                records.append({
                    "word": w_clean,
                    "phonetic": f"/{w_lower}/",
                    "part_of_speech": simple_s2t_convert(extracted_pos[0]),
                    "definition": simple_s2t_convert(definition),
                    "advanced_sentence": pasted_eng_def or f"An English term referring to {w_clean}.",
                    "basic_sentence": pasted_sent,
                    "collocations": pasted_colloc
                })
            return records

    # 4. 若無任何標記，查詢線上字典或預設
    dict_meanings = fetch_all_meanings_from_dictionary(w_clean)
    if dict_meanings and not cleaned_def:
        for dm in dict_meanings:
            pos = simple_s2t_convert(dm['pos'])
            d_text = simple_s2t_convert(dm['definition'])
            eng_def = pasted_eng_def or dm['example'] or f"An English term referring to {w_clean}."
            records.append({
                "word": w_clean,
                "phonetic": dm['phonetic'],
                "part_of_speech": pos,
                "definition": d_text,
                "advanced_sentence": eng_def,
                "basic_sentence": pasted_sent,
                "collocations": pasted_colloc
            })
    else:
        fallback_pos = "phr." if " " in w_clean else "n."
        records.append({
            "word": w_clean,
            "phonetic": f"/{w_lower}/",
            "part_of_speech": fallback_pos,
            "definition": cleaned_def,
            "advanced_sentence": pasted_eng_def or f"A standard English expression referring to {w_clean}.",
            "basic_sentence": pasted_sent,
            "collocations": pasted_colloc
        })
    
    return records

def parse_raw_vocab_line_advanced(line):
    line_clean = re.sub(r'^\d+[\.\s]*', '', line).strip()
    if not line_clean:
        return []

    match_split = re.search(r'([\u4e00-\u9fa5]|v\.|n\.|adj\.|adv\.|prep\.|conj\.|pron\.|phr\.)', line_clean, re.IGNORECASE)
    if not match_split:
        return [{
            "word": line_clean,
            "phonetic": f"/{line_clean.lower()}/",
            "part_of_speech": "n.",
            "definition": "",
            "advanced_sentence": f"An English term referring to {line_clean}.",
            "basic_sentence": "",
            "collocations": ""
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
            if ' > ' in str(ut):
                sem, un = str(ut).split(' > ', 1)
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
        single_def = st.text_input("中文釋義（選填）：", placeholder="例如：v.張貼；n.職位")
        single_sent = st.text_input("真實例句（選填）：", placeholder="例如：Sentence here")
        single_colloc = st.text_input("搭配詞（選填）：", placeholder="例如：Collocation here")
        if st.button("🚀 查字典並寫入雲端", type="primary", use_container_width=True):
            if single_word:
                with st.spinner("🔍 正在查詢字典與寫入..."):
                    records = parse_mixed_vocab_input(single_word, raw_def=single_def, pasted_sent=single_sent, pasted_colloc=single_colloc)
                    df_current = load_vocab_dataframe(active_worksheet)
                    
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
                    st.success(f"🎉 成功新增單字：{single_word}（多重詞性已嚴格獨立拆分）")
                    time.sleep(0.5)
                    st.rerun()

    with col_input2:
        st.subheader("📋 智慧多格式快速貼上匯入")
        st.markdown(f"📍 **[狀態欄] 目前目標分類：** `{selected_level} ({current_unit_tag})`")
        
        pasted_text = st.text_area("貼上完整單字清單", placeholder="drink | 喝 | v. | take liquid | Drink some water. | drink water", height=140, label_visibility="collapsed")
        
        valid_lines = [l for l in pasted_text.strip().split('\n') if l.strip()] if pasted_text else []
        total_preview_count = len(valid_lines)
        if total_preview_count > 0:
            st.info(f"📊 **狀態預覽：** 偵測到 **{total_preview_count}** 個項目準備匯入至「{current_unit_tag}」")
        else:
            st.caption(f"📊 **狀態預覽：** 尚未貼上資料（目標：{current_unit_tag}）")

        status_box = st.empty()
        progress_box = st.empty()

        if st.button("📥 批次匯入完整清單", use_container_width=True):
            if pasted_text:
                lines = [l for l in pasted_text.strip().split('\n') if l.strip()]
                total_q = len(lines)
                df_current = load_vocab_dataframe(active_worksheet)
                count = 0
                
                for i, line in enumerate(lines):
                    current_num = i + 1
                    remaining_num = total_q - current_num
                    
                    status_box.markdown(f"還剩 **{remaining_num}** 個單字")
                    progress_box.progress(current_num / total_q)
                    
                    records = []
                    if '|' in line:
                        parts = [p.strip() for p in line.split('|')]
                        w = parts[0].strip()
                        d = parts[1].strip() if len(parts) > 1 else ""
                        pasted_p = parts[2].strip() if len(parts) > 2 else ""
                        pasted_eng = parts[3].strip() if len(parts) > 3 else ""
                        pasted_s = parts[4].strip() if len(parts) > 4 else ""
                        pasted_c = parts[5].strip() if len(parts) > 5 else ""
                        records = parse_mixed_vocab_input(w, raw_def=d, pasted_pos=pasted_p, pasted_eng_def=pasted_eng, pasted_sent=pasted_s, pasted_colloc=pasted_c)
                    elif '\t' in line:
                        parts = [p.strip() for p in line.split('\t')]
                        w = parts[0].strip()
                        d = parts[1].strip() if len(parts) > 1 else ""
                        pasted_p = parts[2].strip() if len(parts) > 2 else ""
                        records = parse_mixed_vocab_input(w, raw_def=d, pasted_pos=pasted_p)
                    else:
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
                status_box.success(f"🎊 成功匯入/更新 {count} 個項目（多重詞性與釋義已嚴格獨立拆分）！")
                time.sleep(1.5)
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
                        df_current = load_vocab_dataframe(active_worksheet)
                        df_current = df_current[df_current['word'].astype(str).str.strip().str.lower() != word_to_delete.strip().lower()]
                        if not df_current.empty:
                            df_current['id'] = range(1, len(df_current) + 1)
                        save_all_vocab_to_sheet(active_worksheet, df_current)
                        st.success(f"已刪除：{word_to_delete}")
                        time.sleep(1)
                        st.rerun()
            with sub_col2:
                st.write("") 
                st.write("")
                if st.button("🗑️ 刪除該課", type="secondary", use_container_width=True):
                    if selected_unit_filter == "全部單字" or " > " not in selected_unit_filter:
                        st.warning("⚠️ 請先在上方選單選擇到具體某一課，才能執行刪除該課！")
                    else:
                        df_current = load_vocab_dataframe(active_worksheet)
                        df_current = df_current[df_current['unit_tag'] != selected_unit_filter]
                        if not df_current.empty:
                            df_current['id'] = range(1, len(df_current) + 1)
                        save_all_vocab_to_sheet(active_worksheet, df_current)
                        st.success(f"🗑️ 已成功刪除「{selected_unit_filter}」整課單字！")
                        time.sleep(1)
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
                st.markdown(f"<h1 style='text-align: center; font-size: 54px; margin-bottom: 0;'>{row['word']}</h1>", unsafe_allow_html=True)
                st.markdown(f"<p style='text-align: center; color: gray; margin-top: 5px;'>{row.get('phonetic','')} | {row.get('part_of_speech','')}</p>", unsafe_allow_html=True)
                st.markdown("---")
                st.markdown(f"<h4 style='color: #4CAF50;'>中文釋義：{row['definition']}</h4>", unsafe_allow_html=True)
                if row.get('advanced_sentence'):
                    st.markdown(f"<p style='color: #2196F3; font-weight: bold; font-size: 19px;'>📖 英文釋義：{row.get('advanced_sentence')}</p>", unsafe_allow_html=True)
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
                target_adv_def = str(current_item.get('advanced_sentence', '')).strip() or "No English definition provided."
                hint_masked = "".join([" _ " if c.isalpha() else "    " for c in target_word])
                
                with st.container(border=True):
                    st.markdown(f"<h2 style='color: #4CAF50; margin: 0;'>中文釋義：{target_def}</h2>", unsafe_allow_html=True)
                    st.markdown(f"**🔤 拼字提示：** `{hint_masked}`")

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
                        user_ans = st.text_input("📝 請輸入您的拼寫答案：", key=f"ans_input_{st.session_state.game_index}").strip().lower()
                        if st.form_submit_button("🚀 送出答案", type="primary", use_container_width=True):
                            if user_ans == target_word.lower():
                                st.session_state.last_feedback = {"type": "success", "msg": f"🎉 答對了！就是 `{target_word}`"}
                            else:
                                st.session_state.wrong_answers.append(current_item)
                                st.session_state.last_feedback = {"type": "error", "msg": f"❌ 答錯囉！正確答案是：`{target_word}`"}
                            st.rerun()
