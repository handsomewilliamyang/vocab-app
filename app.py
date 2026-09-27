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

def get_word_record_data_clean(word, raw_def=""):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    cleaned_def = simple_s2t_convert(raw_def) if raw_def else ""

    real_eng_def, _, fetched_phonetic, fetched_pos = fetch_all_free_dictionaries(w_clean)

    if not fetched_phonetic:
        fetched_phonetic = f"/{w_lower.replace(' ', '')}/"
    if not fetched_pos:
        fetched_pos = "phr." if " " in w_clean else "n."

    return {
        "word": w_clean,
        "phonetic": fetched_phonetic,
        "part_of_speech": simple_s2t_convert(fetched_pos),
        "definition": cleaned_def,
        "advanced_sentence": real_eng_def if real_eng_def else "", # 保留英文釋義
        "basic_sentence": "",    # 例句保持乾淨空白
        "collocations": ""       # 搭配詞保持乾淨空白
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
        if st.button("🚀 查字典並寫入雲端", type="primary", use_container_width=True):
            if single_word:
                with st.spinner("🔍 正在查詢字典並寫入..."):
                    data = get_word_record_data_clean(single_word, raw_def=single_def)
                    word = data.get('word')
                    
                    df_current = load_vocab_dataframe(active_worksheet)
                    if not df_current.empty and word.lower() in df_current['word'].str.lower().values:
                        idx = df_current.index[df_current['word'].str.lower() == word.lower()].tolist()[0]
                        df_current.at[idx, 'phonetic'] = data.get('phonetic', '')
                        df_current.at[idx, 'part_of_speech'] = data.get('part_of_speech', '')
                        if data.get('definition'): df_current.at[idx, 'definition'] = data.get('definition')
                        if data.get('advanced_sentence'): df_current.at[idx, 'advanced_sentence'] = data.get('advanced_sentence')
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
                            'basic_sentence': '',
                            'collocations': '',
                            'unit_tag': current_unit_tag,
                            'srs_stage': 0
                        }])
                        df_current = pd.concat([df_current, new_row], ignore_index=True)
                        
                    save_all_vocab_to_sheet(active_worksheet, df_current)
                    st.success(f"🎉 成功新增單字：{word}")
                    time.sleep(0.5)
                    st.rerun()

    with col_input2:
        st.subheader("📋 文字/CSV 快速貼上匯入")
        st.markdown("您可以直接將單字清單貼在下方（每行一個，格式：`單字, 中文釋義` 或直接從 Excel 複製貼上）：")
        
        pasted_text = st.text_area("貼上單字清單：", placeholder="resilient, 彈性的\nefficient, 有效率的", height=150)
        if st.button("📥 批次匯入文字清單", use_container_width=True):
            if pasted_text:
                lines = pasted_text.strip().split('\n')
                df_current = load_vocab_dataframe(active_worksheet)
                count = 0
                for line in lines:
                    parts = [p.strip() for p in re.split(r'[,;\t|]', line) if p.strip()]
                    if parts:
                        w = parts[0]
                        d = parts[1] if len(parts) > 1 else ""
                        if w and len(w) < 35:
                            data = get_word_record_data_clean(w, raw_def=d)
                            if not df_current.empty and w.lower() in df_current['word'].str.lower().values:
                                idx = df_current.index[df_current['word'].str.lower() == w.lower()].tolist()[0]
                                df_current.at[idx, 'phonetic'] = data.get('phonetic', '')
                                df_current.at[idx, 'part_of_speech'] = data.get('part_of_speech', '')
                                if d: df_current.at[idx, 'definition'] = simple_s2t_convert(d)
                                if data.get('advanced_sentence'): df_current.at[idx, 'advanced_sentence'] = data.get('advanced_sentence')
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
                                    'basic_sentence': '',
                                    'collocations': '',
                                    'unit_tag': current_unit_tag,
                                    'srs_stage': 0
                                }])
                                df_current = pd.concat([df_current, new_row], ignore_index=True)
                            count += 1
                save_all_vocab_to_sheet(active_worksheet, df_current)
                st.success(f"🎊 成功匯入 {count} 個單字！")
                time.sleep(1)
                st.rerun()

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
            # 💡 嚴格只清空例句與搭配詞，保留英文釋義
            if st.button("🧹 一鍵清空「例句」與「搭配詞」(保留英文釋義)", type="primary", use_container_width=True):
                df_current = load_vocab_dataframe(active_worksheet, force_reload=True).copy()
                if selected_unit_filter != "全部單字":
                    target_indices = df_current[df_current['unit_tag'] == selected_unit_filter].index
                    df_current.loc[target_indices, 'basic_sentence'] = ""
                    df_current.loc[target_indices, 'collocations'] = ""
                else:
                    df_current['basic_sentence'] = ""
                    df_current['collocations'] = ""
                
                success, msg = save_all_vocab_to_sheet(active_worksheet, df_current)
                if success:
                    st.success("✅ 已成功清空所選範圍的例句與搭配詞（英文釋義已完整保留）！")
                else:
                    st.warning(f"⚠️ 雲端更新稍有延遲 ({msg})")
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
