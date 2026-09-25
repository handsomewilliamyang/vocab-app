import streamlit as st
import pandas as pd
import random
import re

# 頁面基本設定
st.set_page_config(page_title="我愛背單字", page_icon="📚", layout="centered")

# --- 1. 直接讀取 Google 試算表公開 CSV 資料 ---
@st.cache_data(ttl=600)
def load_data_from_sheets():
    # 你的 Google 試算表 ID
    sheet_id = "1eI46TU3fR8vPAtKvHYGEF0D85_2n4zxR9H5Wff4OqcY"
    tabs = ["Junior", "Senior", "TOEIC"]
    all_data = []
    
    for tab in tabs:
        try:
            # 組合公開 CSV 匯出網址
            csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={tab}"
            df = pd.read_csv(csv_url)
            if not df.empty:
                df['category'] = tab
                all_data.append(df)
        except Exception as e:
            continue
            
    if all_data:
        return pd.concat(all_data, ignore_index=True)
    else:
        return pd.DataFrame(columns=["word", "phonetic", "part_of_speech", "definition", "basic_sentence", "advanced_sentence", "collocations", "unit_tag", "category"])

df_words = load_data_from_sheets()

# --- 2. 介面設計 ---
st.title("📚 我愛背單字")

if df_words.empty:
    st.warning("目前試算表中沒有資料，請確認 Google 試算表是否已設為「知道連結的人都能檢視」，且分頁名稱為 Junior, Senior, TOEIC。")
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
            if 'practice_index' not in st.session_state:
                st.session_state.practice_index = random.randint(0, len(current_df) - 1)
            
            row = current_df.iloc[st.session_state.practice_index % len(current_df)]
            
            st.markdown(f"### 🎯 單字卡")
            st.write(f"**分類**：{row.get('category', '')} | **標籤**：{row.get('unit_tag', '')}")
            st.markdown(f"## **{row['word']}**  `{row['phonetic']}`")
            st.write(f"**詞性與解釋**：{row['part_of_speech']} {row['definition']}")
            
            # 例句挖空處理
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
                st.session_state.spelling_result = None

            target = st.session_state.spelling_target
            word_len = len(str(target['word']))
            
            st.write(f"🏷️ **範圍**：{target.get('category', '')} > {target.get('unit_tag', '')}")
            st.write(f"📖 **詞性與定義提示**：{target['part_of_speech']} {target['definition']}")
            st.markdown(f"🔤 **字數提示**：`{' _ ' * word_len}` （共 {word_len} 個字母）")
            
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