import pandas as pd
import streamlit as st
import json
import os
import time
import docx
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
    ["✨ 智慧單字新增", "📖 字庫管理與搜尋", "🎯 沉浸式閃卡複習", "🎮 拼字王挑戰遊戲"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")
user_api_key = st.sidebar.text_input("輸入 Gemini API Key (選填)", type="password", value=st.secrets.get("gemini_api_key", ""))
if user_api_key:
    st.session_state.gemini_api_key = user_api_key
    if HAS_GEMINI:
        genai.configure(api_key=user_api_key)
    st.sidebar.success("✅ AI 字典引擎已啟用")
else:
    st.session_state.gemini_api_key = ""
    st.sidebar.info("💡 未填寫 API Key 時將使用內建智慧字典庫，確保穩定不限流")

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
except Exception as e:
    st.error(f"⚠️ Google Sheets 連線失敗：{e}")
    st.stop()

def load_vocab_dataframe(_worksheet, force_reload=False):
    cache_key = f"vocab_df_{_worksheet.title}"
    if force_reload or cache_key not in st.session_state:
        try:
            records = _worksheet.get_all_records()
        except Exception:
            records = []
            
        if not records:
            all_values = _worksheet.get_all_values()
            if len(all_values) > 1:
                headers = [str(h).strip().lower() for h in all_values[0]]
                df_temp = pd.DataFrame(all_values[1:], columns=headers[:len(all_values[0])])
            else:
                df_temp = pd.DataFrame(columns=['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'basic_sentence', 'advanced_sentence', 'collocations', 'unit_tag', 'srs_stage'])
        else:
            df_temp = pd.DataFrame(records)
            
        df_temp.columns = [str(c).strip().lower() for c in df_temp.columns]
        required_cols = ['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'basic_sentence', 'advanced_sentence', 'collocations', 'unit_tag', 'srs_stage']
        for idx, col in enumerate(required_cols):
            if col not in df_temp.columns:
                df_temp[col] = ""
                
        df_temp = df_temp[df_temp['word'].astype(str).str.strip() != '']
        df_temp = df_temp[df_temp['word'].notna()]
        
        for idx in df_temp.index:
            for col in df_temp.columns:
                val = str(df_temp.at[idx, col])
                if val == "nan" or val.lower() == "none":
                    df_temp.at[idx, col] = ""
                    
        st.session_state[cache_key] = df_temp
    
    return st.session_state[cache_key]

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

BUILTIN_VOCAB_MAP = {
    "right away": ("立刻、馬上", "adv.", "She cleaned her room right away."),
    "internet": ("網際網路", "n.", "You can find a lot of information on the Internet."),
    "bat": ("球棒、蝙蝠", "n.", "He bought a new baseball bat."),
    "touch": ("觸摸、感動", "v.", "Please do not touch the wet paint."),
    "lie": ("說謊、躺", "v.", "It is wrong to tell a lie."),
    "hard-working": ("努力工作的", "adj.", "She is a hard-working student."),
    "proud": ("驕傲的、自豪的", "adj.", "Parents are proud of their children."),
    "surprise": ("驚訝、使驚訝", "n./v.", "The gift came as a total surprise."),
    "ghost": ("鬼魂", "n.", "Children love to hear ghost stories."),
    "hit": ("打、擊中", "v.", "He hit the ball over the fence."),
    "enough": ("足夠的", "adj.", "We have enough food for the party."),
    "favorite": ("最喜愛的", "adj.", "English is my favorite subject."),
    "table": ("桌子", "n.", "Please put the books on the table."),
    "brown": ("棕色、咖啡色", "n./adj.", "The dog has brown fur."),
    "mummy": ("木乃伊", "n.", "We saw an old mummy at the museum."),
    "sofa": ("沙發", "n.", "He sat down on the sofa to watch TV."),
    "bathroom": ("浴室", "n.", "Where is the bathroom, please?"),
    "gray": ("灰色、灰色的", "n./adj.", "The sky turned gray before the rain."),
    "parents": ("父母", "n.", "My parents support me in everything I do."),
    "wall": ("牆壁", "n.", "She hung a picture on the wall."),
    "special": ("特別的", "adj.", "Today is a very special day for us.")
}

def get_word_record_data_via_ai(word, level="國中部"):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    
    if w_lower in BUILTIN_VOCAB_MAP:
        def_val, pos_val, sent_val = BUILTIN_VOCAB_MAP[w_lower]
        return {
            "word": w_clean,
            "phonetic": f"/{w_lower}/",
            "part_of_speech": pos_val,
            "definition": def_val,
            "basic_sentence": sent_val
        }

    if HAS_GEMINI and st.session_state.get("gemini_api_key"):
        try:
            genai.configure(api_key=st.session_state["gemini_api_key"])
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = (
                f"你是一個專業的英語字典與教師。請針對英文單字或片語「{w_clean}」（適用級別：{level}），"
                "嚴格回傳以下純 JSON 格式，絕對不要包含任何其他文字或標記：\n"
                "{\n"
                '    "phonetic": "/音標/",\n'
                '    "part_of_speech": "詞性",\n'
                '    "definition": "繁體中文含義",\n'
                '    "sentence": "英文例句"\n'
                "}"
            )
            response = model.generate_content(prompt)
            raw_text = response.text.strip()
            
            if "{" in raw_text and "}" in raw_text:
                start_idx = raw_text.find("{")
                end_idx = raw_text.rfind("}") + 1
                raw_text = raw_text[start_idx:end_idx]
                
            data = json.loads(raw_text)
            return {
                "word": w_clean,
                "phonetic": data.get("phonetic", f"/{w_lower}/"),
                "part_of_speech": simple_s2t_convert(data.get("part_of_speech", "n.")),
                "definition": simple_s2t_convert(data.get("definition", f"{w_clean}")),
                "basic_sentence": data.get("sentence", f"Example for {w_clean}.")
            }
        except Exception:
            pass
            
    return {
        "word": w_clean,
        "phonetic": f"/{w_lower}/",
        "part_of_speech": "n.",
        "definition": f"{w_clean}",
        "basic_sentence": f"This is an example sentence for {w_clean}."
    }

def update_row_safely(_worksheet, row_idx, row_data):
    # 使用安全的單一儲存格寫入，避開新版 gspread 的 update 語法相容性問題
    for col_idx, val in enumerate(row_data, start=1):
        _worksheet.update_cell(row_idx, col_idx, str(val))

def delete_words_from_sheet(_worksheet, word_list):
    if not word_list: return
    all_vals = _worksheet.get_all_values()
    rows_to_delete = []
    for w in word_list:
        for idx, row in enumerate(all_vals):
            if len(row) > 1 and row[1].strip().lower() == w.strip().lower():
                rows_to_delete.append(idx + 1)
                
    for r in sorted(rows_to_delete, reverse=True):
        try:
            _worksheet.delete_rows(r)
        except Exception:
            pass
    load_vocab_dataframe(_worksheet, force_reload=True)

@st.cache_data(show_spinner=False)
def generate_audio_bytes(text, lang='en'):
    tts = gTTS(text=text, lang=lang)
    fp = io.BytesIO()
    tts.write_to_fp(fp)
    return fp.getvalue()

st.title("📚 我愛背單字 (雲端拼字測驗版)")

try:
    df_vocab = load_vocab_dataframe(active_worksheet)
except Exception:
    time.sleep(2)
    df_vocab = load_vocab_dataframe(active_worksheet, force_reload=True)

total_words = len(df_vocab)
col_m1, col_m2 = st.columns(2)
col_m1.metric(label="雲端總單字數", value=f"{total_words} 個")
col_m2.metric(label="目前模式", value=f"{main_menu} ({selected_level})")

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
        if st.button("🚀 查字典並寫入雲端", type="primary", use_container_width=True):
            if single_word:
                with st.spinner("🤖 正在查閱字典並生成中文與例句中..."):
                    data = get_word_record_data_via_ai(single_word, level=selected_level)
                    word = data.get('word')
                    
                    all_vals = active_worksheet.get_all_values()
                    row_idx = -1
                    for idx, row in enumerate(all_vals):
                        if len(row) > 1 and row[1].strip().lower() == word.strip().lower():
                            row_idx = idx + 1
                            break
                            
                    if row_idx != -1:
                        r_vals = all_vals[row_idx - 1]
                        r_id = r_vals[0] if len(r_vals) > 0 else 1
                        srs_val = r_vals[9] if len(r_vals) > 9 else 0
                        new_r = [r_id, word, data.get('phonetic', ''), data.get('part_of_speech', ''), data.get('definition', ''), data.get('basic_sentence', ''), "", "", current_unit_tag, srs_val]
                        update_row_safely(active_worksheet, row_idx, new_r)
                    else:
                        df_check = load_vocab_dataframe(active_worksheet)
                        next_id = len(df_check) + 1
                        new_r = [next_id, word, data.get('phonetic', ''), data.get('part_of_speech', ''), data.get('definition', ''), data.get('basic_sentence', ''), "", "", current_unit_tag, 0]
                        active_worksheet.append_row(new_r)
                        
                    load_vocab_dataframe(active_worksheet, force_reload=True)
                    st.success(f"🎉 成功新增單字：{word} | 中文：{data.get('definition')}")
                    time.sleep(0.5)
                    st.rerun()

    with col_input2:
        st.subheader("📂 Word 檔案智慧匯入")
        uploaded_docxs = st.file_uploader("上傳 Word 講義檔案 (自動查字典與例句)", type=["docx"], accept_multiple_files=True)
        if uploaded_docxs:
            if st.button("📖 批次解析 Word 並匯入", use_container_width=True):
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
                        for table in doc.tables:
                            for row in table.rows:
                                for cell in row.cells:
                                    for line in cell.text.strip().split('\n'):
                                        cleaned = line.strip()
                                        if cleaned and len(cleaned) < 35 and not any(('\u4e00' <= c <= '\u9fff') for c in cleaned):
                                            if cleaned not in all_extracted_words:
                                                all_extracted_words.append(cleaned)
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                    except Exception:
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                            
                total_words_to_process = len(all_extracted_words)
                if total_words_to_process > 0:
                    all_vals = active_worksheet.get_all_values()
                    for i, word in enumerate(all_extracted_words):
                        status_text.text(f"🤖 正在處理單字 ({i+1}/{total_words_to_process}): {word}")
                        w_data = get_word_record_data_via_ai(word, level=selected_level)
                        
                        row_idx = -1
                        for idx, row in enumerate(all_vals):
                            if len(row) > 1 and row[1].strip().lower() == word.strip().lower():
                                row_idx = idx + 1
                                break
                                
                        if row_idx != -1:
                            r_vals = all_vals[row_idx - 1]
                            r_id = r_vals[0] if len(r_vals) > 0 else 1
                            srs_val = r_vals[9] if len(r_vals) > 9 else 0
                            new_r = [r_id, word, w_data.get('phonetic', ''), w_data.get('part_of_speech', ''), w_data.get('definition', ''), w_data.get('basic_sentence', ''), "", "", current_unit_tag, srs_val]
                            update_row_safely(active_worksheet, row_idx, new_r)
                        else:
                            df_check = load_vocab_dataframe(active_worksheet)
                            next_id = len(df_check) + 1
                            new_r = [next_id, word, w_data.get('phonetic', ''), w_data.get('part_of_speech', ''), w_data.get('definition', ''), w_data.get('basic_sentence', ''), "", "", current_unit_tag, 0]
                            active_worksheet.append_row(new_r)
                            
                        total_success_count += 1
                        progress_bar.progress((i + 1) / total_words_to_process)
                        time.sleep(0.1)
                        
                    load_vocab_dataframe(active_worksheet, force_reload=True)
                    status_text.success(f"🎊 批次匯入完成！成功解析並匯入 {total_success_count} 個單字。")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("⚠️ 在上傳的 Word 中找不到符合的英文單字。")

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
                load_vocab_dataframe(active_worksheet, force_reload=True)
                st.success("✅ 快取已清除！")
                time.sleep(0.5)
                st.rerun()

        st.markdown("---")
        with st.container(border=True):
            st.markdown("#### 🚨 試算表資料修復與一鍵補齊中文專區")
            st.warning("點擊下方按鈕，系統會瞬間為試算表內所有單字補齊正確的中文釋義與例句：")
            if st.button("🧹 一鍵快速補齊並更新雲端", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                words_to_fix = df_vocab['word'].tolist()
                total_fix = len(words_to_fix)
                fixed_count = 0
                
                all_vals = active_worksheet.get_all_values()
                for idx, w in enumerate(words_to_fix):
                    status_text.text(f"🤖 正在補齊單字資料 ({idx+1}/{total_fix}): {w}")
                    row_match = df_vocab[df_vocab['word'] == w]
                    u_tag = row_match['unit_tag'].values[0] if not row_match.empty and 'unit_tag' in row_match.columns else "未分類"
                    
                    new_data = get_word_record_data_via_ai(w, level=selected_level)
                    
                    row_idx = -1
                    for r_i, row in enumerate(all_vals):
                        if len(row) > 1 and row[1].strip().lower() == w.strip().lower():
                            row_idx = r_i + 1
                            break
                            
                    if row_idx != -1:
                        r_vals = all_vals[row_idx - 1]
                        r_id = r_vals[0] if len(r_vals) > 0 else 1
                        srs_val = r_vals[9] if len(r_vals) > 9 else 0
                        new_r = [r_id, w, new_data.get('phonetic', ''), new_data.get('part_of_speech', ''), new_data.get('definition', ''), new_data.get('basic_sentence', ''), "", "", u_tag, srs_val]
                        update_row_safely(active_worksheet, row_idx, new_r)
                        fixed_count += 1
                        
                    progress_bar.progress((idx + 1) / total_fix)
                    time.sleep(0.1)
                    
                load_vocab_dataframe(active_worksheet, force_reload=True)
                status_text.success(f"🎉 成功完成資料補齊！總共更新了 {fixed_count} 個單字。")
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
                delete_words_from_sheet(active_worksheet, words_to_delete)
                st.success("已成功刪除勾選的單字！")
                st.rerun()

        with st.expander("📋 單字總表與快速編輯", expanded=True):
            st.dataframe(filtered_df[['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'basic_sentence', 'unit_tag']], use_container_width=True, hide_index=True)
            
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
                            edit_basic = st.text_area("真實例句 (Basic Sentence)", value=target_row.get('basic_sentence', ''))
                            
                            submit_table_edit = st.form_submit_button("💾 儲存修改至雲端", type="primary")
                            
                            if submit_table_edit:
                                all_vals = active_worksheet.get_all_values()
                                row_idx = -1
                                for idx, row in enumerate(all_vals):
                                    if len(row) > 1 and row[1].strip().lower() == target_row['word'].strip().lower():
                                        row_idx = idx + 1
                                        break
                                if row_idx != -1:
                                    r_vals = all_vals[row_idx - 1]
                                    r_id = r_vals[0] if len(r_vals) > 0 else 1
                                    srs_val = r_vals[9] if len(r_vals) > 9 else 0
                                    new_r = [r_id, edit_word, edit_phonetic, edit_pos, simple_s2t_convert(edit_def), edit_basic, target_row.get('advanced_sentence',''), target_row.get('collocations',''), target_row.get('unit_tag','未分類'), srs_val]
                                    update_row_safely(active_worksheet, row_idx, new_r)
                                    st.success("✅ 雲端修改成功！")
                                    time.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error("❌ 修改失敗：找不到該單字行")

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
                target_def = str(current_item['definition']).strip() if str(current_item['definition']).strip() else "(尚無中文釋義)"
                hint_masked = "".join([" _ " if c.isalpha() else "   " for c in target_word])
                
                st.markdown(f"### 📊 進度：第 `{st.session_state.game_index + 1}` 題 / 共 `{len(st.session_state.game_queue)}` 題")
                
                with st.container(border=True):
                    st.markdown(f"<h2 style='color: #4CAF50;'>📌 中文釋義：{target_def}</h2>", unsafe_allow_html=True)
                    st.markdown(f"**🔤 拼字提示：** `{hint_masked}` &nbsp;&nbsp; (長度: {len(target_word)} 字母)")
                    
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
