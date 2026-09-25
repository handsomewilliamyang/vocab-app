import sqlite3
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

# -------------------------------------------------------------------------
# 0. 頁面全域設定
# -------------------------------------------------------------------------
st.set_page_config(
    page_title="我愛背單字",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -------------------------------------------------------------------------
# 1. 側邊欄導覽與級別切換
# -------------------------------------------------------------------------
st.sidebar.markdown("<h2 style='font-size: 24px;'>⚙️ 系統導覽與設定</h2>", unsafe_allow_html=True)

st.sidebar.markdown("---")
st.sidebar.markdown("<h3 style='font-size: 20px;'>📌 功能選單</h3>", unsafe_allow_html=True)
main_menu = st.sidebar.radio(
    "選擇主要功能：",
    ["✨ 智慧單字新增", "📖 字庫管理與搜尋", "🎯 沉浸式閃卡複習", "🎮 拼字王挑戰遊戲"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")
st.sidebar.markdown("<h3 style='font-size: 20px;'>📂 學習階段 / 級別分類</h3>", unsafe_allow_html=True)
selected_level = st.sidebar.radio(
    "選擇目前目標級別：",
    ["國中部", "高中部", "多益 (TOEIC)"],
    label_visibility="collapsed"
)

db_mapping = {
    "國中部": "junior.db",
    "高中部": "senior.db",
    "多益 (TOEIC)": "toeic.db"
}
current_db_name = db_mapping.get(selected_level, "vocabulary.db")

st.sidebar.markdown("---")
st.sidebar.info(f"💡 目前模式：專注於 {selected_level} 單字訓練（獨立資料庫）。")

# -------------------------------------------------------------------------
# 2. 簡繁轉換與初始化
# -------------------------------------------------------------------------
S2T_DICT = {
    "餐厅": "餐廳", "饭厅": "餐廳", "计算机": "電腦", "网络": "網路", 
    "软件": "軟體", "硬件": "硬體", "信息": "資訊", "视频": "影片", 
    "音频": "音訊", "文件": "檔案", "打印": "列印", "鼠标": "滑鼠", 
    "键盘": "鍵盤", "屏幕": "螢幕", "项目": "專案", "组": "組", 
    "默认": "預設", "句": "句", "词": "詞", "语法": "語法"
}

def simple_s2t_convert(text):
    if not text:
        return text
    for s, t in S2T_DICT.items():
        text = text.replace(s, t)
    return text

def init_db(db_name):
    conn = sqlite3.connect(db_name)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS vocab (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE,
            phonetic TEXT,
            part_of_speech TEXT,
            definition TEXT,
            basic_sentence TEXT,
            advanced_sentence TEXT,
            collocations TEXT,
            unit_tag TEXT DEFAULT '國一上 > 第一課',
            srs_stage INTEGER DEFAULT 0
        )
    ''')
    try:
        c.execute("ALTER TABLE vocab ADD COLUMN unit_tag TEXT DEFAULT '國一上 > 第一課'")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

init_db(current_db_name)

# -------------------------------------------------------------------------
# 3. 核心工具函式（安全且非阻塞的字典串接）
# -------------------------------------------------------------------------
def clean_sentence(text):
    if not text:
        return ""
    text = re.sub(r'\s*\(.*?\)', '', str(text)).strip()
    if "example sentence using" in text.lower() or "we can easily see how" in text.lower():
        return ""
    return text

def auto_translate_english_to_chinese(word):
    try:
        url = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(word)}&langpair=en|zh-TW"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode('utf-8'))
            translated_text = data.get('responseData', {}).get('translatedText', word)
            translated_text = re.sub(r'^[a-zA-Z\s\-\,\.]+\s+', '', translated_text)
            translated_text = simple_s2t_convert(translated_text)
            if translated_text.lower() == word.lower() or not re.search(r'[\u4e00-\u9fa5]', translated_text):
                return "(待補充中文)"
            return translated_text
    except Exception:
        return "(待補充中文)"

def fetch_real_dictionary_sentence(word):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    
    try:
        dict_url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(w_clean)}"
        req = urllib.request.Request(dict_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            dict_data = json.loads(response.read().decode('utf-8'))
            if isinstance(dict_data, list) and len(dict_data) > 0:
                meanings = dict_data[0].get('meanings', [])
                if meanings:
                    for meaning in meanings:
                        definitions = meaning.get('definitions', [])
                        for d_obj in definitions:
                            if 'example' in d_obj and d_obj['example']:
                                ex = d_obj['example'].strip()
                                if w_lower in ex.lower():
                                    return ex
    except Exception:
        pass
        
    return f"People frequently use {w_clean} in daily conversation."

def get_word_record_data(word):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    translated_zh = auto_translate_english_to_chinese(w_clean)
    real_sent = fetch_real_dictionary_sentence(w_clean)
    
    return {
        "word": w_clean,
        "phonetic": f"/{w_lower}/",
        "part_of_speech": "n. / v.",
        "definition": simple_s2t_convert(translated_zh),
        "basic_sentence": real_sent,
        "advanced_sentence": f"Advanced context for understanding {w_clean}.",
        "collocations": f"practice {w_clean}"
    }

def upsert_word_to_db(data, db_name, unit_tag):
    conn = sqlite3.connect(db_name)
    c = conn.cursor()
    try:
        word = data.get('word')
        raw_def = data.get('definition', '')
        clean_def = re.sub(r'^[a-zA-Z\s\-\,\.]+\s+', '', raw_def)
        clean_def = simple_s2t_convert(clean_def)
        if not re.search(r'[\u4e00-\u9fa5]', clean_def):
            clean_def = "(待補充中文)"

        b_sent = clean_sentence(data.get('basic_sentence'))
        if not b_sent or word.lower() not in b_sent.lower():
            b_sent = fetch_real_dictionary_sentence(word)
            
        a_sent = clean_sentence(data.get('advanced_sentence'))

        c.execute("SELECT id FROM vocab WHERE word = ?", (word,))
        row = c.fetchone()
        
        if row:
            c.execute('''
                UPDATE vocab 
                SET phonetic=?, part_of_speech=?, definition=?, basic_sentence=?, advanced_sentence=?, collocations=?, unit_tag=?
                WHERE word=?
            ''', (
                data.get('phonetic'), data.get('part_of_speech'), clean_def,
                b_sent, a_sent, data.get('collocations'), unit_tag, word
            ))
        else:
            c.execute('''
                INSERT INTO vocab (word, phonetic, part_of_speech, definition, basic_sentence, advanced_sentence, collocations, unit_tag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                word, data.get('phonetic'), data.get('part_of_speech'), clean_def,
                b_sent, a_sent, data.get('collocations'), unit_tag
            ))
        conn.commit()
        success = True
    except Exception as e:
        success = False
    finally:
        conn.close()
    return success

def get_vocab_by_db(db_name):
    conn = sqlite3.connect(db_name)
    df = pd.read_sql("SELECT * FROM vocab", conn)
    conn.close()
    if 'unit_tag' not in df.columns:
        df['unit_tag'] = '國一上 > 第一課'
    df['unit_tag'] = df['unit_tag'].fillna('國一上 > 第一課')
    return df

@st.cache_data(show_spinner=False)
def generate_audio_bytes(text, lang='en'):
    tts = gTTS(text=text, lang=lang)
    fp = io.BytesIO()
    tts.write_to_fp(fp)
    return fp.getvalue()

# -------------------------------------------------------------------------
# 4. 主畫面佈局
# -------------------------------------------------------------------------
st.title("📚 我愛背單字")

df_vocab = get_vocab_by_db(current_db_name)
total_words = len(df_vocab)

clean_menu_name = re.sub(r'[^\w\s]', '', main_menu).strip()
top_right_display = f"{clean_menu_name} ({selected_level})"

col_m1, col_m2 = st.columns(2)
with col_m1:
    st.metric(label="總單字數", value=f"{total_words} 個")
with col_m2:
    st.metric(label="目前模式", value=top_right_display)

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
        if selected_level == "國中部":
            unit = st.selectbox("選擇課次單元：", ["第一課", "第二課", "第三課", "第四課", "第五課", "第六課"])
        else:
            unit = st.selectbox("選擇課次單元：", ["第一課", "第二課", "第三課", "第四課", "第五課", "第六課", "Review 1", "Review 2", "核心單字總覽"])
        
    current_unit_tag = f"{semester} > {unit}"
    st.info(f"📌 目前新增的單字將歸類至：**{current_unit_tag}**")
    st.markdown("---")

    col_input1, col_input2 = st.columns(2, gap="large")
    
    with col_input1:
        st.subheader("📝 單筆快速建檔")
        single_word = st.text_input("輸入想要學習的英文單字：", placeholder="例如：resilient")
        if st.button("🚀 加入專屬單字庫", type="primary", use_container_width=True):
            if not single_word:
                st.warning("請先輸入單字！")
            else:
                word_data = get_word_record_data(single_word.strip())
                if word_data:
                    if upsert_word_to_db(word_data, current_db_name, current_unit_tag):
                        st.success(f"🎉 成功新增單字：{single_word} 至 【{current_unit_tag}】")
                        st.json(word_data)
                    else:
                        st.error("❌ 寫入資料庫失敗！")

    with col_input2:
        st.subheader("📂 檔案與智慧匯入")
        import_mode = st.radio("選擇匯入來源：", ["CSV 檔案", "Word 檔案 (.docx)"], horizontal=True)
        if import_mode == "Word 檔案 (.docx)":
            uploaded_docxs = st.file_uploader("上傳 Word 講義檔案", type=["docx"], accept_multiple_files=True)
            if uploaded_docxs:
                st.info(f"📁 已載入 {len(uploaded_docxs)} 個檔案，確認匯入單元為：**{current_unit_tag}**")
                if st.button("📖 解析所有 Word 並智慧批次匯入", use_container_width=True):
                    total_success_count = 0
                    for uploaded_docx in uploaded_docxs:
                        temp_path = f"temp_{uploaded_docx.name}"
                        try:
                            with open(temp_path, "wb") as f:
                                f.write(uploaded_docx.getbuffer())
                            doc = docx.Document(temp_path)
                            for table in doc.tables:
                                for row in table.rows:
                                    for cell in row.cells:
                                        for line in cell.text.strip().split('\n'):
                                            cleaned = re.sub(r'^\d+[\.、\s]*', '', line).strip()
                                            if cleaned and len(cleaned) < 35 and not re.search(r'[\u4e00-\u9fa5]', cleaned):
                                                w_data = get_word_record_data(cleaned)
                                                if upsert_word_to_db(w_data, current_db_name, current_unit_tag):
                                                    total_success_count += 1
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                        except Exception:
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                    st.success(f"🎊 批次匯入完成！成功匯入 {total_success_count} 個單字。")

elif main_menu == "📖 字庫管理與搜尋":
    df_vocab = get_vocab_by_db(current_db_name)
    if df_vocab.empty:
        st.info("📭 目前尚無單字，請至側邊欄新增！")
    else:
        unit_list = sorted(df_vocab['unit_tag'].dropna().unique().tolist()) + ["全部單字"]
        selected_unit_filter = st.selectbox("依學習單元篩選：", unit_list)
        filtered_df = df_vocab if selected_unit_filter == "全部單字" else df_vocab[df_vocab['unit_tag'] == selected_unit_filter]
        
        search_query = st.text_input("🔍 搜尋單字或釋義：")
        if search_query:
            filtered_df = filtered_df[filtered_df['word'].str.contains(search_query, case=False, na=False) | filtered_df['definition'].str.contains(search_query, case=False, na=False)]
        
        with st.expander("📋 單字總表與快速編輯", expanded=True):
            st.dataframe(filtered_df[['word', 'phonetic', 'part_of_speech', 'definition', 'basic_sentence', 'unit_tag']], use_container_width=True, hide_index=True)

elif main_menu == "🎯 沉浸式閃卡複習":
    df_vocab_flash = get_vocab_by_db(current_db_name)
    if df_vocab_flash.empty:
        st.warning("📭 目前沒有單字！")
    else:
        if "flashcard_index" not in st.session_state:
            st.session_state.flashcard_index = 0
        total_count = len(df_vocab_flash)
        st.session_state.flashcard_index = st.session_state.flashcard_index % total_count
        row = df_vocab_flash.iloc[st.session_state.flashcard_index]
        
        with st.container(border=True):
            st.markdown(f"<h1 style='text-align: center; font-size: 54px;'>🔤 {row['word']}</h1>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align: center; color: gray;'>{row.get('phonetic','')} | {row.get('part_of_speech','')}</p>", unsafe_allow_html=True)
            
        with st.expander("💡 詳細釋義與例句", expanded=True):
            st.markdown(f"**中文釋義：** {row['definition']}")
            display_sent = clean_sentence(row.get('basic_sentence', ''))
            if not display_sent:
                display_sent = fetch_real_dictionary_sentence(row['word'])
            st.markdown(f"**真實例句：** {display_sent}")
        
        c1, c2 = st.columns(2)
        if c1.button("⬅️ 上一個", use_container_width=True):
            st.session_state.flashcard_index = (st.session_state.flashcard_index - 1) % total_count
            st.rerun()
        if c2.button("➡️ 下一個", use_container_width=True):
            st.session_state.flashcard_index = (st.session_state.flashcard_index + 1) % total_count
            st.rerun()

elif main_menu == "🎮 拼字王挑戰遊戲":
    df_vocab_game = get_vocab_by_db(current_db_name)
    if df_vocab_game.empty:
        st.warning("📭 目前沒有足夠的單字來進行遊戲！")
    else:
        unit_list_game = ["全部單字"] + sorted(df_vocab_game['unit_tag'].dropna().unique().tolist())
        selected_game_unit = st.selectbox("選擇遊戲挑戰的單元範圍：", unit_list_game, key="game_unit_select")
        
        df_filtered_game = df_vocab_game if selected_game_unit == "全部單字" else df_vocab_game[df_vocab_game['unit_tag'] == selected_game_unit]
        
        if df_filtered_game.empty:
            st.warning("📭 該分類中沒有單字！")
        else:
            game_mode = st.radio("選擇挑戰模式：", ["🟢 經典單字挑戰 (考卷填空克漏字 + 單字發音)", "🔴 進階盲拼挑戰 (聽中文定義發音 + 打單字)"], horizontal=True)

            if "game_errors" not in st.session_state:
                st.session_state.game_errors = 0
            
            if "completed_words" not in st.session_state or st.session_state.get("game_scope_lock") != selected_game_unit:
                st.session_state.game_scope_lock = selected_game_unit
                st.session_state.completed_words = []
                if "current_game_item" in st.session_state:
                    del st.session_state["current_game_item"]

            available_df = df_filtered_game[~df_filtered_game['word'].isin(st.session_state.completed_words)]
            
            if available_df.empty:
                st.balloons()
                st.success(f"🎉 太棒了！您已經把 【{selected_game_unit}】 裡的單字全部練習過一輪了！")
                if st.button("🔄 重新挑戰本單元", type="primary"):
                    st.session_state.completed_words = []
                    if "current_game_item" in st.session_state:
                        del st.session_state["current_game_item"]
                    st.rerun()
            else:
                if "current_game_item" not in st.session_state:
                    row = available_df.sample(1).iloc[0]
                    w = str(row['word']).strip()
                    b_s = clean_sentence(row.get('basic_sentence', ''))
                    
                    if not b_s or w.lower() not in b_s.lower():
                        b_s = fetch_real_dictionary_sentence(w)

                    word_audio = generate_audio_bytes(w, lang='en')
                    
                    st.session_state.current_game_item = {
                        "word": w,
                        "definition": row.get('definition', ''),
                        "unit_tag": row.get('unit_tag', ''),
                        "basic_sentence": b_s,
                        "audio_bytes": word_audio
                    }

                item = st.session_state.current_game_item
                word_str = item["word"]
                hint_masked = "".join([" _ " if c.isalpha() else "   " for c in word_str])
                
                with st.container(border=True):
                    st.markdown(f"### ❌ 累積答錯題數：`{st.session_state.game_errors} 次` &nbsp;|&nbsp; 🏷️ {item['unit_tag']} &nbsp;|&nbsp; 📊 本輪剩餘：`{len(available_df)} 題`")
                    
                    # 模式一：經典單字挑戰 (考卷填空克漏字)
                    if "經典" in game_mode:
                        masked_basic = re.sub(re.escape(word_str), '______', item['basic_sentence'], flags=re.IGNORECASE)
                        
                        st.markdown(f"**📖 考卷填空題 (Context Sentence)：**")
                        st.markdown(f"> ### {masked_basic}")
                        
                        col_a1, col_a2 = st.columns([1, 4])
                        with col_a1:
                            st.markdown("<div style='margin-top: 15px;'>**🔊 單字發音 (Pronunciation)：**</div>", unsafe_allow_html=True)
                        with col_a2:
                            try:
                                st.audio(item["audio_bytes"], format="audio/mp3")
                            except Exception:
                                st.warning("發音載入失敗。")
                                
                    # 模式二：進階盲拼挑戰
                    else:
                        st.markdown("### 🎧 Listen to the pronunciation and spell the word based on its definition!")
                        st.markdown(f"**📌 中文釋義提示：** `{item['definition']}`")
                        
                        col_a1, col_a2 = st.columns([1, 4])
                        with col_a1:
                            st.markdown("<div style='margin-top: 15px;'>**🔊 Audio Prompt：**</div>", unsafe_allow_html=True)
                        with col_a2:
                            try:
                                st.audio(item["audio_bytes"], format="audio/mp3")
                            except Exception:
                                st.warning("發音載入失敗。")

                    st.markdown(f"**🔤 拼字提示 (Spelling Hint)：** `{hint_masked}` &nbsp;&nbsp; (Length: {len(word_str)} letters)")

                user_guess = st.text_input("Enter your spelling answer:", key="game_input_box").strip().lower()
                
                col_g1, col_g2 = st.columns(2)
                with col_g1:
                    submit_guess = st.button("🚀 Submit Answer", type="primary", use_container_width=True)
                with col_g2:
                    skip_question = st.button("🔄 Next Question", use_container_width=True)

                if submit_guess:
                    if user_guess == word_str.lower():
                        st.success(f"🎉 Correct! Excellent job! The word is **{word_str}**")
                        if word_str not in st.session_state.completed_words:
                            st.session_state.completed_words.append(word_str)
                        time.sleep(0.8)
                        if "current_game_item" in st.session_state:
                            del st.session_state["current_game_item"]
                        st.rerun()
                    else:
                        st.session_state.game_errors += 1
                        st.error("❌ Incorrect! Try again, you can do it!")

                if skip_question:
                    if "current_game_item" in st.session_state:
                        del st.session_state["current_game_item"]
                    st.rerun()