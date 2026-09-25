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
# 2. 簡繁轉換與核心單字庫
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

GOLDEN_WORD_DB = {
    "kitchen": {"word": "kitchen", "phonetic": "/ˈkɪtʃən/", "part_of_speech": "n.", "definition": "廚房", "basic_sentence": "Mom is cooking delicious dinner in the kitchen.", "advanced_sentence": "The kitchen was completely remodeled last month."},
    "parents": {"word": "parents", "phonetic": "/ˈpɛrənts/", "part_of_speech": "n.", "definition": "父母", "basic_sentence": "My parents always support my educational goals.", "advanced_sentence": "Both parents attended the school meeting."},
    "each other": {"word": "each other", "phonetic": "/iːtʃ ˈʌðər/", "part_of_speech": "pron.", "definition": "互相；彼此", "basic_sentence": "Good friends should always help each other.", "advanced_sentence": "They looked at each other with a warm smile."},
    "house": {"word": "house", "phonetic": "/haʊs/", "part_of_speech": "n.", "definition": "房子；住宅", "basic_sentence": "They live in a large house near the park.", "advanced_sentence": "He bought a new house last year."},
    "enough": {"word": "enough", "phonetic": "/ɪˈnʌf/", "part_of_speech": "adj. / adv. / pron.", "definition": "足夠的；充分地", "basic_sentence": "We have enough time to finish the project.", "advanced_sentence": "She didn't sleep enough last night."},
    "school": {"word": "school", "phonetic": "/skuːl/", "part_of_speech": "n.", "definition": "學校", "basic_sentence": "She goes to school by bus every morning.", "advanced_sentence": "The school provides excellent learning programs."},
    "teacher": {"word": "teacher", "phonetic": "/ˈtiːtʃər/", "part_of_speech": "n.", "definition": "老師", "basic_sentence": "Mr. Smith is our favorite English teacher.", "advanced_sentence": "A good teacher inspires students to think critically."},
    "student": {"word": "student", "phonetic": "/ˈstuːdnt/", "part_of_speech": "n.", "definition": "學生", "basic_sentence": "He is a very hard-working student.", "advanced_sentence": "University students often work part-time."},
    "friend": {"word": "friend", "phonetic": "/frend/", "part_of_speech": "n.", "definition": "朋友", "basic_sentence": "She is my best friend at school.", "advanced_sentence": "A true friend stands by you in hard times."}
}

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

def clean_legacy_data(db_name):
    conn = sqlite3.connect(db_name)
    c = conn.cursor()
    bad_prefixes = ['實用單字： ', '核心單字： ', '實用字彙： ', '核心字彙： ']
    for p in bad_prefixes:
        c.execute("UPDATE vocab SET definition = REPLACE(definition, ?, '')", (p,))
    conn.commit()
    conn.close()

init_db(current_db_name)
clean_legacy_data(current_db_name)

# -------------------------------------------------------------------------
# 3. 核心工具函式
# -------------------------------------------------------------------------
def clean_sentence(text):
    if not text:
        return ""
    text = re.sub(r'\s*\(.*?\)', '', text)
    return text.strip()

def auto_translate_english_to_chinese(word):
    w_lower = word.strip().lower()
    if w_lower in GOLDEN_WORD_DB:
        return GOLDEN_WORD_DB[w_lower]['definition']

    try:
        url = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(word)}&langpair=en|zh-TW"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            translated_text = data.get('responseData', {}).get('translatedText', word)
            translated_text = re.sub(r'^[a-zA-Z\s\-\,\.]+\s+', '', translated_text)
            translated_text = simple_s2t_convert(translated_text)
            if translated_text.lower() == word.lower() or not re.search(r'[\u4e00-\u9fa5]', translated_text):
                return "(待補充中文)"
            return translated_text
    except Exception:
        return "(待補充中文)"

def get_word_record_data(word):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    
    if w_lower in GOLDEN_WORD_DB:
        return GOLDEN_WORD_DB[w_lower]

    translated_zh = auto_translate_english_to_chinese(w_clean)
    
    return {
        "word": w_clean,
        "phonetic": f"/{w_lower}/",
        "part_of_speech": "n. / v.",
        "definition": simple_s2t_convert(translated_zh),
        "basic_sentence": f"This sentence helps practice the word {w_clean}.",
        "advanced_sentence": f"Advanced context for using {w_clean}.",
        "collocations": f"practice {w_clean}"
    }

def update_single_word_in_db(db_name, word_id, new_word, new_phonetic, new_pos, new_def, new_basic, new_adv, new_coll):
    conn = sqlite3.connect(db_name)
    c = conn.cursor()
    try:
        c.execute('''
            UPDATE vocab 
            SET word=?, phonetic=?, part_of_speech=?, definition=?, basic_sentence=?, advanced_sentence=?, collocations=?
            WHERE id=?
        ''', (new_word, new_phonetic, new_pos, simple_s2t_convert(new_def), new_basic, new_adv, new_coll, word_id))
        conn.commit()
        return True, "成功"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()

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

        c.execute("SELECT id FROM vocab WHERE word = ?", (word,))
        row = c.fetchone()
        
        if row:
            c.execute('''
                UPDATE vocab 
                SET phonetic=?, part_of_speech=?, definition=?, basic_sentence=?, advanced_sentence=?, collocations=?, unit_tag=?
                WHERE word=?
            ''', (
                data.get('phonetic'), data.get('part_of_speech'), clean_def,
                clean_sentence(data.get('basic_sentence')), clean_sentence(data.get('advanced_sentence')),
                data.get('collocations'), unit_tag, word
            ))
        else:
            c.execute('''
                INSERT INTO vocab (word, phonetic, part_of_speech, definition, basic_sentence, advanced_sentence, collocations, unit_tag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                word, data.get('phonetic'), data.get('part_of_speech'), clean_def,
                clean_sentence(data.get('basic_sentence')), clean_sentence(data.get('advanced_sentence')),
                data.get('collocations'), unit_tag
            ))
        conn.commit()
        success = True
    except Exception as e:
        success = False
    finally:
        conn.close()
    return success

def delete_words_from_db(db_name, word_list):
    if not word_list:
        return
    conn = sqlite3.connect(db_name)
    c = conn.cursor()
    c.executemany("DELETE FROM vocab WHERE word = ?", [(w,) for w in word_list])
    conn.commit()
    conn.close()

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
            st.dataframe(filtered_df[['word', 'phonetic', 'part_of_speech', 'definition', 'unit_tag']], use_container_width=True, hide_index=True)

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
        with st.expander("💡 詳細釋義", expanded=True):
            st.markdown(f"**中文釋義：** {row['definition']}")
            st.markdown(f"**基礎例句：** {clean_sentence(row['basic_sentence'])}")
        
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
        df_vocab_game = df_vocab_game if selected_game_unit == "全部單字" else df_vocab_game[df_vocab_game['unit_tag'] == selected_game_unit]
        
        if df_vocab_game.empty:
            st.warning("📭 該分類中沒有單字！")
        else:
            if "game_errors" not in st.session_state:
                st.session_state.game_errors = 0

            if "current_game_item" not in st.session_state or st.session_state.get("game_scope_lock") != selected_game_unit:
                st.session_state.game_scope_lock = selected_game_unit
                row = df_vocab_game.sample(1).iloc[0]
                w = str(row['word']).strip()
                w_lower = w.lower()
                
                # 嚴格過濾：如果資料庫的例句是假的或空的，直接採用純淨單字練習模式，絕不秀假句子
                db_b = clean_sentence(row.get('basic_sentence', ''))
                if not db_b or w_lower not in db_b.lower() or "example sentence using" in db_b.lower() or "this sentence helps" in db_b.lower():
                    if w_lower in GOLDEN_WORD_DB:
                        active_b = GOLDEN_WORD_DB[w_lower]['basic_sentence']
                    else:
                        active_b = "" # 沒好句子就保持空白，直接靠定義與發音猜題！
                else:
                    active_b = db_b

                word_audio = generate_audio_bytes(w, lang='en')
                
                st.session_state.current_game_item = {
                    "word": w,
                    "definition": row.get('definition', ''),
                    "unit_tag": row.get('unit_tag', ''),
                    "basic_sentence": active_b,
                    "audio_bytes": word_audio
                }

            item = st.session_state.current_game_item
            word_str = item["word"]
            hint_masked = "".join([" _ " if c.isalpha() else "   " for c in word_str])
            
            with st.container(border=True):
                st.markdown(f"### ❌ 累積答錯題數：`{st.session_state.game_errors} 次` &nbsp;|&nbsp; 🏷️ {item['unit_tag']}")
                st.markdown(f"**📌 中文釋義：** `{item['definition']}`")
                
                # 如果有真實好例句才顯示克漏字，否則乾脆不秀爛句子，避免干擾
                if item['basic_sentence']:
                    masked_basic = re.sub(re.escape(word_str), '______', item['basic_sentence'], flags=re.IGNORECASE)
                    st.markdown(f"**📖 Context Sentence：** {masked_basic}")
                else:
                    st.markdown(f"**📖 Challenge Mode：** Listen to the pronunciation and spell the word based on its Chinese definition.")
                
                col_a1, col_a2 = st.columns([1, 4])
                with col_a1:
                    st.markdown("<div style='margin-top: 15px;'>**🔊 Pronunciation：**</div>", unsafe_allow_html=True)
                with col_a2:
                    try:
                        st.audio(item["audio_bytes"], format="audio/mp3")
                    except Exception:
                        st.warning("發音載入失敗。")

                st.markdown(f"**🔤 Spelling Hint：** `{hint_masked}` &nbsp;&nbsp; (Length: {len(word_str)} letters)")

            user_guess = st.text_input("Enter your spelling answer:", key="game_input_box").strip().lower()
            
            col_g1, col_g2 = st.columns(2)
            with col_g1:
                submit_guess = st.button("🚀 Submit Answer", type="primary", use_container_width=True)
            with col_g2:
                skip_question = st.button("🔄 Next Question", use_container_width=True)

            if submit_guess:
                if user_guess == word_str.lower():
                    st.success(f"🎉 Correct! Excellent job! The word is **{word_str}**")
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