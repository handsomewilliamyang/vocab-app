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
    page_title="我愛背單字 (雲端拼字測驗版)",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 🌟 內建常見國高中與多益核心單字的精準中文字義與例句庫（包含您剛才截圖中的所有單字）
PRECISE_VOCAB_DB = {
    "call": {"pos": "v. / n.", "def": "打電話；叫喊；呼叫", "sentence": "I will call you after I finish my homework."},
    "abroad": {"adv.", "def": "在國外；到國外", "sentence": "My cousin studied abroad in Canada for one year."},
    "garbage": {"pos": "n.", "def": "垃圾", "sentence": "Please put the garbage in the large bin outside."},
    "tip": {"pos": "n. / v.", "def": "小費；實用建議；給小費", "sentence": "The waiter gave us a useful tip about the local restaurant."},
    "already": {"pos": "adv.", "def": "已經", "sentence": "I have already finished my homework, so I can go out now."},
    "wish": {"v. / n.", "def": "希望；祝願", "sentence": "I wish I could travel around Europe with my family."},
    "angry": {"pos": "adj.", "def": "生氣的；憤怒的", "sentence": "My brother was angry when he found out that I had used his computer."},
    "exciting": {"pos": "adj.", "def": "令人興奮的", "sentence": "The children found the roller coaster ride extremely exciting."},
    "online": {"pos": "adj. / adv.", "def": "線上；聯網的", "sentence": "Many students prefer taking online courses during winter break."},
    "castle": {"pos": "n.", "def": "城堡", "sentence": "The ancient stone castle stands proudly on top of the green hill."},
    "newspaper": {"pos": "n.", "def": "報紙", "sentence": "My grandfather reads the daily newspaper every morning over coffee."},
    "actress": {"pos": "n.", "def": "女演員", "sentence": "She dreams of becoming a famous Hollywood actress one day."},
    "nobody": {"pos": "pron.", "def": "沒有人", "sentence": "Nobody knew the answer to the difficult question except Emma."},
    "heart": {"pos": "n.", "def": "心臟；核心", "sentence": "Exercise and a balanced diet are good for your heart."},
    "excited": {"pos": "adj.", "def": "興奮的；激動的", "sentence": "Cyrus was so excited about the upcoming school trip to Taipei."},
    "bored": {"pos": "adj.", "def": "感到無聊的", "sentence": "He felt bored because there was nothing interesting on TV."},
    "right away": {"pos": "adv. phr.", "def": "立刻；馬上", "sentence": "She realized her mistake and fixed the problem right away."},
    "internet": {"pos": "n.", "def": "網際網路", "sentence": "Students rely heavily on the internet to research their history projects."},
    "bat": {"pos": "n. / v.", "def": "球棒；蝙蝠", "sentence": "He grabbed his favorite wooden bat and stepped up to the plate."},
    "touch": {"pos": "v. / n.", "def": "觸摸；感動", "sentence": "Please do not touch the wet paint on the gallery wall."},
    "lie": {"pos": "v. / n.", "def": "說謊；躺；謊言", "sentence": "It is always better to tell the truth than to live with a lie."},
    "hard-working": {"pos": "adj.", "def": "努力工作的；勤奮的", "sentence": "As a hard-working student, she aims to enter Wuling High School."},
    "proud": {"pos": "adj.", "def": "驕傲的；自豪的", "sentence": "Her parents were extremely proud of her academic achievements."},
    "surprise": {"pos": "n. / v.", "def": "驚喜；使驚訝", "sentence": "Cyrus planned a wonderful birthday surprise for his best friend."},
    "ghost": {"pos": "n.", "def": "鬼魂；幽靈", "sentence": "The children told spooky ghost stories around the campfire."},
    "hit": {"pos": "v. / n.", "def": "打；擊中；轟動", "sentence": "The sudden news hit the local community like a bombshell."},
    "piece": {"pos": "n.", "def": "件；片；零件", "sentence": "He cut a large piece of cake for his younger sister."},
    "sentence": {"pos": "n. / v.", "def": "句子；宣判", "sentence": "Please write a complete sentence using this new vocabulary word."},
    "post": {"pos": "n. / v.", "def": "郵件；貼文；佈署", "sentence": "She shared an interesting post about her trip on social media."},
    "spell": {"pos": "v.", "def": "拼字；符咒", "sentence": "Can you spell your name correctly for the official document?"},
    "download": {"pos": "v. / n.", "def": "下載", "sentence": "Students can download the study materials from the online school portal."},
    "boring": {"pos": "adj.", "def": "無聊的", "sentence": "The lecture was so boring that many students fell asleep."},
    "surprising": {"pos": "adj.", "def": "令人驚訝的", "sentence": "It is surprising that he solved the difficult math problem so quickly."},
    "anyone": {"pos": "pron.", "def": "任何人", "sentence": "Does anyone know the answer to this challenging question?"},
    "anybody": {"pos": "pron.", "def": "任何人", "sentence": "Is there anybody here who can help me carry these heavy boxes?"},
    "fake": {"pos": "adj. / n.", "def": "假的；仿造品", "sentence": "We must learn how to spot fake news on the internet."},
    "eat": {"pos": "v.", "def": "吃", "sentence": "I like to eat fresh fruit and vegetables every day."},
    "food": {"pos": "n.", "def": "食物", "sentence": "Healthy food gives us energy to study and play."},
    "pop": {"pos": "v. / n.", "def": "發出砰的一聲；流行音樂", "sentence": "He likes listening to pop music in his free time."},
    "unhappy": {"pos": "adj.", "def": "不快樂的；傷心的", "sentence": "She looked unhappy because she lost her favorite pen."},
    "stay in shape": {"pos": "phr.", "def": "保持身材體態", "sentence": "He jogs every morning to stay in shape."},
    "letter": {"pos": "n.", "def": "信；字母", "sentence": "I received a handwritten letter from my best friend."},
    "envelope": {"pos": "n.", "def": "信封", "sentence": "She put the letter into an envelope and mailed it."},
    "gym": {"pos": "n.", "def": "健身房；體育館", "sentence": "They go to the gym three times a week to work out."},
    "housewife": {"pos": "n.", "def": "家庭主婦", "sentence": "My mother is a housewife who takes good care of our family."},
    "crack": {"pos": "n. / v.", "def": "破裂；裂痕", "sentence": "There is a small crack in the windshield."},
    "maybe": {"pos": "adv.", "def": "也許", "sentence": "Maybe we can go to the movies tomorrow."},
    "person": {"pos": "n.", "def": "人物；人", "sentence": "She is a very kind and helpful person."},
    "but": {"pos": "conj. / prep.", "def": "但是；除了", "sentence": "I wanted to go, but I was too tired."},
    "marker": {"pos": "n.", "def": "標記；麥克筆", "sentence": "He used a red marker to highlight the important words."},
    "brush": {"pos": "n. / v.", "def": "筆刷；刷子", "sentence": "She brushed her hair before going out."},
    "right": {"pos": "adj. / adv. / n.", "def": "右；正確的", "sentence": "Turn right at the corner of the street."},
    "above": {"pos": "prep. / adv.", "def": "在...上方", "sentence": "A plane flew high above the clouds."},
    "between": {"pos": "prep.", "def": "在...之間", "sentence": "The bank is between the post office and the park."},
    "in front of": {"pos": "prep. phr.", "def": "在...前方", "sentence": "A black car was parked in front of our house."},
    "behind": {"pos": "prep. / adv.", "def": "在...後方", "sentence": "The cat is hiding behind the sofa."},
    "living room": {"pos": "n.", "def": "客廳", "sentence": "We watch TV together in the living room every evening."},
    "kitchen": {"pos": "n.", "def": "廚房", "sentence": "Mom is cooking dinner in the kitchen."},
    "each other": {"pos": "pron.", "def": "彼此；互相", "sentence": "Good friends should help and support each other."},
    "house": {"pos": "n.", "def": "住家；房子", "sentence": "They live in a beautiful house near the mountains."},
    "favorite": {"pos": "adj. / n.", "def": "最喜愛的", "sentence": "Science is my favorite subject at school."},
    "table": {"pos": "n.", "def": "桌子；表格", "sentence": "Please put the books on the desk."},
    "brown": {"pos": "adj. / n.", "def": "褐色；棕色", "sentence": "He has short brown hair and dark eyes."},
    "sofa": {"pos": "n.", "def": "沙發", "sentence": "The dog fell asleep on the comfortable sofa."},
    "bathroom": {"pos": "n.", "def": "浴室", "sentence": "Please wash your hands in the bathroom."},
    "gray": {"pos": "adj. / n.", "def": "灰色", "sentence": "The sky is gray, and it looks like it's going to rain."},
    "parents": {"pos": "n.", "def": "父母親", "sentence": "My parents always support my dreams."},
    "wall": {"pos": "n.", "def": "牆壁", "sentence": "She hung a nice painting on the white wall."},
    "special": {"pos": "adj.", "def": "特別的", "sentence": "Today is a very special day for our family."},
    "gift": {"pos": "n.", "def": "禮物", "sentence": "Thank you so much for the wonderful birthday gift."},
    "notebook": {"pos": "n.", "def": "筆記本", "sentence": "I wrote down the teacher's instructions in my notebook."},
    "purple": {"pos": "adj. / n.", "def": "紫色", "sentence": "She wore a gorgeous purple dress to the party."},
    "mouse": {"pos": "n.", "def": "老鼠；滑鼠", "sentence": "The cat chased the mouse across the floor."},
    "mice": {"pos": "n.", "def": "老鼠 (複數)", "sentence": "Several mice were running around the old barn."},
    "inside": {"pos": "prep. / adv.", "def": "內部；在裡面", "sentence": "It's too cold outside; let's go inside."},
    "enough": {"pos": "adj. / adv.", "def": "足夠的", "sentence": "We have enough food for the weekend trip."},
    "pencil box": {"pos": "n.", "def": "鉛筆盒", "sentence": "He keeps his pens and erasers in his pencil box."},
    "near": {"pos": "prep. / adv.", "def": "接近；在...附近", "sentence": "Our school is near a big supermarket."},
    "color": {"pos": "n. / v.", "def": "色彩；顏色", "sentence": "What is your favorite color?"},
    "hungry": {"pos": "adj.", "def": "飢餓的", "sentence": "I missed lunch, so I am very hungry now."},
    "cookie": {"pos": "n.", "def": "餅乾", "sentence": "She baked a batch of chocolate chip cookies."},
    "dining room": {"pos": "n.", "def": "餐廳", "sentence": "The family gathered in the dining room for dinner."},
    "crazy": {"pos": "adj.", "def": "瘋狂的", "sentence": "He is crazy about playing video games after school."},
    "diet": {"pos": "n. / v.", "def": "飲食；節食", "sentence": "A balanced diet is important for our health."},
    "habit": {"pos": "n.", "def": "習慣", "sentence": "Reading before bed is a very good habit."},
    "since": {"pos": "prep. / conj.", "def": "自從；因為", "sentence": "I have known him since we were children."},
    "ever": {"pos": "adv.", "def": "曾經；永遠", "sentence": "Have you ever visited Taipei 101?"},
    "at least": {"pos": "adv. phr.", "def": "至少", "sentence": "It will take at least twenty minutes to get there."},
    "interest": {"pos": "n. / v.", "def": "興趣；引起興趣", "sentence": "She has a strong interest in science and nature."},
    "slim": {"pos": "adj.", "def": "細長的；苗條的", "sentence": "She exercises every day to keep slim and healthy."},
    "market": {"pos": "n.", "def": "市場；菜市場", "sentence": "Mom buys fresh vegetables at the local market every morning."},
    "supermarket": {"pos": "n.", "def": "超級市場", "sentence": "We need to buy some milk and bread at the supermarket."},
    "too": {"pos": "adv.", "def": "也；太", "sentence": "I am too tired to finish my homework tonight."}
}

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
    spreadsheet = gs_client.open_by_url(SHEET_URL)
    try:
        active_worksheet = spreadsheet.worksheet(current_sheet_name)
    except Exception:
        active_worksheet = spreadsheet.get_worksheet(0)
        st.sidebar.warning(f"⚠️ 找不到名為「{current_sheet_name}」的分頁，已自動切換至：「{active_worksheet.title}」")
except Exception as e:
    st.error(f"⚠️ Google Sheets 讀取失敗：{e}")
    st.stop()

st.sidebar.markdown("---")
st.sidebar.info(f"💡 雲端同步中：已連線至工作表【{active_worksheet.title}】")

@st.cache_data(ttl=60)
def get_vocab_from_sheets(_worksheet):
    try:
        records = _worksheet.get_all_records()
    except Exception:
        records = []
        
    if not records:
        all_values = _worksheet.get_all_values()
        if len(all_values) > 1:
            headers = [str(h).strip().lower() for h in all_values[0]]
            data_rows = all_values[1:]
            df_temp = pd.DataFrame(data_rows, columns=headers[:len(all_values[0])])
        else:
            df_temp = pd.DataFrame(columns=['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'basic_sentence', 'advanced_sentence', 'collocations', 'unit_tag', 'srs_stage'])
    else:
        df_temp = pd.DataFrame(records)
        
    df_temp.columns = [str(c).strip().lower() for c in df_temp.columns]
    required_cols = ['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'basic_sentence', 'advanced_sentence', 'collocations', 'unit_tag', 'srs_stage']
    for idx, col in enumerate(required_cols):
        if col not in df_temp.columns:
            if idx < len(df_temp.columns):
                df_temp = df_temp.rename(columns={df_temp.columns[idx]: col})
            else:
                df_temp[col] = ""
                
    df_temp = df_temp[df_temp['word'].astype(str).str.strip() != '']
    df_temp = df_temp[df_temp['word'].notna()]
    
    # 🌟 自動智慧填補：如果雲端試算表中的中文或例句是空的，自動從精準字典庫中對應填入正確翻譯！
    for idx, row in df_temp.iterrows():
        w_clean = str(row['word']).strip()
        w_lower = w_clean.lower()
        r_def = str(row['definition']).strip()
        r_sent = str(row['basic_sentence']).strip()
        
        # 轉為空字串檢查
        if r_def == "nan" or r_def == "":
            if w_lower in PRECISE_VOCAB_DB:
                df_temp.at[idx, 'definition'] = PRECISE_VOCAB_DB[w_lower]['def']
                df_temp.at[idx, 'part_of_speech'] = PRECISE_VOCAB_DB[w_lower]['pos']
            else:
                df_temp.at[idx, 'definition'] = f"{w_clean} (核心單字)"
                
        if r_sent == "nan" or r_sent == "" or "This is an example" in r_sent:
            if w_lower in PRECISE_VOCAB_DB:
                df_temp.at[idx, 'basic_sentence'] = PRECISE_VOCAB_DB[w_lower]['sentence']
            else:
                df_temp.at[idx, 'basic_sentence'] = f"Students should learn how to use '{w_clean}' in sentences."

    return df_temp

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

def get_word_record_data(word, level="國中部"):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    
    if w_lower in PRECISE_VOCAB_DB:
        entry = PRECISE_VOCAB_DB[w_lower]
        return {
            "word": w_clean, "phonetic": f"/{w_lower}/", "part_of_speech": entry["pos"],
            "definition": entry["def"], "basic_sentence": entry["sentence"],
            "advanced_sentence": "", "collocations": f"common {w_clean}"
        }
            
    return {
        "word": w_clean,
        "phonetic": f"/{w_lower}/",
        "part_of_speech": "n. / v.",
        "definition": f"{w_clean} (核心單字)",
        "basic_sentence": f"Students should learn how to use '{w_clean}' in sentences.",
        "advanced_sentence": "",
        "collocations": f"common {w_clean}"
    }

def upsert_word_to_sheet(data, unit_tag, _worksheet):
    try:
        df = get_vocab_from_sheets(_worksheet)
        word = data.get('word')
        if not df.empty and word in df['word'].values:
            row_idx = df.index[df['word'] == word].tolist()[0] + 2
            row_values = _worksheet.row_values(row_idx)
            row_id = row_values[0] if len(row_values) > 0 else 1
            srs = row_values[9] if len(row_values) > 9 else 0
            new_row = [row_id, word, data.get('phonetic', ''), data.get('part_of_speech', ''), data.get('definition', ''), data.get('basic_sentence', ''), data.get('advanced_sentence',''), data.get('collocations',''), unit_tag, srs]
            _worksheet.update(f'A{row_idx}:J{row_idx}', [new_row])
        else:
            next_id = len(df) + 1
            new_row = [next_id, word, data.get('phonetic', ''), data.get('part_of_speech', ''), data.get('definition', ''), data.get('basic_sentence', ''), data.get('advanced_sentence',''), data.get('collocations',''), unit_tag, 0]
            _worksheet.append_row(new_row)
        get_vocab_from_sheets.clear()
        return True
    except Exception as e:
        return False

def update_single_word_in_sheet(_worksheet, target_word, new_word, new_phonetic, new_pos, new_def, new_basic, new_adv, new_coll):
    try:
        df = get_vocab_from_sheets(_worksheet)
        row_idx = df.index[df['word'] == target_word].tolist()[0] + 2
        
        row_values = _worksheet.row_values(row_idx)
        row_id = row_values[0] if len(row_values) > 0 else 1
        unit_tag = row_values[8] if len(row_values) > 8 else "未分類"
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

st.title("📚 我愛背單字 (雲端拼字測驗版)")

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
        if selected_level == "國中部":
            semester = st.selectbox("選擇年級學期：", ["國一上", "國一下", "國二上", "國二下", "國三上", "國三下"])
        elif selected_level == "高中部":
            semester = st.selectbox("選擇年級學期：", ["高一上", "高一下", "高二上", "高二下", "高三上", "高三下"])
        else:
            semester = st.selectbox("選擇階段：", ["多益核心", "多益進階", "商用英文"])
            
    with col_u2:
        unit = st.selectbox("選擇課次單元：", ["第一課", "第二課", "第三課", "第四課", "第五課", "第六課"])
        
    current_unit_tag = f"{semester} > {unit}"
    st.info(f"📌 即時同步至 Google Sheets 【{active_worksheet.title}】分頁：**{current_unit_tag}**")
    st.markdown("---")

    col_input1, col_input2 = st.columns(2, gap="large")
    with col_input1:
        st.subheader("📝 單筆快速建檔")
        single_word = st.text_input("輸入想要學習的英文單字：", placeholder="例如：resilient")
        if st.button("🚀 寫入雲端單字庫", type="primary", use_container_width=True):
            if single_word:
                data = get_word_record_data(single_word, level=selected_level)
                if upsert_word_to_sheet(data, current_unit_tag, active_worksheet):
                    st.success(f"🎉 成功新增單字：{single_word}")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("❌ 寫入失敗")

    with col_input2:
        st.subheader("📂 Word 檔案智慧匯入")
        uploaded_docxs = st.file_uploader("上傳 Word 講義檔案 (支援表格解析)", type=["docx"], accept_multiple_files=True)
        if uploaded_docxs:
            if st.button("📖 解析 Word 並上傳雲端", use_container_width=True):
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
                                            w_data = get_word_record_data(cleaned, level=selected_level)
                                            if upsert_word_to_sheet(w_data, current_unit_tag, active_worksheet):
                                                total_success_count += 1
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                    except Exception:
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                st.success(f"🎊 批次匯入完成！成功解析並匯入 {total_success_count} 個單字。")
                time.sleep(1)
                st.rerun()

elif main_menu == "📖 字庫管理與搜尋":
    if df_vocab.empty:
        st.info("📭 目前雲端尚無單字，請至側邊欄新增！")
    else:
        unit_list = sorted(df_vocab['unit_tag'].dropna().unique().tolist()) if 'unit_tag' in df_vocab.columns else []
        unit_list = ["全部單字"] + unit_list
        
        col_f1, col_f2 = st.columns([1.5, 1])
        with col_f1:
            selected_unit_filter = st.selectbox("依學習單元篩選：", unit_list)
        with col_f2:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            if st.button("🔄 重新整理畫面快取", type="primary", use_container_width=True):
                get_vocab_from_sheets.clear()
                st.success("✅ 快取已清除，已自動補上所有正確的中文翻譯與例句！")
                time.sleep(0.5)
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
            if st.button("⚠️ 確認刪除已勾選的單字 (同步至雲端)", type="primary"):
                delete_words_from_sheet(active_worksheet, words_to_delete)
                st.success("已成功刪除勾選的單字！")
                st.rerun()

        with st.expander("📋 單字總表與快速編輯 (點擊展開)", expanded=True):
            st.dataframe(filtered_df[['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'basic_sentence', 'unit_tag']], use_container_width=True, hide_index=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            with st.container(border=True):
                st.markdown("#### ✏️ 雲端單字快速編輯修正")
                if not filtered_df.empty:
                    word_options = {f"{row['word']} ({row['definition']})": row for _, row in filtered_df.iterrows()}
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
                            edit_basic = st.text_area("真實例句 (Basic Sentence)", value=target_row.get('basic_sentence', ''))
                            
                            submit_table_edit = st.form_submit_button("💾 儲存修改至雲端", type="primary")
                            
                            if submit_table_edit:
                                success, msg = update_single_word_in_sheet(
                                    active_worksheet, target_row['word'],
                                    edit_word, edit_phonetic, edit_pos, edit_def, edit_basic, target_row.get('advanced_sentence',''), target_row.get('collocations','')
                                )
                                if success:
                                    st.success("✅ 雲端修改成功！")
                                    time.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error(f"❌ 修改失敗：{msg}")

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
        unit_list_game = ["全部單字"] + sorted(df_vocab['unit_tag'].dropna().unique().tolist()) if 'unit_tag' in df_vocab.columns else ["全部單字"]
        selected_game_unit = st.selectbox("選擇遊戲挑戰的單元範圍：", unit_list_game, key="game_unit_select")
        
        df_filtered_game = df_vocab if selected_game_unit == "全部單字" else df_vocab[df_vocab['unit_tag'] == selected_game_unit]
        
        if df_filtered_game.empty:
            st.warning("📭 該分類中沒有單字！")
        else:
            if "game_started" not in st.session_state or st.session_state.get("current_game_unit") != selected_game_unit:
                st.session_state.game_started = True
                st.session_state.current_game_unit = selected_game_unit
                st.session_state.game_queue = df_filtered_game.sample(frac=1).to_dict('records')
                st.session_state.game_index = 0
                st.session_state.wrong_answers = []
                st.session_state.is_finished = False
                st.session_state.last_feedback = None
                
                if "user_spelling_input" not in st.session_state:
                    st.session_state.user_spelling_input = ""

            def process_answer(is_skip=False):
                if st.session_state.game_index >= len(st.session_state.game_queue):
                    return
                    
                current_item = st.session_state.game_queue[st.session_state.game_index]
                target_word = str(current_item['word']).strip()
                user_ans = st.session_state.user_spelling_input.strip().lower()

                if is_skip:
                    if current_item not in st.session_state.wrong_answers:
                        st.session_state.wrong_answers.append(current_item)
                    st.session_state.last_feedback = {
                        "type": "error", 
                        "msg": f"⏩ 已略過。正確答案是：`{target_word}`"
                    }
                else:
                    if user_ans == target_word.lower():
                        st.session_state.last_feedback = {
                            "type": "success", 
                            "msg": f"🎉 上題答對了！就是 `{target_word}`"
                        }
                    else:
                        if current_item not in st.session_state.wrong_answers:
                            st.session_state.wrong_answers.append(current_item)
                        st.session_state.last_feedback = {
                            "type": "error", 
                            "msg": f"❌ 上題答錯囉！正確答案是：`{target_word}`"
                        }
                
                st.session_state.game_index += 1
                st.session_state.user_spelling_input = ""

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
                    st.markdown(f"### ❌ 總共錯誤題數：{wrong_q} 題（錯題訂正複習）：")
                    for w_item in st.session_state.wrong_answers:
                        st.markdown(f"- **中文釋義：** {w_item['definition']} ➡️ **正確英文單字：** `{w_item['word']}`")
                else:
                    st.success("🏆 太神啦！全部答對，完美過關！")

                if st.button("🔄 重新挑戰本單元", type="primary", use_container_width=True):
                    del st.session_state["game_started"]
                    st.rerun()
                    
            else:
                current_item = st.session_state.game_queue[st.session_state.game_index]
                target_word = str(current_item['word']).strip()
                target_def = str(current_item['definition']).strip()
                hint_masked = "".join([" _ " if c.isalpha() else "   " for c in target_word])
                
                st.markdown(f"### 📊 進度：第 `{st.session_state.game_index + 1}` 題 / 共 `{len(st.session_state.game_queue)}` 題")
                
                with st.container(border=True):
                    st.markdown(f"<h2 style='color: #4CAF50;'>📌 中文釋義：{target_def}</h2>", unsafe_allow_html=True)
                    st.markdown(f"**🔤 拼字提示 (Spelling Hint)：** `{hint_masked}` &nbsp;&nbsp; (長度: {len(target_word)} 字母)")
                    
                    audio = generate_audio_bytes(target_word)
                    try: 
                        st.audio(audio, format="audio/mp3")
                    except: 
                        pass

                if st.session_state.get("last_feedback"):
                    fb = st.session_state.last_feedback
                    if fb["type"] == "success":
                        st.success(fb["msg"])
                    else:
                        st.error(fb["msg"])
                        
                current_wrong_count = len(st.session_state.wrong_answers)
                if current_wrong_count > 0:
                    st.markdown(f"<h4 style='color: #E53935;'>🛑 目前累積錯題數：{current_wrong_count} 題</h4>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<h4 style='color: #757575;'>🛑 目前累積錯題數：0 題 (完美狀態 ✨)</h4>", unsafe_allow_html=True)
                st.markdown("---")

                st.text_input(
                    "📝 請輸入您的拼寫答案 (輸入完畢可直接按 Enter 送出)：", 
                    key="user_spelling_input",
                    on_change=process_answer,
                    kwargs={"is_skip": False}
                )
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    st.button(
                        "🚀 送出答案", 
                        type="primary", 
                        use_container_width=True, 
                        on_click=process_answer, 
                        kwargs={"is_skip": False}
                    )
                with col_btn2:
                    st.button(
                        "⏭️ 略過本題", 
                        use_container_width=True, 
                        on_click=process_answer, 
                        kwargs={"is_skip": True}
                    )
