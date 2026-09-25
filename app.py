import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import random
import re

# 頁面基本設定
st.set_page_config(page_title="我愛背單字", page_icon="📚", layout="centered")

# --- 1. 連線 Google Sheets 載入資料 ---
@st.cache_resource
def init_connection():
    try:
        # 從 Streamlit Secrets 讀取憑證
        creds_dict = dict(st.secrets["gcp_service_account"])
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(None, scopes=scope) if False else Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        
        # 讀取試算表網址
        spreadsheet_url = st.secrets["spreadsheet_url"]
        sheet = client.open_by_url(spreadsheet_url)
        return sheet
    except Exception as e:
        st.error(f"連線 Google 試算表失敗，請檢查 Secrets 設定：{e}")
        return None

sheet = init_connection()

@st.cache_data(ttl=600)
def load_data_from_sheets():
    if not sheet:
        return pd.DataFrame()
    
    all_data = []
    tabs = ["Junior", "Senior", "TOEIC"]
    for tab in tabs:
        try:
            worksheet = sheet.worksheet(tab)
            data = worksheet.get_all_records()
            if data:
                df = pd.DataFrame(data)
                df['category'] = tab  # 標記分類
                all_data.append(df)
        except Exception as e:
            continue
            
    if all_data:
        return pd.concat(all_data, ignore_index=True)
    else:
        # 預設空結構
        return pd.DataFrame(columns=["word", "phonetic", "part_of_speech", "definition", "basic_sentence", "advanced_sentence", "collocations", "unit_tag", "category"])

df_words = load_data_from_sheets()

# --- 2. 介面設計 ---
st.title("📚 我愛背單字")

if df_words.empty:
    st.warning("目前試算表中沒有資料，請確認 Google Sheets 內容與分頁名稱（Junior, Senior, TOEIC）。")
else:
    st.write(f"總單字數：**{len(df_words)} 個**")
    
    # 選擇模式
    mode = st.sidebar.radio("選擇學習模式", ["單字練習與複習", "🔥 拼字王挑戰"])
    
    # 選擇範圍
    categories = ["全部單字"] + list(df_words['category'].unique())
    selected_cat = st.selectbox("選擇挑戰的單元範圍：", categories)
    
    if selected_cat != "全部單字":
        current_df = df_words[df_words['category'] == selected_cat]
    else:
        current_df = df_words

    if current_df.empty:
        st.info("此分類目前沒有單字。")
    else:
        if mode == "單字練習與複習":
            # 隨機抽單字邏輯
            if 'practice_index' not in st.session_state:
                st.session_state.practice_index = random.randint(0, len(current_df) - 1)
            
            row = current_df.iloc[st.session_state.practice_index % len(current_df)]
            
            st.markdown(f"### 🎯 單字卡")
            st.write(f"**分類**：{row.get('category', '')} | **標籤**：{row.get('unit_tag', '')}")
            st.markdown(f"## **{row['word']}**  `{row['phonetic']}`")
            st.write(f"**詞性與解釋**：{row['part_of_speech']} {row['definition']}")
            
            # 例句挖空處理（不分大小寫將單字替換為 ______）
            basic_sent = str(row.get('basic_sentence', ''))
            if basic_sent and basic_sent != 'nan':
                masked_basic = re.sub(re.escape(str(row['word'])), '______', basic_sent, flags=re.IGNORECASE)
                st.info(f"💡 **基礎例句**：{masked_basic}")
                
            adv_sent = str(row.get('advanced_sentence', ''))
            if adv_sent and adv_sent != 'nan':
                masked_adv = re.sub(re.escape(str(row['word'])), '______', adv_sent, flags=re.IGNORECASE)
                st.success(f"🔥 **進階例句**：{masked_adv}")
                
            if st.button("換下一題 ➡️"):
                st.session_state.practice_index = random.randint(0, len(current_df) - 1)
                st.rerun()

        elif mode == "🔥 拼字王挑戰":
            st.markdown("### ⚡ 拼字王挑戰：根據提示拼出正確單字！")
            
            if 'spelling_target' not in st.session_state or st.session_state.get('spelling_cat') != selected_cat:
                st.session_state.spelling_target = current_df.sample(1).iloc[0]
                st.session_state.spelling_cat = selected_cat
                st.session_state.user_spelling_input = ""
                st.session_state.spelling_result = None

            target = st.session_state.spelling_target
            word_len = len(str(target['word']))
            
            # 顯示提示（移除中文釋義，改給英文或詞性與例句提示，符合需求）
            st.write(f"🏷️ **範圍**：{target.get('category', '')} > {target.get('unit_tag', '')}")
            st.write(f"📖 **詞性與定義提示**：{target['part_of_speech']} {target['definition']}")
            
            # 顯示字數提示
            st.markdown(f"🔤 **字數提示**：`{' _ ' * word_len}` （共 {word_len} 個字母）")
            
            # 讓學生輸入答案
            user_input = st.text_input("請輸入你的拼字答案：", key="spelling_input_box")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("送出答案"):
                    if user_input.strip().lower() == str(target['word']).lower():
                        st.session_state.spelling_result = "correct"
                    else:
                        st.session_state.spelling_result = "wrong"
            with col2:
                if st.button("下一題 ⏭️"):
                    st.session_state.spelling_target = current_df.sample(1).iloc[0]
                    st.session_state.spelling_result = None
                    st.rerun()
            
            if st.session_state.spelling_result == "correct":
                st.balloons()
                st.success(f"🎉 太神啦！答對了！正確答案就是 **{target['word']}**")
            elif st.session_state.spelling_result == "wrong":
                st.error("❌ 答錯囉！再試一次，或點擊下一題看看吧！")