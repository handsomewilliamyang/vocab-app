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
    page_title="我愛背單字 (雲端同步版)",
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
user_api_key = st.sidebar.text_input("輸入 Gemini API Key (選填)", type="password", value=st.secrets.get("gemini_api_key", ""))
if user_api_key:
    st.session_state.gemini_api_key = user_api_key
    st.sidebar.success("✅ AI 引擎已啟用")
else:
    st.session_state.gemini_api_key = ""
    st.sidebar.warning("⚠️ 未輸入 API Key")

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
    active_worksheet = gs_client.open_by_url(SHEET_URL).worksheet(current_sheet_name)
except Exception as e:
    st.error(f"⚠️ 找不到名為「{current_sheet_name}」的工作表。")
    st.stop()

st.sidebar.markdown("---")
st.sidebar.info(f"💡 雲端同步中：已連線至工作表【{current_sheet_name}】")

@st.cache_data(ttl=2)
def get_vocab_from_sheets(_worksheet):
    records = _worksheet.get_all_records()
    if not records:
        return pd.DataFrame(columns=['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'basic_sentence', 'advanced_sentence', 'collocations', 'unit_tag', 'srs_stage'])
    df = pd.DataFrame(records)
    # 確保必要欄位存在
    if 'word' not in df.columns and 'id' in df.columns:
        # 如果欄位位移，重新對應
        pass
    return df

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

def clean_sentence(text):
    if not text: return ""
    text = re.sub(r'\s*\(.*?\)', '', str(text)).strip()
    return text

def auto_translate_english_to_chinese(word):
    if HAS_GEMINI and st.session_state.get('gemini_api_key'):
        try:
            genai.configure(api_key=st.session_state.gemini_api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"Provide a concise Traditional Chinese definition (釋義) and part of speech for the English word '{word}'. Format: [詞性] 中文釋義"
            response = model.generate_content(prompt)
            if response.text:
                return simple_s2t_convert(response.text.strip())
        except:
            pass
    return "(請手動編輯中文釋義)"

def fetch_sentence(word):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    search_root = w_lower[:4] if len(w_lower) >= 4 else w_lower

    if HAS_GEMINI and st.session_state.get('gemini_api_key'):
        try:
            genai.configure(api_key=st.session_state.gemini_api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"Write a single, practical, everyday English sentence using the word '{w_clean}'. Return ONLY the English sentence."
            response = model.generate_content(prompt)
            if response.text:
                clean_res = response.text.strip().replace('"', '').replace('\n', '')
                if search_root in clean_res.lower():
                    return clean_res
        except:
            pass
    return f"Students should learn common {w_clean}."

def get_word_record_data(word):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    return {
        "word": w_clean,
        "phonetic": f"/{w_lower}/",
        "part_of_speech": "n. / v.",
        "definition": auto_translate_english_to_chinese(w_clean),
        "basic_sentence": fetch_sentence(w_clean),
        "advanced_sentence": "",
        "collocations": f"common {w_clean}"
    }

def update_single_word_in_sheet(_worksheet, target_word, new_word, new_phonetic, new_pos, new_def, new_basic, new_adv, new_coll):
    try:
        df = get_vocab_from_sheets(_worksheet)
        row_idx = df.index[df['word'] == target_word].tolist()[0] + 2
        
        row_values = _worksheet.row_values(row_idx)
        row_id = row_values[0] if len(row_values) > 0 else 1
        unit_tag = row_values[8] if len(row_values) > 8 else "國一上 > 第一課"
        srs = row_values[9] if len(row_values) > 9 else 0
        
        new_row = [row_id, new_word, new_phonetic, new_pos, simple_s2t_convert(new_def), new_basic, new_adv, new_coll, unit_tag, srs]
        _worksheet.update(f'A{row_idx}:J{row_idx}', [new_row])
        get_vocab_from_sheets.clear()
        return True, "成功"
    except Exception as e:
        return False, str(e)

def delete_words_from_sheet(_worksheet, word_list):
    if not word_list: return
    df = get_vocab_from_sheets(_worksheet)
    rows_to_delete = sorted([df.index[df['word'] == w].tolist()[0] + 2 for w in word_list if w in df['word'].values], reverse=True)
    for r in rows_to_delete:
        _worksheet.delete_rows(r)
    get_vocab_from_sheets.clear()

@st.cache_data(show_spinner=False)
def generate_audio_bytes(text, lang='en'):
    tts = gTTS(text=text, lang=lang)
    fp = io.BytesIO()
    tts.write_to_fp(fp)
    return fp.getvalue()

st.title("📚 我愛背單字 (雲端同步版)")

df_vocab = get_vocab_from_sheets(active_worksheet)
total_words = len(df_vocab)

col_m1, col_m2 = st.columns(2)
with col_m1:
    st.metric(label="雲端總單字數", value=f"{total_words} 個")
with col_m2:
    st.metric(label="目前模式", value=f"{main_menu} ({selected_level})")

st.markdown("<br>", unsafe_allow_html=True)

if main_menu == "✨ 智慧單字新增":
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        semester = st.selectbox("選擇年級學期：", ["國一上", "國一下", "國二上", "國二下", "國三上", "國三下"])
    with col_u2:
        unit = st.selectbox("選擇課次單元：", ["第一課", "第二課", "第三課", "第四課", "第五課", "第六課"])
        
    current_unit_tag = f"{semester} > {unit}"
    st.info(f"📌 即時同步至 Google Sheets 【{current_sheet_name}】分頁：**{current_unit_tag}**")
    
    single_word = st.text_input("輸入想要學習的英文單字：", placeholder="例如：resilient")
    if st.button("🚀 寫入雲端單字庫", type="primary", use_container_width=True):
        if single_word:
            data = get_word_record_data(single_word)
            try:
                next_id = len(df_vocab) + 1
                new_row = [next_id, data['word'], data['phonetic'], data['part_of_speech'], data['definition'], data['basic_sentence'], "", data['collocations'], current_unit_tag, 0]
                active_worksheet.append_row(new_row)
                get_vocab_from_sheets.clear()
                st.success(f"🎉 成功新增單字：{single_word}")
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"❌ 寫入失敗：{e}")

elif main_menu == "📖 字庫管理與搜尋":
    if df_vocab.empty:
        st.info("📭 目前雲端尚無單字，請至側邊欄新增！")
    else:
        unit_list = sorted(df_vocab['unit_tag'].dropna().unique().tolist()) if 'unit_tag' in df_vocab.columns else ["全部單字"]
        selected_unit_filter = st.selectbox("依學習單元篩選：", ["全部單字"] + unit_list)

        filtered_df = df_vocab if selected_unit_filter == "全部單字" else df_vocab[df_vocab['unit_tag'] == selected_unit_filter]
        
        search_query = st.text_input("🔍 搜尋單字或釋義：")
        if search_query:
            filtered_df = filtered_df[filtered_df['word'].str.contains(search_query, case=False, na=False) | filtered_df['definition'].str.contains(search_query, case=False, na=False)]

        st.dataframe(filtered_df[['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'basic_sentence', 'unit_tag']], use_container_width=True, hide_index=True)

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
            
        with st.expander("💡 詳細釋義與真實例句", expanded=True):
            st.markdown(f"**中文釋義：** {row['definition']}")
            st.markdown(f"**例句：** {row.get('basic_sentence','')}")
        
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
        row = df_vocab.sample(1).iloc[0]
        w = str(row['word']).strip()
        st.markdown(f"### 🎯 挑戰單字：`{w}`")
        st.markdown(f"**📌 中文釋義：** `{row.get('definition','')}`")
        audio = generate_audio_bytes(w)
        try: st.audio(audio, format="audio/mp3")
        except: pass
        
        ans = st.text_input("請輸入拼寫：").strip().lower()
        if st.button("送出"):
            if ans == w.lower():
                st.success("答對了！")
            else:
                st.error(f"答錯了，正確答案是 {w}")