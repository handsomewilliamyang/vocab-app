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

# 導入發音所需套件
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
# 1. 側邊欄導覽與級別切換（字體放大優化）
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
# 2. 簡繁轉換對照字典與強制清洗機制
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

OFFLINE_DICT = {
    "house": {"word": "house", "phonetic": "/haʊs/", "part_of_speech": "n.", "definition": "房子；住宅", "basic_sentence": "They live in a large house near the park.", "advanced_sentence": "He bought a new house last year.", "collocations": "build a house"},
    "enough": {"word": "enough", "phonetic": "/ɪˈnʌf/", "part_of_speech": "adj. / adv. / pron.", "definition": "足夠的；充分地", "basic_sentence": "We have enough time to finish the project.", "advanced_sentence": "She didn't sleep enough last night.", "collocations": "enough time"},
    "but": {"word": "but", "phonetic": "/bʌt/", "part_of_speech": "conj. / prep.", "definition": "但是；除了", "basic_sentence": "I wanted to go, but I was too tired.", "advanced_sentence": "Everyone passed the exam except for him.", "collocations": "not only... but also..."},
    "neither": {"word": "neither", "phonetic": "/ˈniːðər/", "part_of_speech": "adv. / conj. / pron.", "definition": "兩者都不；也不", "basic_sentence": "Neither of them came to the party.", "advanced_sentence": "She doesn't like spicy food, and neither do I.", "collocations": "neither... nor..."},
    "either": {"word": "either", "phonetic": "/ˈiːðər/", "part_of_speech": "adv. / conj.", "definition": "也（用於否定句）；或者", "basic_sentence": "I don't like apples, and he doesn't like them either.", "advanced_sentence": "You may choose either option.", "collocations": "either... or..."},
    "north": {"word": "north", "phonetic": "/nɔːrθ/", "part_of_speech": "n. / adj.", "definition": "北方；向北方", "basic_sentence": "Birds fly to the north in spring.", "advanced_sentence": "The town is situated ten miles to the north.", "collocations": "in the north"},
    "south": {"word": "south", "phonetic": "/saʊθ/", "part_of_speech": "n. / adj.", "definition": "南方；向南方", "basic_sentence": "They traveled toward the south.", "advanced_sentence": "The climate in the south is warmer.", "collocations": "in the south"},
    "east": {"word": "east", "phonetic": "/iːst/", "part_of_speech": "n. / adj.", "definition": "東方；向東方", "basic_sentence": "The sun rises in the east.", "advanced_sentence": "We drove east for two hours.", "collocations": "in the east"},
    "west": {"word": "west", "phonetic": "/west/", "part_of_speech": "n. / adj.", "definition": "西方；向西方", "basic_sentence": "The sun sets in the west.", "advanced_sentence": "They live on the west side of the city.", "collocations": "in the west"},
    "school": {"word": "school", "phonetic": "/skuːl/", "part_of_speech": "n.", "definition": "學校", "basic_sentence": "She goes to school by bus.", "advanced_sentence": "The school provides excellent programs.", "collocations": "go to school"},
    "teacher": {"word": "teacher", "phonetic": "/ˈtiːtʃər/", "part_of_speech": "n.", "definition": "老師", "basic_sentence": "Mr. Smith is our English teacher.", "advanced_sentence": "A good teacher inspires students.", "collocations": "classroom teacher"},
    "student": {"word": "student", "phonetic": "/ˈstuːdnt/", "part_of_speech": "n.", "definition": "學生", "basic_sentence": "He is a hard-working student.", "advanced_sentence": "University students work part-time.", "collocations": "exchange student"},
    "friend": {"word": "friend", "phonetic": "/frend/", "part_of_speech": "n.", "definition": "朋友", "basic_sentence": "She is my best friend.", "advanced_sentence": "A true friend stands by you.", "collocations": "close friend"},
    "happy": {"word": "happy", "phonetic": "/ˈhæpi/", "part_of_speech": "adj.", "definition": "快樂的", "basic_sentence": "I am happy to see you.", "advanced_sentence": "She looked extremely happy.", "collocations": "happy ending"},
    "grade": {"word": "grade", "phonetic": "/ɡreɪd/", "part_of_speech": "n.", "definition": "成績；年級", "basic_sentence": "She got a good grade on the test.", "advanced_sentence": "He is in the eighth grade.", "collocations": "get a grade"},
    "class": {"word": "class", "phonetic": "/klæs/", "part_of_speech": "n.", "definition": "班級；課", "basic_sentence": "Our class has thirty students.", "advanced_sentence": "We have an English class.", "collocations": "in class"},
    "test": {"word": "test", "phonetic": "/test/", "part_of_speech": "n. / v.", "definition": "考試；測試", "basic_sentence": "We will have a math test tomorrow.", "advanced_sentence": "The teacher tested our knowledge.", "collocations": "take a test"},
    "study": {"word": "study", "phonetic": "/ˈstʌdi/", "part_of_speech": "v. / n.", "definition": "讀書；學習", "basic_sentence": "She studies English every day.", "advanced_sentence": "His study on behavior was published.", "collocations": "study hard"},
    "each other": {"word": "each other", "phonetic": "/iːtʃ ˈʌðər/", "part_of_speech": "pron.", "definition": "互相；彼此", "basic_sentence": "They looked at each other and smiled.", "advanced_sentence": "Good friends should help each other.", "collocations": "talk to each other"}
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
    bad_prefixes = ['實用單字： ', '核心單字： ', '實用字彙： ', '核心字彙： ', '實用單字：', '核心單字：', '實用字彙：', '核心字彙：', '實用單字: ', '核心單字: ', '實用單字:', '核心單字:']
    for p in bad_prefixes:
        c.execute("UPDATE vocab SET definition = REPLACE(definition, ?, '')", (p,))
    
    c.execute("SELECT id, word, definition FROM vocab")
    rows = c.fetchall()
    for row_id, w_text, def_text in rows:
        if def_text:
            cleaned_def = re.sub(r'^[a-zA-Z\s\-\,\.]+\s+', '', def_text)
            cleaned_def = simple_s2t_convert(cleaned_def)
            if cleaned_def != def_text and re.search(r'[\u4e00-\u9fa5]', cleaned_def):
                c.execute("UPDATE vocab SET definition = ? WHERE id = ?", (cleaned_def, row_id))

    for w_key, data in OFFLINE_DICT.items():
        c.execute("UPDATE vocab SET phonetic=?, part_of_speech=?, definition=?, basic_sentence=? WHERE LOWER(TRIM(word))=?", (data['phonetic'], data['part_of_speech'], data['definition'], data['basic_sentence'], w_key.lower()))
    conn.commit()
    conn.close()

init_db(current_db_name)
clean_legacy_data(current_db_name)

# -------------------------------------------------------------------------
# 3. 核心工具函式（串接真實字典 API 與自然例句）
# -------------------------------------------------------------------------
def clean_sentence(text):
    if not text:
        return ""
    text = re.sub(r'\s*\(.*?\)', '', text)
    return text.strip()

def auto_translate_english_to_chinese(word):
    w_lower = word.strip().lower()
    if w_lower in OFFLINE_DICT:
        return OFFLINE_DICT[w_lower]['definition']

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

def fetch_real_dictionary_data(word):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    
    if w_lower in OFFLINE_DICT:
        return OFFLINE_DICT[w_lower]

    translated_zh = auto_translate_english_to_chinese(w_clean)
    
    # 💡 利用開源線上字典 API 抓取真實英文例句
    real_basic = f"We can see {w_clean} used in everyday communication."
    real_adv = f"It is essential to understand how {w_clean} functions in context."
    
    try:
        dict_url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(w_clean)}"
        req = urllib.request.Request(dict_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as response:
            dict_data = json.loads(response.read().decode('utf-8'))
            if isinstance(dict_data, list) and len(dict_data) > 0:
                meanings = dict_data[0].get('meanings', [])
                if meanings:
                    first_meaning = meanings[0]
                    pos = first_meaning.get('partOfSpeech', 'n.')
                    definitions = first_meaning.get('definitions', [])
                    if definitions:
                        for d_obj in definitions:
                            if 'example' in d_obj and d_obj['example']:
                                real_basic = d_obj['example']
                                break
                        if len(definitions) > 1 and 'example' in definitions[1] and definitions[1]['example']:
                            real_adv = definitions[1]['example']
                    
                    phonetics = dict_data[0].get('phonetics', [])
                    phonetic_text = f"/{w_lower}/"
                    for p in phonetics:
                        if 'text' in p:
                            phonetic_text = p['text']
                            break
                            
                    return {
                        "word": w_clean,
                        "phonetic": phonetic_text,
                        "part_of_speech": f"{pos}.",
                        "definition": simple_s2t_convert(translated_zh),
                        "basic_sentence": real_basic,
                        "advanced_sentence": real_adv,
                        "collocations": f"common {w_clean}"
                    }
    except Exception:
        pass

    return {
        "word": w_clean,
        "phonetic": f"/{w_lower}/",
        "part_of_speech": "n. / v.",
        "definition": simple_s2t_convert(translated_zh),
        "basic_sentence": f"They often talk about {w_clean} in daily life.",
        "advanced_sentence": f"Understanding {w_clean} is very helpful for learners.",
        "collocations": f"practice {w_clean}"
    }

def update_single_word_in_db(db_name, word_id, new_word, new_phonetic, new_pos, new_def, new_basic, new_adv, new_coll):
    conn = sqlite3.connect(db_name)
    c = conn.cursor()
    try:
        c.execute("SELECT id FROM vocab WHERE LOWER(TRIM(word)) = LOWER(TRIM(?)) AND id != ?", (new_word, word_id))
        if c.fetchone():
            return False, "該英文單字已存在於資料庫中，請勿重複建立！"

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
                word_data = fetch_real_dictionary_data(single_word.strip())
                if word_data:
                    if upsert_word_to_db(word_data, current_db_name, current_unit_tag):
                        st.success(f"🎉 成功新增單字：{single_word} 至 【{current_unit_tag}】")
                        st.json(word_data)
                    else:
                        st.error("❌ 寫入資料庫失敗！")

    with col_input2:
        st.subheader("📂 檔案與智慧匯入（支援多檔案複選）")
        import_mode = st.radio("選擇匯入來源：", ["CSV 檔案", "Word 檔案 (.docx)"], horizontal=True)
        
        if import_mode == "Word 檔案 (.docx)":
            uploaded_docxs = st.file_uploader("上傳 Word 講義檔案（可同時選取多個）", type=["docx"], accept_multiple_files=True)
            if uploaded_docxs:
                st.info(f"📁 已載入 {len(uploaded_docxs)} 個檔案，確認匯入單元為：**{current_unit_tag}**")
                if st.button("📖 解析所有 Word 並智慧批次匯入", use_container_width=True):
                    total_success_count = 0
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    all_extracted_words = []
                    for uploaded_docx in uploaded_docxs:
                        temp_path = f"temp_{uploaded_docx.name}"
                        try:
                            with open(temp_path, "wb") as f:
                                f.write(uploaded_docx.getbuffer())
                                
                            doc = docx.Document(temp_path)
                            
                            def is_valid_vocab(text):
                                t = text.strip()
                                if not t or len(t) > 35:
                                    return False
                                if re.search(r'[\u4e00-\u9fa5]', t):
                                    return False
                                if t.lower() in ['n.', 'v.', 'adj.', 'adv.', 'prep.', 'conj.', 'pron.', 'phr.', 'vi.', 'vt.']:
                                    return False
                                if not re.match(r'^[a-zA-Z\s\-\'\.]+$', t):
                                    return False
                                return True

                            for table in doc.tables:
                                for row in table.rows:
                                    for cell in row.cells:
                                        text = cell.text.strip()
                                        if text:
                                            for line in text.split('\n'):
                                                cleaned = re.sub(r'^\d+[\.、\s]*', '', line).strip()
                                                if is_valid_vocab(cleaned) and cleaned not in all_extracted_words:
                                                    all_extracted_words.append(cleaned)
                                                    
                            for para in doc.paragraphs:
                                text = para.text.strip()
                                if text:
                                    cleaned = re.sub(r'^\d+[\.、\s]*', '', text).strip()
                                    if is_valid_vocab(cleaned) and cleaned not in all_extracted_words:
                                        all_extracted_words.append(cleaned)
                                        
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                        except Exception as e:
                            if os.path.exists(temp_path):
                                os.remove(temp_path)

                    if len(all_extracted_words) > 0:
                        st.success(f"✅ 解析成功！所有檔案共萃取出 {len(all_extracted_words)} 個不重複單字，開始批次串接字典並建檔...")
                        for i, w in enumerate(all_extracted_words):
                            status_text.text(f"⏳ 正在串接線上字典與自動翻譯 ({i+1}/{len(all_extracted_words)}): {w}")
                            w_data = fetch_real_dictionary_data(w)
                            if w_data:
                                if upsert_word_to_db(w_data, current_db_name, current_unit_tag):
                                    total_success_count += 1
                            progress_bar.progress((i + 1) / len(all_extracted_words))
                            time.sleep(0.3)
                            
                        status_text.empty()
                        st.success(f"🎊 多檔案批次匯入大功告成！成功匯入 {total_success_count} 個單字至 【{current_unit_tag}】。")
                    else:
                        st.warning("⚠️ 上傳的 Word 檔案中沒有找到可辨識的英文單字。")

elif main_menu == "📖 字庫管理與搜尋":
    df_vocab = get_vocab_by_db(current_db_name)
    
    if df_vocab.empty:
        st.info("📭 目前尚無單字，請至側邊欄「✨ 智慧單字新增」分頁新增！")
    else:
        unit_list = sorted(df_vocab['unit_tag'].dropna().unique().tolist())
        unit_list.append("全部單字")
        
        col_top_f1, col_top_f2 = st.columns([1.5, 1])
        with col_top_f1:
            selected_unit_filter = st.selectbox("依學習單元篩選：", unit_list)
        with col_top_f2:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            if st.button("🔄 重新整理與自動修復中文與例句", type="primary", use_container_width=True):
                conn = sqlite3.connect(current_db_name)
                c = conn.cursor()
                c.execute("SELECT id, word, definition FROM vocab")
                all_rows = c.fetchall()
                conn.close()
                
                missing_or_bad = []
                for r_id, r_word, r_def in all_rows:
                    if not r_def or r_def.lower() == r_word.lower() or '待補充' in r_def or '翻譯失敗' in r_def or re.match(r'^[a-zA-Z]', r_def) or any(s in r_def for s in S2T_DICT.keys()):
                        missing_or_bad.append((r_id, r_word))
                
                if not missing_or_bad:
                    st.success("✅ 檢查完畢，清單已重新整理，所有單字的資料都很健康！")
                    time.sleep(0.8)
                    st.rerun()
                else:
                    progress_bar = st.progress(0)
                    status = st.empty()
                    for i, row in enumerate(missing_or_bad):
                        word_id, w_text = row
                        status.text(f"⏳ 正在重新串接字典與翻譯: {w_text} ...")
                        w_data = fetch_real_dictionary_data(w_text)
                        update_single_word_in_db(
                            current_db_name, word_id, w_text, 
                            w_data['phonetic'], w_data['part_of_speech'], w_data['definition'], 
                            w_data['basic_sentence'], w_data['advanced_sentence'], w_data['collocations']
                        )
                        progress_bar.progress((i + 1) / len(missing_or_bad))
                        time.sleep(0.3)
                    status.empty()
                    st.success(f"🎊 重新整理與修復完成！已成功更新 {len(missing_or_bad)} 個單字！")
                    time.sleep(1)
                    st.rerun()
        
        filtered_df = df_vocab if selected_unit_filter == "全部單字" else df_vocab[df_vocab['unit_tag'] == selected_unit_filter]

        col_s1, col_s2 = st.columns([2, 1])
        with col_s1:
            search_query = st.text_input("🔍 搜尋單字或釋義：", placeholder="輸入關鍵字...")
        with col_s2:
            words_to_delete = st.multiselect("🗑️ 勾選要刪除的單字：", filtered_df['word'].tolist(), placeholder="選擇單字...")

        if search_query:
            mask = filtered_df['word'].str.contains(search_query, case=False, na=False) | filtered_df['definition'].str.contains(search_query, case=False, na=False)
            filtered_df = filtered_df[mask]
            
        if words_to_delete:
            if st.button("⚠️ 確認刪除已勾選的單字", type="primary"):
                delete_words_from_db(current_db_name, words_to_delete)
                st.success("已成功刪除勾選的單字！")
                st.rerun()
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        with st.expander("📋 點擊收合/展開：單字總表與快速編輯區", expanded=True):
            display_df = filtered_df.copy()
            display_df.insert(0, '編號', range(1, len(display_df) + 1))
            display_columns = ['編號', 'word', 'phonetic', 'part_of_speech', 'definition']
            
            st.dataframe(
                display_df[display_columns], 
                use_container_width=True, 
                hide_index=True,
                column_config={
                    "編號": st.column_config.NumberColumn(
                        "編號",
                        width="small"
                    )
                }
            )
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            with st.container(border=True):
                st.markdown("#### ✏️ 單字快速編輯修正")
                st.caption("💡 提示：點擊下方輸入框後，可直接輸入英文單字進行即時搜尋與過濾！")
                
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
                            edit_basic = st.text_area("基礎例句 (Basic Sentence)", value=target_row.get('basic_sentence', ''), key=f"bs_{target_row['id']}")
                            edit_adv = st.text_area("進階例句 (Advanced Sentence)", value=target_row.get('advanced_sentence', ''), key=f"as_{target_row['id']}")
                            edit_coll = st.text_input("常見搭配詞 (Collocations)", value=target_row.get('collocations', ''), key=f"c_{target_row['id']}")
                            
                            submit_table_edit = st.form_submit_button("💾 確認儲存該單字修改", type="primary")
                            
                            if submit_table_edit:
                                success, msg = update_single_word_in_db(
                                    current_db_name, 
                                    target_row['id'], 
                                    edit_word, edit_phonetic, edit_pos, edit_def, edit_basic, edit_adv, edit_coll
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
        st.warning("📭 目前沒有單字可以進行閃卡練習，請先至側邊欄新增單字！")
    else:
        unit_list_flash = ["全部單字"] + sorted(df_vocab_flash['unit_tag'].dropna().unique().tolist())
        selected_flash_unit = st.selectbox("選擇要複習的單元範圍：", unit_list_flash, key="flash_unit_select")
        
        df_vocab_flash = df_vocab_flash if selected_flash_unit == "全部單字" else df_vocab_flash[df_vocab_flash['unit_tag'] == selected_flash_unit]
            
        if df_vocab_flash.empty:
            st.warning("📭 該分類中沒有單字！")
        else:
            if "flashcard_index" not in st.session_state:
                st.session_state.flashcard_index = 0
                
            total_count = len(df_vocab_flash)
            st.session_state.flashcard_index = st.session_state.flashcard_index % total_count
            current_idx = st.session_state.flashcard_index
            
            row = df_vocab_flash.iloc[current_idx]
            
            with st.container(border=True):
                st.markdown(f"<p style='text-align: right; color: gray;'>CARD {current_idx + 1} OF {total_count} &nbsp;|&nbsp; 🏷️ {row.get('unit_tag', '未分類')}</p>", unsafe_allow_html=True)
                st.markdown(f"<h1 style='text-align: center; font-size: 54px; margin: 10px 0;'>🔤 {row['word']}</h1>", unsafe_allow_html=True)
                st.markdown(f"<p style='text-align: center; color: gray; font-size: 20px;'>{row['phonetic']} &nbsp;|&nbsp; {row['part_of_speech']}</p>", unsafe_allow_html=True)
            
            with st.expander("💡 點擊展開詳細釋義與例句解析", expanded=True):
                st.markdown(f"### 📌 核心釋義：\n> **{row['definition']}**")
                st.markdown(f"### 📖 基礎例句：\n{clean_sentence(row['basic_sentence'])}")
                st.markdown(f"### 🌟 進階例句：\n{clean_sentence(row['advanced_sentence'])}")
                st.markdown(f"### 🔗 常見搭配詞：\n`{row['collocations']}`")
                
            st.markdown("<br>", unsafe_allow_html=True)
            col_prev, col_mid, col_next = st.columns([1, 2, 1])
            with col_prev:
                if st.button("⬅️ 上一個單字", use_container_width=True):
                    st.session_state.flashcard_index = (st.session_state.flashcard_index - 1) % total_count
                    st.rerun()
            with col_mid:
                st.markdown(f"<div style='text-align: center; padding-top: 10px; font-weight: bold;'>學習進度：{current_idx + 1} / {total_count}</div>", unsafe_allow_html=True)
            with col_next:
                if st.button("➡️ 下一個單字", use_container_width=True):
                    st.session_state.flashcard_index = (st.session_state.flashcard_index + 1) % total_count
                    st.rerun()

elif main_menu == "🎮 拼字王挑戰遊戲":
    df_vocab_game = get_vocab_by_db(current_db_name)
    
    if df_vocab_game.empty:
        st.warning("📭 目前沒有足夠的單字來進行遊戲，請先至側邊欄新增單字！")
    else:
        unit_list_game = ["全部單字"] + sorted(df_vocab_game['unit_tag'].dropna().unique().tolist())
        selected_game_unit = st.selectbox("選擇遊戲挑戰的單元範圍：", unit_list_game, key="game_unit_select")
        
        df_vocab_game = df_vocab_game if selected_game_unit == "全部單字" else df_vocab_game[df_vocab_game['unit_tag'] == selected_game_unit]
            
        if df_vocab_game.empty:
            st.warning("📭 該分類中沒有單字！")
        else:
            game_mode = st.radio("選擇挑戰模式：", ["🟢 經典單字挑戰 (真實字典克漏字 + 發音)", "🔴 進階盲拼挑戰 (聽真實字典英文解釋 + 打單字)"], horizontal=True)

            if "game_errors" not in st.session_state:
                st.session_state.game_errors = 0

            # 💡 絕對嚴格鎖定：確保每次抽出的當前題目、真實字典例句、單字完全對應
            if "game_word_lock" not in st.session_state or st.session_state.get("game_scope_lock") != selected_game_unit:
                st.session_state.game_scope_lock = selected_game_unit
                row = df_vocab_game.sample(1).iloc[0]
                w = str(row['word']).strip()
                
                db_b = clean_sentence(row.get('basic_sentence', ''))
                # 如果資料庫裡剛好沒有有效例句，現場即時呼叫真實字典補充
                if not db_b or w.lower() not in db_b.lower():
                    fresh_data = fetch_real_dictionary_data(w)
                    active_b = fresh_data['basic_sentence']
                    active_a = fresh_data['advanced_sentence']
                else:
                    active_b = db_b
                    active_a = clean_sentence(row.get('advanced_sentence', f"Context for {w}."))

                st.session_state.game_word_lock = w
                st.session_state.game_row_lock = row
                st.session_state.game_basic_lock = active_b
                st.session_state.game_adv_lock = active_a

            target = st.session_state.game_row_lock
            word_str = st.session_state.game_word_lock
            hint_masked = "".join([" _ " if c.isalpha() else "   " for c in word_str])
            
            with st.container(border=True):
                st.markdown(f"### ❌ 累積答錯題數：`{st.session_state.game_errors} 次` &nbsp;|&nbsp; 🏷️ {target.get('unit_tag', '')}")
                
                # 模式一：經典單字挑戰 (真實字典克漏字 + 發音)
                if "經典" in game_mode:
                    # 使用正規表達式不分大小寫將句子中的單字挖空
                    masked_basic_game = re.sub(re.escape(word_str), '______', st.session_state.game_basic_lock, flags=re.IGNORECASE)
                    if masked_basic_game == st.session_state.game_basic_lock:
                        # 若句子剛好沒直接包含該字串（例如時態變化），則直接顯示該句並在下方提示
                        masked_basic_game = f"{st.session_state.game_basic_lock} (Target word meaning: {target.get('definition', '')})"
                        
                    st.markdown(f"**📖 Dictionary Context Sentence：** {masked_basic_game}")
                    
                    col_a1, col_a2 = st.columns([1, 4])
                    with col_a1:
                        st.markdown("<div style='margin-top: 15px;'>**🔊 Pronunciation：**</div>", unsafe_allow_html=True)
                    with col_a2:
                        try:
                            audio_bytes = generate_audio_bytes(word_str, lang='en')
                            st.audio(audio_bytes, format="audio/mp3")
                        except Exception:
                            st.warning("發音載入失敗，請確認網路連線。")
                            
                # 模式二：進階盲拼挑戰 (聽真實字典英文解釋 + 打單字)
                else:
                    st.markdown("### 🎧 Listen to the dictionary definition and spell the word!")
                    st.markdown(f"**📌 Dictionary Explanation：** {st.session_state.game_adv_lock}")
                    
                    col_a1, col_a2 = st.columns([1, 4])
                    with col_a1:
                        st.markdown("<div style='margin-top: 15px;'>**🔊 Audio Prompt：**</div>", unsafe_allow_html=True)
                    with col_a2:
                        try:
                            audio_bytes = generate_audio_bytes(st.session_state.game_adv_lock, lang='en')
                            st.audio(audio_bytes, format="audio/mp3")
                        except Exception:
                            st.warning("發音載入失敗，請確認網路連線。")

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
                    for k in ['game_word_lock', 'game_row_lock', 'game_basic_lock', 'game_adv_lock']:
                        if k in st.session_state:
                            del st.session_state[k]
                    st.rerun()
                else:
                    st.session_state.game_errors += 1
                    st.error("❌ Incorrect! Try again, you can do it!")

            if skip_question:
                for k in ['game_word_lock', 'game_row_lock', 'game_basic_lock', 'game_adv_lock']:
                    if k in st.session_state:
                        del st.session_state[k]
                st.rerun()