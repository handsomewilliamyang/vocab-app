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
    st.error("⚠️ Google Sheets 連線設定錯誤：" + str(e))
    st.stop()

st.sidebar.markdown("<h2 style='font-size: 24px;'>⚙️ 系統導覽與設定</h2>", unsafe_allow_html=True)
st.sidebar.markdown("---")
main_menu = st.sidebar.radio(
    "選擇主要功能：",
    ["✨ 智慧單字新增", "📖 字庫管理與搜尋", "🎯 沉浸式閃卡複習", "🎮 拼字王挑戰遊戲"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")
user_api_key = st.sidebar.text_input("輸入 Gemini API Key (必填以啟用 AI 字典)", type="password", value=st.secrets.get("gemini_api_key", ""))
if user_api_key:
    st.session_state.gemini_api_key = user_api_key
    if HAS_GEMINI:
        try:
            genai.configure(api_key=user_api_key)
            st.sidebar.success("✅ AI 字典引擎已啟用")
        except Exception as ex:
            st.sidebar.error(f"⚠️ API Key 設定失敗：{ex}")
else:
    st.session_state.gemini_api_key = ""
    st.sidebar.warning("⚠️ 請務必輸入 API Key 才能自動查字典")

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
        st.sidebar.warning("⚠️ 找不到分頁，已自動切換至：" + active_worksheet.title)
except Exception as e:
    st.error("⚠️ Google Sheets 連線失敗：" + str(e))
    st.stop()

st.sidebar.markdown("---")
st.sidebar.info("💡 雲端同步中：已連線至工作表【" + active_worksheet.title + "】")

def load_vocab_dataframe(_worksheet, force_reload=False):
    cache_key = "vocab_df_" + _worksheet.title
    if force_reload or cache_key not in st.session_state:
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
        
        for idx, row in df_temp.iterrows():
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

# 🌟 強化版 AI 字典查詢：若發生錯誤會直接回傳詳細錯誤訊息供診斷
def get_word_record_data_via_ai(word, level="國中部"):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    
    if not HAS_GEMINI or not st.session_state.get("gemini_api_key"):
        return {
            "word": w_clean,
            "phonetic": "/" + w_lower + "/",
            "part_of_speech": "n.",
            "definition": f"{w_clean} (尚未啟用 API Key)",
            "basic_sentence": f"Please enter Gemini API Key in sidebar."
        }

    try:
        genai.configure(api_key=st.session_state["gemini_api_key"])
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = (
            f"你是一個專業的英語字典與教師。請針對英文單字或片語「{w_clean}」（適用級別：{level}），"
            "嚴格回傳以下純 JSON 格式（絕對不要包含任何 markdown 程式碼標記如 ```json）：\n"
            "{\n"
            '    "phonetic": "/音標/",\n'
            '    "part_of_speech": "詞性 (例如 n., v., adj.,phr.)",\n'
            '    "definition": "精準流暢的繁體中文含義",\n'
            '    "sentence": "實用且道地的英文例句"\n'
            "}"
        )
        response = model.generate_content(prompt)
        raw_text = response.text.strip()
        
        raw_text = re.sub(r"^```(json)?", "", raw_text, flags=re.IGNORECASE).strip()
        raw_text = re.sub(r"```$", "", raw_text).strip()
        
        data = json.loads(raw_text)
        
        phonetic = data.get("phonetic", "/" + w_lower + "/")
        pos = data.get("part_of_speech", "n.")
        definition = data.get("definition", w_clean)
        sentence = data.get("sentence", f"Example sentence for {w_clean}.")
        
        return {
            "word": w_clean,
            "phonetic": phonetic if phonetic else "/" + w_lower + "/",
            "part_of_speech": simple_s2t_convert(pos),
            "definition": simple_s2t_convert(definition),
            "basic_sentence": sentence
        }
    except Exception as e:
        return {
            "word": w_clean,
            "phonetic": "/" + w_lower + "/",
            "part_of_speech": "err",
            "definition": f"AI錯誤: {str(e)[:40]}",
            "basic_sentence": f"Error during AI generation for {w_clean}."
        }

def update_single_word_in_sheet(_worksheet, target_word, new_word, new_phonetic, new_pos, new_def, new_basic, new_adv, new_coll):
    try:
        df = load_vocab_dataframe(_worksheet)
        row_idx = df.index[df['word'] == target_word].tolist()[0] + 2
        
        row_values = _worksheet.row_values(row_idx)
        row_id = row_values[0] if len(row_values) > 0 else 1
        unit_tag = row_values[8] if len(row_values) > 8 else "未分類"
        srs = row_values[9] if len(row_values) > 9 else 0
        
        new_row = [row_id, new_word, new_phonetic, new_pos, simple_s2t_convert(new_def), new_basic, new_adv, new_coll, unit_tag, srs]
        _worksheet.update('A' + str(row_idx) + ':J' + str(row_idx), [new_row])
        time.sleep(0.5)
        load_vocab_dataframe(_worksheet, force_reload=True)
        return True, "成功"
    except Exception as e:
        return False, str(e)

def delete_words_from_sheet(_worksheet, word_list):
    if not word_list: return
    df = load_vocab_dataframe(_worksheet)
    rows_to_delete = sorted([df.index[df['word'] == w].tolist()[0] + 2 for w in word_list if w in df['word'].values], reverse=True)
    for r in rows_to_delete:
        _worksheet.delete_rows(r)
        time.sleep(0.3)
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
with col_m1:
    st.metric(label="雲端總單字數", value=str(total_words) + " 個")
with col_m2:
    st.metric(label="目前模式", value=main_menu + " (" + selected_level + ")")

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
        
    current_unit_tag = semester + " > " + unit
    st.info("📌 即時同步至 Google Sheets 【" + active_worksheet.title + "】分頁：**" + current_unit_tag + "**")
    st.markdown("---")

    col_input1, col_input2 = st.columns(2, gap="large")
    with col_input1:
        st.subheader("📝 單筆快速建檔 (AI 字典)")
        single_word = st.text_input("輸入想要學習的英文單字：", placeholder="例如：resilient")
        if st.button("🚀 AI 查字典並寫入雲端", type="primary", use_container_width=True):
            if single_word:
                with st.spinner("🤖 AI 正在查閱字典並生成中文與例句中..."):
                    data = get_word_record_data_via_ai(single_word, level=selected_level)
                    df_check = load_vocab_dataframe(active_worksheet)
                    word = data.get('word')
                    if not df_check.empty and word in df_check['word'].values:
                        r_idx = df_check.index[df_check['word'] == word].tolist()[0] + 2
                        r_vals = active_worksheet.row_values(r_idx)
                        r_id = r_vals[0] if len(r_vals) > 0 else 1
                        srs_val = r_vals[9] if len(r_vals) > 9 else 0
                        new_r = [r_id, word, data.get('phonetic', ''), data.get('part_of_speech', ''), data.get('definition', ''), data.get('basic_sentence', ''), "", "", current_unit_tag, srs_val]
                        active_worksheet.update('A' + str(r_idx) + ':J' + str(r_idx), [new_r])
                    else:
                        next_id = len(df_check) + 1
                        new_r = [next_id, word, data.get('phonetic', ''), data.get('part_of_speech', ''), data.get('definition', ''), data.get('basic_sentence', ''), "", "", current_unit_tag, 0]
                        active_worksheet.append_row(new_r)
                    load_vocab_dataframe(active_worksheet, force_reload=True)
                    st.success("🎉 成功新增單字：" + word + " | 中文：" + data.get('definition'))
                    time.sleep(0.5)
                    st.rerun()

    with col_input2:
        st.subheader("📂 Word 檔案智慧查字典匯入")
        uploaded_docxs = st.file_uploader("上傳 Word 講義檔案 (自動查字典與例句)", type=["docx"], accept_multiple_files=True)
        if uploaded_docxs:
            if st.button("📖 AI 批次解析 Word 並查字典", use_container_width=True):
                total_success_count = 0
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                all_extracted_words = []
                for uploaded_docx in uploaded_docxs:
                    temp_path = "temp_" + uploaded_docx.name
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
                                            if cleaned not in all_extracted_words:
                                                all_extracted_words.append(cleaned)
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                    except Exception:
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                            
                total_words_to_process = len(all_extracted_words)
                if total_words_to_process > 0:
                    for i, word in enumerate(all_extracted_words):
                        status_text.text("🤖 AI 正在查字典中 (" + str(i+1) + "/" + str(total_words_to_process) + "): " + word)
                        w_data = get_word_record_data_via_ai(word, level=selected_level)
                        
                        df_check = load_vocab_dataframe(active_worksheet)
                        if not df_check.empty and word in df_check['word'].values:
                            r_idx = df_check.index[df_check['word'] == word].tolist()[0] + 2
                            r_vals = active_worksheet.row_values(r_idx)
                            r_id = r_vals[0] if len(r_vals) > 0 else 1
                            srs_val = r_vals[9] if len(r_vals) > 9 else 0
                            new_r = [r_id, word, w_data.get('phonetic', ''), w_data.get('part_of_speech', ''), w_data.get('definition', ''), w_data.get('basic_sentence', ''), "", "", current_unit_tag, srs_val]
                            active_worksheet.update('A' + str(r_idx) + ':J' + str(r_idx), [new_r])
                        else:
                            next_id = len(df_check) + 1
                            new_r = [next_id, word, w_data.get('phonetic', ''), w_data.get('part_of_speech', ''), w_data.get('definition', ''), w_data.get('basic_sentence', ''), "", "", current_unit_tag, 0]
                            active_worksheet.append_row(new_r)
                        
                        total_success_count += 1
                        progress_bar.progress((i + 1) / total_words_to_process)
                        time.sleep(0.8)
                        
                    load_vocab_dataframe(active_worksheet, force_reload=True)
                    status_text.success("🎊 批次匯入完成！成功透過 AI 字典解析並匯入 " + str(total_success_count) + " 個單字與例句。")
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
                st.success("✅ 快取已清除，已重新載入雲端資料！")
                time.sleep(0.5)
                st.rerun()

        st.markdown("---")
        with st.container(border=True):
            st.markdown("#### 🚨 試算表資料修復與一鍵補齊中文專區")
            st.warning("點擊下方按鈕，AI 會為試算表內所有單字**重新查字典，自動填入正確的中文釋義與例句**：")
            if st.button("🧹 強制啟動 AI 字典全面補齊並更新雲端", type="primary", use_container_width=True):
                if not st.session_state.get("gemini_api_key"):
                    st.error("❌ 請先在左側邊欄輸入您的 Gemini API Key！")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    words_to_fix = df_vocab['word'].tolist()
                    total_fix = len(words_to_fix)
                    fixed_count = 0
                    
                    for idx, w in enumerate(words_to_fix):
                        status_text.text("🤖 AI 正在補齊單字資料 (" + str(idx+1) + "/" + str(total_fix) + "): " + w)
                        row_match = df_vocab[df_vocab['word'] == w]
                        u_tag = row_match['unit_tag'].values[0] if not row_match.empty and 'unit_tag' in row_match.columns else "未分類"
                        
                        new_data = get_word_record_data_via_ai(w, level=selected_level)
                        df_check = load_vocab_dataframe(active_worksheet)
                        if not df_check.empty and w in df_check['word'].values:
                            r_idx = df_check.index[df_check['word'] == w].tolist()[0] + 2
                            r_vals = active_worksheet.row_values(r_idx)
                            r_id = r_vals[0] if len(r_vals) > 0 else 1
                            srs_val = r_vals[9] if len(r_vals) > 9 else 0
                            new_r = [r_id, w, new_data.get('phonetic', ''), new_data.get('part_of_speech', ''), new_data.get('definition', ''), new_data.get('basic_sentence', ''), "", "", u_tag, srs_val]
                            active_worksheet.update('A' + str(r_idx) + ':J' + str(r_idx), [new_r])
                            fixed_count += 1
                        progress_bar.progress((idx + 1) / total_fix)
                        time.sleep(1.0)
                        
                    load_vocab_dataframe(active_worksheet, force_reload=True)
                    status_text.success("🎉 成功完成 AI 資料補齊！總共更新了 " + str(fixed_count) + " 個單字。")
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
                    word_options = {row['word'] + " (" + (row['definition'] if row['definition'] else '無中文') + ")": row for _, row in filtered_df.iterrows()}
                    selected_option = st.selectbox("選擇要編輯的單字：", list(word_options.keys()), key="table_edit_select")
                    
                    if selected_option:
                        target_row = word_options[selected_option]
                        with st.form(key="table_edit_form_" + str(target_row['word'])):
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
                                    st.error("❌ 修改失敗：" + msg)

elif main_menu == "🎯 沉浸式閃卡複習":
    if df_vocab.empty:
        st.warning("📭 目前雲端沒有單字！")
    else:
        if "flashcard_index" not in st.session_state: st.session_state.flashcard_index = 0
        total_count = len(df_vocab)
        st.session_state.flashcard_index = st.session_state.flashcard_index % total_count
        row = df_vocab.iloc[st.session_state.flashcard_index]
        
        with st.container(border=True):
            st.markdown("<h1 style='text-align: center; font-size: 54px;'>🔤 " + str(row['word']) + "</h1>", unsafe_allow_html=True)
            st.markdown("<p style='text-align: center; color: gray;'>" + str(row.get('phonetic','')) + " | " + str(row.get('part_of_speech','')) + "</p>", unsafe_allow_html=True)
            
        with st.expander("💡 詳細釋義與真實例句", expanded=True):
            st.markdown("**中文釋義：** " + str(row['definition']))
            st.markdown("**例句：** " + str(row.get('basic_sentence','')))
        
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
                        "msg": "⏩ 已略過。正確答案是：`" + target_word + "`"
                    }
                else:
                    if user_ans == target_word.lower():
                        st.session_state.last_feedback = {
                            "type": "success", 
                            "msg": "🎉 上題答對了！就是 `" + target_word + "`"
                        }
                    else:
                        if current_item not in st.session_state.wrong_answers:
                            st.session_state.wrong_answers.append(current_item)
                        st.session_state.last_feedback = {
                            "type": "error", 
                            "msg": "❌ 上題答錯囉！正確答案是：`" + target_word + "`"
                        }
                
                st.session_state.game_index += 1
                st.session_state.user_spelling_input = ""

            if st.session_state.game_index >= len(st.session_state.game_queue):
                st.session_state.is_finished = True

            if st.session_state.get("is_finished", False):
                st.balloons()
                st.markdown("## 🎉 測驗圓滿結束！")
                total_q = len(st.session_state.game_queue)
                wrong_q = len(st.
