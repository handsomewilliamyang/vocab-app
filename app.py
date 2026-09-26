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
    page_title="我愛背單字 (雲端同步版)",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -------------------------------------------------------------------------
# 1. Google Sheets 連線初始化
# -------------------------------------------------------------------------
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
    st.error(f"⚠️ Google Sheets 連線設定錯誤，請檢查 secrets.toml！錯誤訊息：{e}")
    st.stop()

# -------------------------------------------------------------------------
# 2. 側邊欄導覽與級別切換
# -------------------------------------------------------------------------
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
    st.sidebar.success("✅ AI 引擎已啟用 (連線正常)")
else:
    st.session_state.gemini_api_key = ""
    st.sidebar.warning("⚠️ 未輸入 API Key，將使用免費字典與基礎翻譯。")

st.sidebar.markdown("---")
st.sidebar.markdown("<h3 style='font-size: 20px;'>📂 學習階段 / 級別分類</h3>", unsafe_allow_html=True)
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
    st.error(f"⚠️ 找不到名為「{current_sheet_name}」的工作表，請確認試算表底下分頁名稱正確。")
    st.stop()

st.sidebar.markdown("---")
st.sidebar.info(f"💡 雲端同步中：已連線至工作表【{current_sheet_name}】")

# -------------------------------------------------------------------------
# 3. 核心工具與翻譯/AI 強化函式
# -------------------------------------------------------------------------
@st.cache_data(ttl=2)
def get_vocab_from_sheets(_worksheet):
    records = _worksheet.get_all_records()
    if not records:
        return pd.DataFrame(columns=['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'basic_sentence', 'advanced_sentence', 'collocations', 'unit_tag', 'srs_stage'])
    return pd.DataFrame(records)

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
    bad_phrases = ["example sentence using", "we can easily see how", "people frequently use", "this is an example"]
    if any(bp in text.lower() for bp in bad_phrases):
        return ""
    return text

def auto_translate_english_to_chinese(word):
    if HAS_GEMINI and st.session_state.get('gemini_api_key'):
        try:
            genai.configure(api_key=st.session_state.gemini_api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"Provide a concise Traditional Chinese definition (釋義) and part of speech for the English word '{word}'. Format: [詞性] 中文釋義 (例如: n. 蘋果)"
            response = model.generate_content(prompt)
            if response.text:
                return simple_s2t_convert(response.text.strip())
        except:
            pass
    return "(待補充中文)"

def fetch_sentence(word):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    search_root = w_lower[:4] if len(w_lower) >= 4 else w_lower

    if HAS_GEMINI and st.session_state.get('gemini_api_key'):
        try:
            genai.configure(api_key=st.session_state.gemini_api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"Write a single, practical, everyday English sentence using the word '{w_clean}'. Return ONLY the English sentence. Do not include quotes or translations."
            response = model.generate_content(prompt)
            if response.text:
                clean_res = response.text.strip().replace('"', '').replace('\n', '')
                if search_root in clean_res.lower():
                    return clean_res
        except:
            pass
    return ""

def get_word_record_data(word):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    translated_zh = auto_translate_english_to_chinese(w_clean)
    real_sent = fetch_sentence(w_clean)
    return {
        "word": w_clean,
        "phonetic": f"/{w_lower}/",
        "part_of_speech": "n. / v. / adj.",
        "definition": simple_s2t_convert(translated_zh),
        "basic_sentence": real_sent,
        "advanced_sentence": "Students should learn this word.",
        "collocations": f"common {w_clean}"
    }

def upsert_word_to_sheet(data, unit_tag, _worksheet):
    try:
        df = get_vocab_from_sheets(_worksheet)
        word = data.get('word')
        raw_def = data.get('definition', '')
        b_sent = clean_sentence(data.get('basic_sentence'))

        if not df.empty and word in df['word'].values:
            # 更新現有單字
            row_idx = df.index[df['word'] == word].tolist()[0] + 2
            row_values = _worksheet.row_values(row_idx)
            row_id = row_values[0] if len(row_values) > 0 else 1
            srs = row_values[9] if len(row_values) > 9 else 0
            new_row = [row_id, word, data.get('phonetic', ''), data.get('part_of_speech', ''), raw_def, b_sent, data.get('advanced_sentence',''), data.get('collocations',''), unit_tag, srs]
            _worksheet.update(f'A{row_idx}:J{row_idx}', [new_row])
        else:
            # 新增單字，自動編排 ID
            next_id = int(pd.to_numeric(df['id'], errors='coerce').max()) + 1 if not df.empty and 'id' in df.columns and not pd.isna(pd.to_numeric(df['id'], errors='coerce').max()) else len(df) + 1
            new_row = [next_id, word, data.get('phonetic', ''), data.get('part_of_speech', ''), raw_def, b_sent, data.get('advanced_sentence',''), data.get('collocations',''), unit_tag, 0]
            _worksheet.append_row(new_row)
            
        get_vocab_from_sheets.clear()
        return True
    except Exception as e:
        print(e)
        return False

def update_single_word_in_sheet(_worksheet, target_word, new_word, new_phonetic, new_pos, new_def, new_basic, new_adv, new_coll):
    try:
        df = get_vocab_from_sheets(_worksheet)
        b_sent = clean_sentence(new_basic)
        
        row_idx = df.index[df['word'] == target_word].tolist()[0] + 2
        
        # 保留原有的 ID 與進度標籤
        row_values = _worksheet.row_values(row_idx)
        row_id = row_values[0] if len(row_values) > 0 else 1
        unit_tag = row_values[8] if len(row_values) > 8 else "未分類"
        srs = row_values[9] if len(row_values) > 9 else 0
        
        _worksheet.update(f'A{row_idx}:J{row_idx}', [[row_id, new_word, new_phonetic, new_pos, simple_s2t_convert(new_def), b_sent, new_adv, new_coll, unit_tag, srs]])
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

# -------------------------------------------------------------------------
# 4. 主畫面佈局
# -------------------------------------------------------------------------
st.title("📚 我愛背單字 (雲端同步版)")

df_vocab = get_vocab_from_sheets(active_worksheet)
total_words = len(df_vocab)

clean_menu_name = re.sub(r'[^\w\s]', '', main_menu).strip()
top_right_display = f"{clean_menu_name} ({selected_level})"

col_m1, col_m2 = st.columns(2)
with col_m1:
    st.metric(label="雲端總單字數", value=f"{total_words} 個")
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
    st.info(f"📌 目前新增的單字將即時同步至 Google Sheets 【{current_sheet_name}】分頁的：**{current_unit_tag}**")
    st.markdown("---")

    col_input1, col_input2 = st.columns(2, gap="large")
    
    with col_input1:
        st.subheader("📝 單筆快速建檔")
        single_word = st.text_input("輸入想要學習的英文單字：", placeholder="例如：resilient")
        if st.button("🚀 寫入雲端單字庫", type="primary", use_container_width=True):
            if not single_word:
                st.warning("請先輸入單字！")
            else:
                word_data = get_word_record_data(single_word.strip())
                if word_data:
                    if upsert_word_to_sheet(word_data, current_unit_tag, active_worksheet):
                        st.success(f"🎉 成功新增單字：{single_word}（已同步至雲端）")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error("❌ 寫入雲端失敗！")

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
                    except Exception as e:
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
            if st.button("🔄 透過 AI 自動掃描補齊翻譯與例句", type="primary", use_container_width=True):
                progress_bar = st.progress(0)
                status_text = st.empty()
                updated_count = 0
                
                for idx, row in df_vocab.iterrows():
                    r_word, r_def, r_sent = row['word'], row['definition'], row['basic_sentence']
                    needs_update = False
                    clean_s = clean_sentence(r_sent)
                    search_root = str(r_word).lower()[:4] if len(str(r_word)) >= 4 else str(r_word).lower()
                    
                    if not clean_s or search_root not in clean_s.lower():
                        clean_s = fetch_sentence(str(r_word))
                        if clean_s: needs_update = True
                            
                    new_def = r_def
                    if not r_def or "(待補充" in str(r_def) or not re.search(r'[\u4e00-\u9fa5]', str(r_def)):
                        new_def = auto_translate_english_to_chinese(str(r_word))
                        if new_def != r_def: needs_update = True
                            
                    if needs_update or clean_sentence(r_sent) != str(r_sent):
                        status_text.text(f"⏳ 正在修復雲端資料: {r_word} ...")
                        update_single_word_in_sheet(
                            active_worksheet, r_word, r_word, 
                            row['phonetic'], row['part_of_speech'], new_def, clean_s, row.get('advanced_sentence',''), row.get('collocations','')
                        )
                        updated_count += 1
                    progress_bar.progress((idx + 1) / len(df_vocab))
                
                status_text.empty()
                st.success(f"🎊 掃描完成！已透過 AI 補齊 {updated_count} 筆雲端資料。")
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
                st.caption("💡 提示：您可以在這裡修改任何單字與中文釋義，變更將直接儲存至 Google Sheets。")
                
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
    df_vocab_flash = get_vocab_from_sheets(active_worksheet)
    if df_vocab_flash.empty:
        st.warning("📭 目前雲端沒有單字！")
    else:
        if "flashcard_index" not in st.session_state: st.session_state.flashcard_index = 0
        total_count = len(df_vocab_flash)
        st.session_state.flashcard_index = st.session_state.flashcard_index % total_count
        row = df_vocab_flash.iloc[st.session_state.flashcard_index]
        
        with st.container(border=True):
            st.markdown(f"<h1 style='text-align: center; font-size: 54px;'>🔤 {row['word']}</h1>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align: center; color: gray;'>{row.get('phonetic','')} | {row.get('part_of_speech','')}</p>", unsafe_allow_html=True)
            
        with st.expander("💡 詳細釋義與真實例句", expanded=True):
            st.markdown(f"**中文釋義：** {row['definition']}")
            display_sent = clean_sentence(row.get('basic_sentence', ''))
            if display_sent:
                st.markdown(f"**例句：** {display_sent}")
            else:
                st.info("💡 此單字尚無有效例句。")
        
        c1, c2 = st.columns(2)
        if c1.button("⬅️ 上一個", use_container_width=True):
            st.session_state.flashcard_index = (st.session_state.flashcard_index - 1) % total_count
            st.rerun()
        if c2.button("➡️ 下一個", use_container_width=True):
            st.session_state.flashcard_index = (st.session_state.flashcard_index + 1) % total_count
            st.rerun()

elif main_menu == "🎮 拼字王挑戰遊戲":
    df_vocab_game = get_vocab_from_sheets(active_worksheet)
    if df_vocab_game.empty:
        st.warning("📭 目前沒有足夠的單字來進行遊戲！")
    else:
        unit_list_game = ["全部單字"] + sorted(df_vocab_game['unit_tag'].dropna().unique().tolist()) if 'unit_tag' in df_vocab_game.columns else ["全部單字"]
        selected_game_unit = st.selectbox("選擇遊戲挑戰的單元範圍：", unit_list_game, key="game_unit_select")
        
        df_filtered_game = df_vocab_game if selected_game_unit == "全部單字" else df_vocab_game[df_vocab_game['unit_tag'] == selected_game_unit]
        
        if df_filtered_game.empty:
            st.warning("📭 該分類中沒有單字！")
        else:
            game_mode = st.radio("選擇挑戰模式：", ["🟢 經典單字挑戰 (考卷填空克漏字 + 單字發音)", "🔴 進階盲拼挑戰 (聽中文定義發音 + 打單字)"], horizontal=True)

            if "game_errors" not in st.session_state: st.session_state.game_errors = 0
            
            if "completed_words" not in st.session_state or st.session_state.get("game_scope_lock") != selected_game_unit:
                st.session_state.game_scope_lock = selected_game_unit
                st.session_state.completed_words = []
                if "current_game_item" in st.session_state: del st.session_state["current_game_item"]

            available_df = df_filtered_game[~df_filtered_game['word'].isin(st.session_state.completed_words)]
            
            if available_df.empty:
                st.balloons()
                st.success(f"🎉 太棒了！您已經把 【{selected_game_unit}】 裡的單字全部練習過一輪了！")
                if st.button("🔄 重新挑戰本單元", type="primary"):
                    st.session_state.completed_words = []
                    if "current_game_item" in st.session_state: del st.session_state["current_game_item"]
                    st.rerun()
            else:
                if "current_game_item" not in st.session_state:
                    row = available_df.sample(1).iloc[0]
                    w = str(row['word']).strip()
                    b_s = clean_sentence(row.get('basic_sentence', ''))
                    word_audio = generate_audio_bytes(w, lang='en')
                    st.session_state.current_game_item = {
                        "word": w, "definition": row.get('definition', ''), "unit_tag": row.get('unit_tag', ''),
                        "basic_sentence": b_s, "audio_bytes": word_audio
                    }

                item = st.session_state.current_game_item
                word_str = item["word"]
                hint_masked = "".join([" _ " if c.isalpha() else "   " for c in word_str])
                
                with st.container(border=True):
                    st.markdown(f"### ❌ 累積答錯題數：`{st.session_state.game_errors} 次` &nbsp;|&nbsp; 🏷️ {item['unit_tag']} &nbsp;|&nbsp; 📊 本輪剩餘：`{len(available_df)} 題`")
                    
                    if "經典" in game_mode:
                        b_s = item['basic_sentence']
                        search_root = word_str.lower()[:4] if len(word_str) >= 4 else word_str.lower()
                        can_cloze = bool(b_s and search_root in b_s.lower())
                            
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
                            st.warning("⚠️ 此單字目前無有效例句，請直接依據下方「中文釋義」與「發音」作答。")
                            st.markdown(f"**📌 中文釋義：** `{item['definition']}`")
                        
                        col_a1, col_a2 = st.columns([1, 4])
                        with col_a1: st.markdown("<div style='margin-top: 15px;'>**🔊 單字發音：**</div>", unsafe_allow_html=True)
                        with col_a2:
                            try: st.audio(item["audio_bytes"], format="audio/mp3")
                            except: pass
                                
                    else:
                        st.markdown("### 🎧 Listen to the pronunciation and spell the word based on its definition!")
                        st.markdown(f"**📌 中文釋義提示：** `{item['definition']}`")
                        
                        col_a1, col_a2 = st.columns([1, 4])
                        with col_a1: st.markdown("<div style='margin-top: 15px;'>**🔊 Audio Prompt：**</div>", unsafe_allow_html=True)
                        with col_a2:
                            try: st.audio(item["audio_bytes"], format="audio/mp3")
                            except: pass

                    st.markdown(f"**🔤 拼字提示 (Spelling Hint)：** `{hint_masked}` &nbsp;&nbsp; (Length: {len(word_str)} letters)")

                user_guess = st.text_input("Enter your spelling answer:", key="game_input_box").strip().lower()
                
                col_g1, col_g2 = st.columns(2)
                with col_g1: submit_guess = st.button("🚀 Submit Answer", type="primary", use_container_width=True)
                with col_g2: skip_question = st.button("🔄 Next Question", use_container_width=True)

                if submit_guess:
                    if user_guess == word_str.lower():
                        st.success(f"🎉 Correct! The word is **{word_str}**")
                        if word_str not in st.session_state.completed_words:
                            st.session_state.completed_words.append(word_str)
                        time.sleep(0.8)
                        if "current_game_item" in st.session_state: del st.session_state["current_game_item"]
                        st.rerun()
                    else:
                        st.session_state.game_errors += 1
                        st.error("❌ Incorrect! Try again!")

                if skip_question:
                    if "current_game_item" in st.session_state: del st.session_state["current_game_item"]
                    st.rerun()