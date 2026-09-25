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

# 嘗試載入 Gemini 套件
try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

# -------------------------------------------------------------------------
# 0. 頁面全域設定
# -------------------------------------------------------------------------
st.set_page_config(
    page_title="我愛背單字 (AI 強化版)",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -------------------------------------------------------------------------
# 1. 側邊欄導覽與設定
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
st.sidebar.markdown("<h3 style='font-size: 20px;'>🤖 AI 例句生成引擎 (Gemini)</h3>", unsafe_allow_html=True)
if HAS_GEMINI:
    gemini_key = st.sidebar.text_input("輸入 Gemini API Key (選填)", type="password", value=st.session_state.get("gemini_api_key", ""))
    st.session_state.gemini_api_key = gemini_key
    if gemini_key:
        st.sidebar.success("✅ AI 引擎已啟用！將為您生成完美例句。")
    else:
        st.sidebar.info("💡 貼上 API Key 即可啟動 AI 自動造句，否則將使用免費字典。")
else:
    st.sidebar.warning("⚠️ 請在終端機輸入 `pip install google-generativeai` 來啟用 Gemini AI 造句功能！")


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
# 3. 核心工具函式（Gemini AI + 字典 API 雙引擎）
# -------------------------------------------------------------------------
def clean_sentence(text):
    if not text:
        return ""
    text = re.sub(r'\s*\(.*?\)', '', str(text)).strip()
    bad_phrases = ["example sentence using", "we can easily see how", "people frequently use", "this is an example"]
    if any(bp in text.lower() for bp in bad_phrases):
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

def fetch_sentence(word):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    search_root = w_lower[:4] if len(w_lower) >= 4 else w_lower

    # 1. 嘗試使用 Gemini API (如果有輸入 Key)
    if HAS_GEMINI and st.session_state.get('gemini_api_key'):
        try:
            genai.configure(api_key=st.session_state.gemini_api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"Write a single, practical, everyday English sentence using the word '{w_clean}'. Return ONLY the English sentence. Do not include quotes, translations, or any other text."
            response = model.generate_content(prompt)
            if response.text:
                clean_res = response.text.strip().replace('"', '').replace('\n', '')
                if search_root in clean_res.lower():
                    return clean_res
        except Exception as e:
            pass # 如果 Gemini 失敗或逾時，默默掉下去用免費字典

    # 2. 備用方案：免費字典 API
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
                                if search_root in ex.lower():
                                    return ex
    except Exception:
        pass
    
    # 3. 如果連免費字典都找不到，就真的回傳空白，絕不生假句子
    return ""

def get_word_record_data(word):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    translated_zh = auto_translate_english_to_chinese(w_clean)
    real_sent = fetch_sentence(w_clean)
    
    return {
        "word": w_clean,
        "phonetic": f"/{w_lower}/",
        "part_of_speech": "n. / v.",
        "definition": simple_s2t_convert(translated_zh),
        "basic_sentence": real_sent,
        "advanced_sentence": "",
        "collocations": f"practice {w_clean}"
    }

def update_single_word_in_db(db_name, word_id, new_word, new_phonetic, new_pos, new_def, new_basic, new_adv, new_coll):
    conn = sqlite3.connect(db_name)
    c = conn.cursor()
    try:
        b_sent = clean_sentence(new_basic)
        c.execute('''
            UPDATE vocab 
            SET word=?, phonetic=?, part_of_speech=?, definition=?, basic_sentence=?, advanced_sentence=?, collocations=?
            WHERE id=?
        ''', (new_word, new_phonetic, new_pos, simple_s2t_convert(new_def), b_sent, new_adv, new_coll, word_id))
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
            clean_def = auto_translate_english_to_chinese(word)

        b_sent = clean_sentence(data.get('basic_sentence'))
        search_root = word.lower()[:4] if len(word) >= 4 else word.lower()
        if not b_sent or search_root not in b_sent.lower():
            b_sent = fetch_sentence(word)

        c.execute("SELECT id FROM vocab WHERE word = ?", (word,))
        row = c.fetchone()
        
        if row:
            c.execute('''
                UPDATE vocab 
                SET phonetic=?, part_of_speech=?, definition=?, basic_sentence=?, collocations=?, unit_tag=?
                WHERE word=?
            ''', (
                data.get('phonetic'), data.get('part_of_speech'), clean_def,
                b_sent, data.get('collocations'), unit_tag, word
            ))
        else:
            c.execute('''
                INSERT INTO vocab (word, phonetic, part_of_speech, definition, basic_sentence, collocations, unit_tag)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                word, data.get('phonetic'), data.get('part_of_speech'), clean_def,
                b_sent, data.get('collocations'), unit_tag
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
st.title("📚 我愛背單字 (AI 強化版)")

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
                        if word_data['basic_sentence']:
                            st.success(f"🎉 成功新增單字：{single_word}（已自動產生真實例句）至 【{current_unit_tag}】")
                        else:
                            st.success(f"🎉 成功新增單字：{single_word} 至 【{current_unit_tag}】 (字典無例句，維持空白)")
                    else:
                        st.error("❌ 寫入資料庫失敗！")

    with col_input2:
        st.subheader("📂 檔案與智慧匯入")
        import_mode = st.radio("選擇匯入來源：", ["CSV 檔案", "Word 檔案 (.docx)"], horizontal=True)
        if import_mode == "Word 檔案 (.docx)":
            uploaded_docxs = st.file_uploader("上傳 Word 講義檔案", type=["docx"], accept_multiple_files=True)
            if uploaded_docxs:
                st.info(f"📁 已載入 {len(uploaded_docxs)} 個檔案，確認匯入單元為：**{current_unit_tag}**")
                if st.button("📖 解析所有 Word 並匯入", use_container_width=True):
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
        
        col_f1, col_f2 = st.columns([1.5, 1])
        with col_f1:
            selected_unit_filter = st.selectbox("依學習單元篩選：", unit_list)
        with col_f2:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            if st.button("🔄 掃描清除假例句 / 透過 AI 補抓翻譯與例句", type="primary", use_container_width=True):
                conn = sqlite3.connect(current_db_name)
                c = conn.cursor()
                c.execute("SELECT id, word, definition, basic_sentence FROM vocab")
                all_rows = c.fetchall()
                conn.close()
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                updated_count = 0
                
                for idx, row_item in enumerate(all_rows):
                    r_id, r_word, r_def, r_sent = row_item
                    needs_update = False
                    
                    clean_s = clean_sentence(r_sent)
                    search_root = r_word.lower()[:4] if len(r_word) >= 4 else r_word.lower()
                    
                    if not clean_s or search_root not in clean_s.lower():
                        clean_s = fetch_sentence(r_word)
                        if clean_s:
                            needs_update = True
                            
                    new_def = r_def
                    if not r_def or "(待補充" in r_def:
                        new_def = auto_translate_english_to_chinese(r_word)
                        if new_def != r_def:
                            needs_update = True
                            
                    if needs_update or clean_sentence(r_sent) != r_sent:
                        status_text.text(f"⏳ 正在修復: {r_word} ...")
                        update_single_word_in_db(
                            current_db_name, r_id, r_word, 
                            "", "", new_def, clean_s, "", ""
                        )
                        updated_count += 1
                        
                    progress_bar.progress((idx + 1) / len(all_rows))
                    time.sleep(0.05)
                
                status_text.empty()
                st.success(f"🎊 掃描完成！已清理與修復 {updated_count} 筆資料。")
                time.sleep(1)
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
                delete_words_from_db(current_db_name, words_to_delete)
                st.success("已成功刪除勾選的單字！")
                st.rerun()

        with st.expander("📋 單字總表與快速編輯", expanded=True):
            st.dataframe(filtered_df[['word', 'phonetic', 'part_of_speech', 'definition', 'basic_sentence', 'unit_tag']], use_container_width=True, hide_index=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            with st.container(border=True):
                st.markdown("#### ✏️ 單字快速編輯修正")
                st.caption("💡 提示：您可以在這裡手動修改任何單字內容。")
                
                if not filtered_df.empty:
                    word_options = {f"{row['word']} ({row['definition']})": row for _, row in filtered_df.iterrows()}
                    selected_option = st.selectbox("選擇要編輯的單字：", list(word_options.keys()), key="table_edit_select")
                    
                    if selected_option:
                        target_row = word_options[selected_option]
                        with st.form(key=f"table_edit_form_{target_row['id']}"):
                            col_e1, col_e2, col_e3 = st.columns(3)
                            with col_e1:
                                edit_word = st.text_input("單字 (Word)", value=target_row['word'], key=f"w_{target_row['id']}")
                            with col_e2:
                                edit_phonetic = st.text_input("音標 (Phonetic)", value=target_row.get('phonetic', ''), key=f"p_{target_row['id']}")
                            with col_e3:
                                edit_pos = st.text_input("詞性 (POS)", value=target_row.get('part_of_speech', ''), key=f"pos_{target_row['id']}")
                                
                            edit_def = st.text_input("中文釋義 (Definition)", value=target_row.get('definition', ''), key=f"d_{target_row['id']}")
                            edit_basic = st.text_area("真實例句 (Basic Sentence)", value=target_row.get('basic_sentence', ''), key=f"bs_{target_row['id']}")
                            
                            submit_table_edit = st.form_submit_button("💾 確認儲存該單字修改", type="primary")
                            
                            if submit_table_edit:
                                success, msg = update_single_word_in_db(
                                    current_db_name, 
                                    target_row['id'], 
                                    edit_word, edit_phonetic, edit_pos, edit_def, edit_basic, "", ""
                                )
                                if success:
                                    st.success("✅ 單字修改成功！")
                                    time.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error(f"❌ 修改失敗：{msg}")

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
            if display_sent:
                st.markdown(f"**例句：** {display_sent}")
            else:
                st.info("💡 此單字尚無有效例句，您可至字庫管理點擊一鍵修復，或手動補充。")
        
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
                        b_s = item['basic_sentence']
                        search_root = word_str.lower()[:4] if len(word_str) >= 4 else word_str.lower()
                        
                        can_cloze = False
                        if b_s and search_root in b_s.lower():
                            can_cloze = True
                            
                        if can_cloze:
                            pattern = re.compile(re.escape(word_str), re.IGNORECASE)
                            if pattern.search(b_s):
                                masked_basic = pattern.sub('______', b_s)
                            else:
                                root_pattern = re.compile(re.escape(search_root) + r'\w*', re.IGNORECASE)
                                masked_basic = root_pattern.sub('______', b_s)
                                
                            st.markdown(f"**📖 考卷填空題 (Context Sentence)：**")
                            st.markdown(f"> ### {masked_basic}")
                        else:
                            st.warning("⚠️ 此單字目前無有效例句，請直接依據下方「中文釋義」與「發音」作答。 (您可至「字庫管理」使用一鍵修復)")
                            st.markdown(f"**📌 中文釋義：** `{item['definition']}`")
                        
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