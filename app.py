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

def fetch_all_free_dictionaries(word):
    w_clean = word.strip().lower()
    real_def = ""
    real_example = ""
    phonetic = ""
    pos = ""

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
                        if ex_candidate:
                            real_example = ex_candidate
                        if real_def and real_example:
                            break
                    if real_def and real_example:
                        break
    except Exception:
        pass

    return real_def, real_example, phonetic, pos

def get_word_record_data_clean(word, raw_def="", pasted_pos="", pasted_eng_def="", pasted_sent="", pasted_colloc=""):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    cleaned_def = simple_s2t_convert(raw_def) if raw_def else ""

    real_eng_def, _, fetched_phonetic, fetched_pos = fetch_all_free_dictionaries(w_clean)

    if pasted_pos:
        fetched_pos = simple_s2t_convert(pasted_pos)

    if not real_eng_def or pasted_eng_def:
        if pasted_eng_def:
            real_eng_def = simple_s2t_convert(pasted_eng_def)

    if not real_eng_def and HAS_GEMINI and st.session_state.get("gemini_api_key"):
        try:
            genai.configure(api_key=st.session_state["gemini_api_key"])
            model = genai.GenerativeModel(
                "gemini-1.5-flash",
                generation_config={"response_mime_type": "application/json", "temperature": 0.7}
            )
            prompt = f"""Provide a professional, clear English definition for: "{w_clean}" (Chinese meaning: "{cleaned_def}").
            Return a JSON object strictly matching this schema:
            {{
              "english_definition": "A clear and concise definition in English."
            }}"""
            response = model.generate_content(prompt)
            data_json = json.loads(response.text)
            real_eng_def = data_json.get("english_definition", "")
        except Exception:
            pass

    if not real_eng_def:
        if cleaned_def:
            real_eng_def = f"An English term meaning {cleaned_def}."
        else:
            real_eng_def = f"A standard English expression referring to {w_clean}."

    if not fetched_phonetic:
        fetched_phonetic = f"/{w_lower.replace(' ', '')}/"
    if not fetched_pos:
        fetched_pos = "phr." if " " in w_clean else "n."

    return {
        "word": w_clean,
        "phonetic": fetched_phonetic,
        "part_of_speech": simple_s2t_convert(fetched_pos),
        "definition": cleaned_def,
        "advanced_sentence": real_eng_def,
        "basic_sentence": pasted_sent,
        "collocations": pasted_colloc
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
        single_def = st.text_input("中文釋義（選填）：", placeholder="例如：有彈性的、韌性強的")
        single_sent = st.text_input("真實例句（選填）：", placeholder="例如：Sentence here")
        single_colloc = st.text_input("搭配詞（選填）：", placeholder="例如：Collocation here")
        if st.button("🚀 查字典並寫入雲端", type="primary", use_container_width=True):
            if single_word:
                with st.spinner("🔍 正在查詢字典與寫入..."):
                    data = get_word_record_data_clean(single_word, raw_def=single_def)
                    word = data.get('word')
                    
                    df_current = load_vocab_dataframe(active_worksheet)
                    # 以「單字」本身作為唯一識別（確保每個單字只有一個大格）
                    match_mask = df_current['word'].astype(str).str.strip().str.lower() == word.lower()
                    if not df_current.empty and match_mask.any():
                        idx = df_current.index[match_mask].tolist()[0]
                        df_current.at[idx, 'phonetic'] = data.get('phonetic', '')
                        df_current.at[idx, 'part_of_speech'] = data.get('part_of_speech', '')
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
                            'part_of_speech': data.get('part_of_speech', ''),
                            'definition': data.get('definition', ''),
                            'advanced_sentence': data.get('advanced_sentence', ''),
                            'basic_sentence': single_sent,
                            'collocations': single_colloc,
                            'unit_tag': current_unit_tag,
                            'srs_stage': 0
                        }])
                        df_current = pd.concat([df_current, new_row], ignore_index=True)
                        
                    save_all_vocab_to_sheet(active_worksheet, df_current)
                    st.success(f"🎉 成功新增單字：{word}")
                    time.sleep(0.5)
                    st.rerun()

    with col_input2:
        st.subheader("📋 智慧多格式快速貼上匯入")
        st.markdown(f"📍 **[狀態欄] 目前目標分類：** `{selected_level} ({current_unit_tag})`")
        
        pasted_text = st.text_area("貼上完整單字清單（支援：單字 | 中文 | 詞性 | 英文釋義 | 例句 | 搭配詞）：", placeholder="drink | 喝 | v. | take liquid | Drink some water. | drink water", height=140)
        
        valid_lines = [l for l in pasted_text.strip().split('\n') if l.strip()] if pasted_text else []
        total_preview_count = len(valid_lines)
        if total_preview_count > 0:
            st.info(f"📊 **狀態預覽：** 偵測到 **{total_preview_count}** 個單字準備匯入至「{current_unit_tag}」")
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
                    
                    status_box.markdown(f"🔄 **[執行狀態]** 正在匯入：`{current_unit_tag}` | 目前進度：第 **{current_num}** / {total_q} 個字（還剩 **{remaining_num}** 個字）")
                    progress_box.progress(current_num / total_q)
                    
                    if '|' in line:
                        parts = [p.strip() for p in line.split('|')]
                    elif '\t' in line:
                        parts = [p.strip() for p in line.split('\t')]
                    else:
                        parts = [p.strip() for p in line.split(',')]
                        
                    if parts and parts[0].strip():
                        w = parts[0].strip()
                        d = parts[1].strip() if len(parts) > 1 else ""
                        
                        pasted_p = ""
                        pasted_eng = ""
                        pasted_s = ""
                        pasted_c = ""
                        
                        if len(parts) >= 6:
                            pasted_p = parts[2].strip()
                            pasted_eng = parts[3].strip()
                            pasted_s = parts[4].strip()
                            pasted_c = parts[5].strip()
                        elif len(parts) == 5:
                            candidate_pos = parts[2].strip().lower()
                            pos_keywords = ['n.', 'v.', 'adj.', 'adv.', 'prep.', 'conj.', 'pron.', 'phr.', 'aux.', '名詞', '動詞', '形容詞']
                            is_pos = any(k in candidate_pos for k in pos_keywords) and len(candidate_pos) < 15
                            if is_pos:
                                pasted_p = parts[2].strip()
                                pasted_eng = parts[3].strip()
                                pasted_s = parts[4].strip()
                            else:
                                pasted_eng = parts[2].strip()
                                pasted_s = parts[3].strip()
                                pasted_c = parts[4].strip()
                        elif len(parts) == 4:
                            pasted_eng = parts[2].strip()
                            pasted_s = parts[3].strip()
                        elif len(parts) == 3:
                            pasted_eng = parts[2].strip()
                        
                        if len(w) < 35:
                            data = get_word_record_data_clean(
                                w, 
                                raw_def=d, 
                                pasted_pos=pasted_p, 
                                pasted_eng_def=pasted_eng, 
                                pasted_sent=pasted_s, 
                                pasted_colloc=pasted_c
                            )

                            # 以「單字」本身作為唯一識別，確保每個單字只會有一行（一個大格）
                            match_mask = df_current['word'].astype(str).str.strip().str.lower() == w.lower()
                            
                            if not df_current.empty and match_mask.any():
                                idx = df_current.index[match_mask].tolist()[0]
                                df_current.at[idx, 'phonetic'] = data.get('phonetic', '')
                                df_current.at[idx, 'part_of_speech'] = data.get('part_of_speech', '')
                                if d: df_current.at[idx, 'definition'] = simple_s2t_convert(d)
                                df_current.at[idx, 'advanced_sentence'] = data.get('advanced_sentence', '')
                                if data.get('basic_sentence'): df_current.at[idx, 'basic_sentence'] = data.get('basic_sentence')
                                if data.get('collocations'): df_current.at[idx, 'collocations'] = data.get('collocations')
                                df_current.at[idx, 'unit_tag'] = current_unit_tag
                            else:
                                next_id = len(df_current) + 1
                                new_row = pd.DataFrame([{
                                    'id': next_id,
                                    'word': w,
                                    'phonetic': data.get('phonetic', ''),
                                    'part_of_speech': data.get('part_of_speech', ''),
                                    'definition': simple_s2t_convert(d),
                                    'advanced_sentence': data.get('advanced_sentence', ''),
                                    'basic_sentence': data.get('basic_sentence', ''),
                                    'collocations': data.get('collocations', ''),
                                    'unit_tag': current_unit_tag,
                                    'srs_stage': 0
                                }])
                                df_current = pd.concat([df_current, new_row], ignore_index=True)
                            count += 1
                save_all_vocab_to_sheet(active_worksheet, df_current)
                status_box.success(f"🎊 成功匯入/更新 {count} 個單字的完整資料（分類：{current_unit_tag}）！")
                time.sleep(1.5)
                st.rerun()

elif main_menu == "📖 字彙管理":
    if df_vocab.empty:
        st.info("📭 目前雲端尚無單字，請至側邊欄新增！")
    else:
        unit_list = sorted(df_vocab['unit_tag'].dropna().unique().tolist()) if 'unit_tag' in df_vocab.columns else []
        unit_list = ["全部單字"] + [u for u in unit_list if u.strip() != ""]
        
        selected_unit_filter = st.selectbox("依學習單元篩選顯示：", unit_list)

        filtered_df = df_vocab if selected_unit_filter == "全部單字" else df_vocab[df_vocab['unit_tag'] == selected_unit_filter]
        
        search_query = st.text_input("🔍 搜尋單字或釋義：")
        if search_query:
            filtered_df = filtered_df[filtered_df['word'].str.contains(search_query, case=False, na=False) | filtered_df['definition'].str.contains(search_query, case=False, na=False)]

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

elif main_menu == "🎯 背誦單字":
    if df_vocab.empty:
        st.warning(f"📭 目前雲端沒有單字！")
    else:
        unit_list_flash = ["全部單字"] + sorted(df_vocab['unit_tag'].dropna().unique().tolist()) if 'unit_tag' in df_vocab.columns else ["全部單字"]
        selected_flash_unit = st.selectbox("🎯 選擇要複習的單元：", unit_list_flash, key="flash_unit_select")
        
        df_filtered_flash = df_vocab if selected_flash_unit == "全部單字" else df_vocab[df_vocab['unit_tag'] == selected_flash_unit]
        
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
        unit_list_game = ["全部單字"] + sorted(df_vocab['unit_tag'].dropna().unique().tolist()) if 'unit_tag' in df_vocab.columns else ["全部單字"]
        selected_game_unit = st.selectbox("選擇遊戲挑戰的單元範圍：", unit_list_game, key="game_unit_select")
        df_filtered_game = df_vocab if selected_game_unit == "全部單字" else df_vocab[df_vocab['unit_tag'] == selected_game_unit]
        
        if not df_filtered_game.empty:
            state_key = f"game_started_{game_mode}"
            if state_key not in st.session_state or st.session_state.get("current_game_unit") != selected_game_unit:
                st.session_state[state_key] = True
                st.session_state.current_game_unit = selected_game_unit
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
                if st.button("🔄 重新挑戰本單元", type="primary", use_container_width=True):
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
