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

CORE_VOCAB_DICT = {
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
    "bathroom": {"pos": "n.", "def": "浴室；廁所", "sentence": "Please wash your hands in the bathroom."},
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
    active_worksheet = gs_client.open_by_url(SHEET_URL).worksheet(current_sheet_name)
except Exception as e:
    st.error(f"⚠️ 找不到名為「{current_sheet_name}」的工作表。")
    st.stop()

st.sidebar.markdown("---")
st.sidebar.info(f"💡 雲端同步中：已連線至工作表【{current_sheet_name}】")

@st.cache_data(ttl=2)
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

def get_word_record_data(word):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    
    if w_lower in CORE_VOCAB_DICT:
        entry = CORE_VOCAB_DICT[w_lower]
        return {
            "word": w_clean,
            "phonetic": f"/{w_lower}/",
            "part_of_speech": entry["pos"],
            "definition": entry["def"],
            "basic_sentence": entry["sentence"],
            "advanced_sentence": "",
            "collocations": f"common {w_clean}"
        }
        
    pos_res, def_res = "n. / v.", "中文釋義待補"
    sent_res = f"People use {w_clean} in daily life."
    
    if HAS_GEMINI and st.session_state.get('gemini_api_key'):
        try:
            genai.configure(api_key=st.session_state.gemini_api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"Provide part of speech and Traditional Chinese definition for '{w_clean}' in format POS|DEF, and a natural everyday sentence. Format: POS|||DEF|||SENTENCE"
            response = model.generate_content(prompt)
            if response.text and "|||" in response.text:
                parts = response.text.strip().split("|||")
                if len(parts) >= 3:
                    pos_res = parts[0].strip()
                    def_res = simple_s2t_convert(parts[1].strip())
                    sent_res = parts[2].strip().replace('"', '')
        except:
            pass
            
    return {
        "word": w_clean,
        "phonetic": f"/{w_lower}/",
        "part_of_speech": pos_res,
        "definition": def_res,
        "basic_sentence": sent_res,
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
    st.info(f"📌 即時同步至 Google Sheets 【{current_sheet_name}】分頁：**{current_unit_tag}**")
    st.markdown("---")

    col_input1, col_input2 = st.columns(2, gap="large")
    with col_input1:
        st.subheader("📝 單筆快速建檔")
        single_word = st.text_input("輸入想要學習的英文單字：", placeholder="例如：resilient")
        if st.button("🚀 寫入雲端單字庫", type="primary", use_container_width=True):
            if single_word:
                data = get_word_record_data(single_word)
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
                                            w_data = get_word_record_data(cleaned)
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
            if st.button("🔄 安全修復空白或呆板例句", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                fixed_count = 0
                
                for idx, row in df_vocab.iterrows():
                    r_word = str(row['word']).strip()
                    w_lower = r_word.lower()
                    r_sent = str(row['basic_sentence']).strip()
                    
                    is_bad_sentence = (not r_sent or "This is an example" in r_sent or "%s" in r_sent)
                    if is_bad_sentence:
                        if w_lower in CORE_VOCAB_DICT:
                            entry = CORE_VOCAB_DICT[w_lower]
                            status_text.text(f"⏳ 正在修復: {r_word} ...")
                            update_single_word_in_sheet(
                                active_worksheet, r_word, r_word, 
                                row['phonetic'], entry["pos"], entry["def"], entry["sentence"], row.get('advanced_sentence',''), row.get('collocations','')
                            )
                            fixed_count += 1
                    progress_bar.progress((idx + 1) / len(df_vocab))
                
                status_text.empty()
                st.success(f"🎊 修復完成！已成功幫您補齊 {fixed_count} 筆例句。")
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
            # 初始化遊戲狀態
            if "game_started" not in st.session_state or st.session_state.get("current_game_unit") != selected_game_unit:
                st.session_state.current_game_unit = selected_game_unit
                st.session_state.game_queue = df_filtered_game.sample(frac=1).to_dict('records')
                st.session_state.game_index = 0
                st.session_state.wrong_answers = []
                st.session_state.is_finished = False
                st.session_state.quiz_feedback = None

            # 檢查是否測驗結束
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
                
                # 如果已經作答過（顯示回饋結果與進入下一題按鈕）
                if st.session_state.get("quiz_feedback"):
                    fb = st.session_state.quiz_feedback
                    if fb["type"] == "success":
                        st.success(fb["msg"])
                    else:
                        st.error(fb["msg"])
                    
                    st.markdown(f"### ❌ 目前累積錯誤題數：`{len(st.session_state.wrong_answers)}` 題")
                    
                    if st.button("➡️ 進入下一題", type="primary", use_container_width=True):
                        st.session_state.quiz_feedback = None
                        st.session_state.game_index += 1
                        st.rerun()
                else:
                    # 尚未作答時的輸入框與按鈕（利用隨題號改變的 key 確保每次切換絕對乾淨無殘留）
                    curr_idx = st.session_state.game_index
                    input_key = f"input_box_v3_{curr_idx}"
                    
                    user_ans = st.text_input("請輸入您的拼寫答案：", key=input_key).strip().lower()
                    
                    col_btn1, col_btn2 = st.columns(2)
                    with col_btn1:
                        if st.button("🚀 送出答案", type="primary", use_container_width=True):
                            if user_ans == target_word.lower():
                                st.session_state.quiz_feedback = {"type": "success", "msg": f"🎉 答對了！就是 `{target_word}`"}
                            else:
                                if current_item not in st.session_state.wrong_answers:
                                    st.session_state.wrong_answers.append(current_item)
                                st.session_state.quiz_feedback = {
                                    "type": "error", 
                                    "msg": f"❌ 答錯囉！正確答案是：`{target_word}` (目前累積錯誤題數：{len(st.session_state.wrong_answers)} 題)"
                                }
                            st.rerun()
                            
                    with col_btn2:
                        if st.button("⏭️ 略過本題", use_container_width=True):
                            if current_item not in st.session_state.wrong_answers:
                                st.session_state.wrong_answers.append(current_item)
                            st.session_state.quiz_feedback = {
                                "type": "error", 
                                "msg": f"⏩ 已略過。本題正確答案為：`{target_word}` (目前累積錯誤題數：{len(st.session_state.wrong_answers)} 題)"
                            }
                            st.rerun()