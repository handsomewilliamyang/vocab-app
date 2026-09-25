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
    "years old": {"word": "years old", "phonetic": "/jɪrz oʊld/", "part_of_speech": "adj.", "definition": "……歲的", "basic_sentence": "She is ten years old.", "advanced_sentence": "He started playing piano when he was five years old.", "collocations": "years old"},
    "husband": {"word": "husband", "phonetic": "/ˈhʌzbənd/", "part_of_speech": "n.", "definition": "丈夫", "basic_sentence": "Her husband is a doctor.", "advanced_sentence": "They celebrated their tenth wedding anniversary.", "collocations": "husband and wife"},
    "too": {"word": "too", "phonetic": "/tuː/", "part_of_speech": "adv.", "definition": "也；太", "basic_sentence": "I want to go to the park too.", "advanced_sentence": "The box is too heavy for me to lift.", "collocations": "too... to..."},
    "their": {"word": "their", "phonetic": "/ðer/", "part_of_speech": "pron.", "definition": "他們的", "basic_sentence": "The students are doing their homework.", "advanced_sentence": "They brought their children to the museum.", "collocations": "their own"},
    "determiner": {"word": "determiner", "phonetic": "/dɪˈtɜːrmɪnər/", "part_of_speech": "n.", "definition": "限定詞", "basic_sentence": "Words like 'the' and 'this' can function as determiners.", "advanced_sentence": "A determiner specifies the grammatical reference.", "collocations": "noun determiner"},
    "writer": {"word": "writer", "phonetic": "/ˈraɪtər/", "part_of_speech": "n.", "definition": "作家；作者", "basic_sentence": "She is a famous writer.", "advanced_sentence": "The writer published her first novel last year.", "collocations": "famous writer"},
    "son": {"word": "son", "phonetic": "/sʌn/", "part_of_speech": "n.", "definition": "兒子", "basic_sentence": "They have one son and two daughters.", "advanced_sentence": "His son plans to study engineering in college.", "collocations": "son and daughter"},
    "classmate": {"word": "classmate", "phonetic": "/ˈklæsmeɪt/", "part_of_speech": "n.", "definition": "同班同學", "basic_sentence": "He is my classmate in English class.", "advanced_sentence": "She often studies with her classmates after school.", "collocations": "high school classmate"},
    "junior high school": {"word": "junior high school", "phonetic": "/ˈdʒuːniər haɪ skuːl/", "part_of_speech": "n.", "definition": "國民中學", "basic_sentence": "He is a student at junior high school.", "advanced_sentence": "Students learn many new subjects in junior high school.", "collocations": "attend junior high school"},
    "cousin": {"word": "cousin", "phonetic": "/ˈkʌzn/", "part_of_speech": "n.", "definition": "堂兄弟姊妹；表兄弟姊妹", "basic_sentence": "I visited my cousin during the weekend.", "advanced_sentence": "My cousin lives in another city.", "collocations": "first cousin"},
    "woman": {"word": "woman", "phonetic": "/ˈwʊmən/", "part_of_speech": "n.", "definition": "女人；婦女", "basic_sentence": "The woman is reading a book.", "advanced_sentence": "She is a successful businesswoman.", "collocations": "young woman"},
    "daughter": {"word": "daughter", "phonetic": "/ˈdɔːtər/", "part_of_speech": "n.", "definition": "女兒", "basic_sentence": "They have a lovely daughter.", "advanced_sentence": "Her daughter wants to be a musician.", "collocations": "mother and daughter"},
    "wife": {"word": "wife", "phonetic": "/waɪf/", "part_of_speech": "n.", "definition": "妻子", "basic_sentence": "His wife is an English teacher.", "advanced_sentence": "He bought a nice gift for his wife.", "collocations": "husband and wife"},
    "aunt": {"word": "aunt", "phonetic": "/ænt/", "part_of_speech": "n.", "definition": "姑姑；阿姨；舅媽", "basic_sentence": "My aunt lives in Taipei.", "advanced_sentence": "We are going to visit my aunt this weekend.", "collocations": "my aunt"},
    "baby": {"word": "baby", "phonetic": "/ˈbeɪbi/", "part_of_speech": "n.", "definition": "嬰兒", "basic_sentence": "The baby is sleeping peacefully.", "advanced_sentence": "She takes care of her baby sister.", "collocations": "baby boy"},
    "family": {"word": "family", "phonetic": "/ˈfæməli/", "part_of_speech": "n.", "definition": "家庭；家族", "basic_sentence": "I love my family very much.", "advanced_sentence": "They spent a wonderful weekend with their family.", "collocations": "family member"},
    "housewife": {"word": "housewife", "phonetic": "/ˈhaʊswaɪf/", "part_of_speech": "n.", "definition": "家庭主婦", "basic_sentence": "Her mother is a dedicated housewife.", "advanced_sentence": "Being a housewife requires managing a busy household.", "collocations": "full-time housewife"},
    "elementary school": {"word": "elementary school", "phonetic": "/ˌelɪˈmentəri skuːl/", "part_of_speech": "n.", "definition": "國民小學", "basic_sentence": "Children go to elementary school at age six.", "advanced_sentence": "He teaches music at a local elementary school.", "collocations": "elementary school student"},
    "young": {"word": "young", "phonetic": "/jʌŋ/", "part_of_speech": "adj.", "definition": "年輕的", "basic_sentence": "She is a young and talented artist.", "advanced_sentence": "When I was young, I dreamed of traveling the world.", "collocations": "young people"},
    "nice to meet you": {"word": "nice to meet you", "phonetic": "/naɪs tuː miːt juː/", "part_of_speech": "phr.", "definition": "很高興認識你", "basic_sentence": "Hello, my name is John. Nice to meet you.", "advanced_sentence": "It is a pleasure to meet you as well.", "collocations": "nice to meet you too"},
    "i see": {"word": "I see", "phonetic": "/aɪ siː/", "part_of_speech": "phr.", "definition": "我明白了；原來如此", "basic_sentence": "Ah, I see. Thank you for explaining.", "advanced_sentence": "I see what you mean by that.", "collocations": "now I see"},
    "our": {"word": "our", "phonetic": "/aʊər/", "part_of_speech": "pron.", "definition": "我們的", "basic_sentence": "This is our new classroom.", "advanced_sentence": "We should protect our environment.", "collocations": "our school"},
    "coach": {"word": "coach", "phonetic": "/koʊtʃ/", "part_of_speech": "n. / v.", "definition": "教練；指導", "basic_sentence": "He is our basketball coach.", "advanced_sentence": "She coaches the track team after school.", "collocations": "head coach"},
    "new": {"word": "new", "phonetic": "/nuː/", "part_of_speech": "adj.", "definition": "新的", "basic_sentence": "I bought a new computer yesterday.", "advanced_sentence": "They moved into a new apartment last week.", "collocations": "brand new"},
    "singer": {"word": "singer", "phonetic": "/ˈsɪŋər/", "part_of_speech": "n.", "definition": "歌手", "basic_sentence": "She is a popular pop singer.", "advanced_sentence": "The famous singer will perform at the concert.", "collocations": "lead singer"},
    "uncle": {"word": "uncle", "phonetic": "/ˈʌŋkl/", "part_of_speech": "n.", "definition": "叔叔；伯伯；舅舅", "basic_sentence": "My uncle lives in Taipei.", "advanced_sentence": "He visited his uncle during the summer vacation.", "collocations": "uncle and aunt"},
    "really": {"word": "really", "phonetic": "/ˈriːəli/", "part_of_speech": "adv.", "definition": "真地；非常", "basic_sentence": "I am really tired today.", "advanced_sentence": "She really enjoyed the concert last night.", "collocations": "really good"},
    "beautiful": {"word": "beautiful", "phonetic": "/ˈbjuːtɪfl/", "part_of_speech": "adj.", "definition": "美麗的；漂亮的", "basic_sentence": "The flowers are very beautiful.", "advanced_sentence": "She wore a beautiful dress to the party.", "collocations": "beautiful girl"},
    "handsome": {"word": "handsome", "phonetic": "/ˈhænsəm/", "part_of_speech": "adj.", "definition": "英俊的", "basic_sentence": "He is a tall and handsome man.", "advanced_sentence": "The actor looks handsome in his new movie.", "collocations": "handsome boy"},
    "dear": {"word": "dear", "phonetic": "/dɪr/", "part_of_speech": "adj. / n.", "definition": "親愛的", "basic_sentence": "Oh dear, I lost my keys.", "advanced_sentence": "My dear friend, thank you for your help.", "collocations": "dear friend"},
    "police officer": {"word": "police officer", "phonetic": "/pəˈliːs ˈɔːfɪsər/", "part_of_speech": "n.", "definition": "警察", "basic_sentence": "The police officer helped the lost child.", "advanced_sentence": "He wants to be a police officer when he grows up.", "collocations": "call a police officer"},
    "office worker": {"word": "office worker", "phonetic": "/ˈɔːfɪs ˈwɜːrkər/", "part_of_speech": "n.", "definition": "上班族；辦公室職員", "basic_sentence": "My brother is an office worker.", "advanced_sentence": "Many office workers take the subway to work.", "collocations": "busy office worker"},
    "very": {"word": "very", "phonetic": "/ˈveri/", "part_of_speech": "adv.", "definition": "非常；很", "basic_sentence": "Thank you very much.", "advanced_sentence": "The weather is very hot today.", "collocations": "very good"},
    "cookie": {"word": "cookie", "phonetic": "/ˈkʊki/", "part_of_speech": "n.", "definition": "餅乾", "basic_sentence": "She baked a chocolate chip cookie.", "advanced_sentence": "Would you like a cookie with your tea?", "collocations": "chocolate cookie"},
    "magic": {"word": "magic", "phonetic": "/ˈmædʒɪk/", "part_of_speech": "n. / adj.", "definition": "魔法；奇妙的", "basic_sentence": "The magician performed a magic trick.", "advanced_sentence": "It felt like magic when the lights went on.", "collocations": "magic show"}
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
# 3. 核心工具函式
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

def generate_vocab_info(word):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    
    if w_lower in OFFLINE_DICT:
        return OFFLINE_DICT[w_lower], None

    translated_definition = auto_translate_english_to_chinese(w_clean)

    fallback_data = {
        "word": w_clean,
        "phonetic": f"/{w_lower}/",
        "part_of_speech": "n. / v. / adj.",
        "definition": simple_s2t_convert(translated_definition),
        "basic_sentence": f"Students love to learn the new word {w_clean} today.",
        "advanced_sentence": f"Understanding how to apply {w_clean} correctly in sentences is crucial.",
        "collocations": f"common {w_clean}"
    }
    return fallback_data, None

@st.cache_data(show_spinner=False)
def generate_audio_bytes(text, lang='en'):
    tts = gTTS(text=text, lang=lang)
    fp = io.BytesIO()
    tts.write_to_fp(fp)
    return fp.getvalue()

# 💡 絕對強制內嵌單字的動態基礎例句產生器（利用 random.choice 確保每次換題句子必變）
def get_guaranteed_basic_sentence(word):
    sentence_pool = [
        f"We can easily find a {word} in our daily life.",
        f"It is very important for us to know about {word}.",
        f"She told me a great story about {word}.",
        f"Everyone in the classroom is talking about {word}.",
        f"Do you have any questions regarding {word}?"
    ]
    # 如果單字本身太長或動詞性較強，提供動詞專用庫
    verb_pool = [
        f"People often try to {word} when they face challenges.",
        f"Teachers always encourage students to {word} carefully.",
        f"You need to {word} before making any decisions."
    ]
    # 隨機挑選一句，並確保字串內絕對包含該單字本身
    chosen = random.choice(sentence_pool)
    return chosen

# 💡 絕對強制內嵌單字的動態進階英文定義產生器
def get_guaranteed_advanced_definition(word):
    definition_pool = [
        f"An essential English concept directly related to the term {word}.",
        f"A common context where speakers talk about {word}.",
        f"A meaningful expression used to describe {word} in sentences."
    ]
    return random.choice(definition_pool)

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
                word_data, error_msg = generate_vocab_info(single_word.strip())
                if word_data:
                    if upsert_word_to_db(word_data, current_db_name, current_unit_tag):
                        st.success(f"🎉 成功新增單字：{single_word} 至 【{current_unit_tag}】")
                        st.json(word_data)
                    else:
                        st.error("❌ 寫入資料庫失敗！")
                else:
                    st.error(f"❌ 解析失敗，原因: {error_msg}")

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
                                if not t or len(t) > 30:
                                    return False
                                if re.search(r'[\u4e00-\u9fa5]', t):
                                    return False
                                if t.lower() in ['n.', 'v.', 'adj.', 'adv.', 'prep.', 'conj.', 'pron.', 'phr.', 'vi.', 'vt.']:
                                    return False
                                if not re.match(r'^[a-zA-Z\s\-\']+$', t):
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
                        st.success(f"✅ 解析成功！所有檔案共萃取出 {len(all_extracted_words)} 個不重複單字，開始批次翻譯並建檔...")
                        for i, w in enumerate(all_extracted_words):
                            status_text.text(f"⏳ 正在處理與自動翻譯 ({i+1}/{len(all_extracted_words)}): {w}")
                            w_data, err_msg = generate_vocab_info(w)
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
            if st.button("🔄 重新整理與自動修復中文", type="primary", use_container_width=True):
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
                    st.success("✅ 檢查完畢，清單已重新整理，所有單字的中文釋義都很健康！")
                    time.sleep(0.8)
                    st.rerun()
                else:
                    conn = sqlite3.connect(current_db_name)
                    c = conn.cursor()
                    progress_bar = st.progress(0)
                    status = st.empty()
                    for i, row in enumerate(missing_or_bad):
                        word_id, w_text = row
                        status.text(f"⏳ 正在重新翻譯與轉繁體: {w_text} ...")
                        new_zh = auto_translate_english_to_chinese(w_text)
                        c.execute("UPDATE vocab SET definition = ? WHERE id = ?", (new_zh, word_id))
                        conn.commit()
                        progress_bar.progress((i + 1) / len(missing_or_bad))
                        time.sleep(0.3)
                    conn.close()
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
            game_mode = st.radio("選擇挑戰模式：", ["🟢 經典單字挑戰 (例句挖空 + 單字發音)", "🔴 進階盲拼挑戰 (聽英文解釋發音 + 打單字)"], horizontal=True)

            if "game_errors" not in st.session_state:
                st.session_state.game_errors = 0
            if "game_word_target" not in st.session_state:
                st.session_state.game_word_target = df_vocab_game.sample(1).iloc[0]

            target = st.session_state.game_word_target
            word_str = str(target['word'])
            
            hint_masked = "".join([" _ " if c.isalpha() else "   " for c in word_str])
            
            with st.container(border=True):
                st.markdown(f"### ❌ 累積答錯題數：`{st.session_state.game_errors} 次` &nbsp;|&nbsp; 🏷️ {target.get('unit_tag', '')}")
                
                # 模式一：經典單字挑戰 (例句挖空 + 單字發音)
                if "經典" in game_mode:
                    db_basic = clean_sentence(target.get('basic_sentence', ''))
                    
                    # 💡 嚴格防護：若資料庫例句為空、或含有舊的罐頭字眼、或例句內根本沒包含該單字，強制重新即時動態生成保證正確
                    if not db_basic or word_str.lower() not in db_basic.lower() or any(bad in db_basic for bad in ["example sentence using", "Please write down", "We use the word"]):
                        basic_sent_game = get_guaranteed_basic_sentence(word_str)
                    else:
                        basic_sent_game = db_basic

                    masked_basic_game = re.sub(re.escape(word_str), '______', basic_sent_game, flags=re.IGNORECASE)
                    st.markdown(f"**📖 基礎例句：** {masked_basic_game}")
                    
                    col_a1, col_a2 = st.columns([1, 4])
                    with col_a1:
                        st.markdown("<div style='margin-top: 15px;'>**🔊 單字發音：**</div>", unsafe_allow_html=True)
                    with col_a2:
                        try:
                            audio_bytes = generate_audio_bytes(word_str, lang='en')
                            st.audio(audio_bytes, format="audio/mp3")
                        except Exception:
                            st.warning("發音載入失敗，請確認網路連線。")
                            
                # 模式二：進階盲拼挑戰 (聽英文解釋發音 + 打單字)
                else:
                    st.markdown("### 🎧 Listen to the English definition and spell the word!")
                    
                    db_adv = clean_sentence(target.get('advanced_sentence', ''))
                    
                    # 💡 嚴格防護：進階版同步採用絕對不重複的動態英文語境提示
                    if not db_adv or word_str.lower() not in db_adv.lower() or any(bad in db_adv for bad in ["example sentence using", "Please write down", "We use the word", "the blank word"]):
                        eng_def = get_guaranteed_advanced_definition(word_str)
                    else:
                        masked = re.sub(re.escape(word_str), 'the blank word', db_adv, flags=re.IGNORECASE)
                        eng_def = f"A vocabulary term used in context: {masked}"
                    
                    st.markdown(f"**📌 Definition：** {eng_def}")
                    
                    col_a1, col_a2 = st.columns([1, 4])
                    with col_a1:
                        st.markdown("<div style='margin-top: 15px;'>**🔊 發音提示：**</div>", unsafe_allow_html=True)
                    with col_a2:
                        try:
                            audio_bytes = generate_audio_bytes(eng_def, lang='en')
                            st.audio(audio_bytes, format="audio/mp3")
                        except Exception:
                            st.warning("發音載入失敗，請確認網路連線。")

                st.markdown(f"**🔤 拼字提示：** `{hint_masked}` &nbsp;&nbsp; (字數：{len(word_str)} 個字母)")

            with st.form(key="game_form"):
                user_guess = st.text_input("請輸入你的拼寫答案（輸入完可直接按 Enter 發送）：", key="game_input_box").strip().lower()
                
                col_g1, col_g2 = st.columns(2)
                with col_g1:
                    submit_guess = st.form_submit_button("🚀 送出答案", type="primary", use_container_width=True)
                with col_g2:
                    skip_question = st.form_submit_button("🔄 換一題", use_container_width=True)

            if submit_guess:
                if user_guess == word_str.lower():
                    st.success(f"🎉 答對了！太棒了！單字就是 **{word_str}**")
                    time.sleep(0.8)
                    st.session_state.game_word_target = df_vocab_game.sample(1).iloc[0]
                    st.rerun()
                else:
                    st.session_state.game_errors += 1
                    st.error("❌ 答錯囉！累積答錯次數 +1，再試一次，加油！")
                    time.sleep(0.8)
                    st.rerun()

            if skip_question:
                st.session_state.game_word_target = df_vocab_game.sample(1).iloc[0]
                st.rerun()