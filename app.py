import streamlit as st
import pandas as pd
import random
import re

# --- 頁面基本設定 ---
st.set_page_config(
    page_title="智慧英文單字學習與管理系統",
    page_icon="📚",
    layout="wide"
)

# 自訂 CSS 讓閃卡與排版更漂亮
st.markdown("""
<style>
.big-word { font-size: 4.5rem; font-weight: bold; text-align: center; margin-bottom: 0; color: #4facf7; }
.phonetic-pos { font-size: 1.2rem; color: #aaa; text-align: center; margin-top: 0; margin-bottom: 20px;}
.card-header { text-align: right; color: #888; font-size: 0.9rem; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

# --- 1. 核心資料載入 (免憑證公開讀取) ---
@st.cache_data(ttl=600)
def load_data_from_sheets():
    sheet_id = "1eI46TU3fR8vPAtKvHYGEF0D85_2n4zxR9H5Wff4OqcY"
    tabs = ["Junior", "Senior", "TOEIC"]
    all_data = []
    
    for tab in tabs:
        try:
            csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={tab}"
            df = pd.read_csv(csv_url)
            if not df.empty:
                df.columns = df.columns.str.strip()
                df['category'] = tab
                all_data.append(df)
        except Exception as e:
            continue
            
    if all_data:
        df_combined = pd.concat(all_data, ignore_index=True)
        # 【關鍵修復】將所有 NaN 或 None 替換為空字串，消除醜陋的 None 顯示
        df_combined = df_combined.fillna("")
        df_combined = df_combined.replace("None", "")
        return df_combined
    else:
        return pd.DataFrame(columns=["id", "word", "phonetic", "part_of_speech", "definition", "basic_sentence", "advanced_sentence", "collocations", "unit_tag", "srs_stage", "category"])

df_words = load_data_from_sheets()

# --- 2. 側邊欄導覽與設定 ---
with st.sidebar:
    st.markdown("### ⚙️ 系統設定與導覽")
    st.success("✅ 核心連線就緒 (公開試算表模式)")
    st.markdown("---")
    
    st.markdown("### 📌 功能選單")
    app_mode = st.radio(
        "選擇操作模式",
        ["✨ 智慧單字新增", "📖 字庫管理與搜尋", "🃏 沉浸式閃卡複習", "🔥 拼字王挑戰遊戲"],
        label_visibility="collapsed"
    )
    st.markdown("---")
    
    st.markdown("### 📁 學習階段 / 級別分類")
    level_map = {"國中部": "Junior", "高中部": "Senior", "多益 (TOEIC)": "TOEIC"}
    selected_level_label = st.radio("選擇目前目標級別：", list(level_map.keys()), label_visibility="collapsed")
    current_category = level_map[selected_level_label]
    st.markdown("---")
    
    st.info(f"💡 目前模式：專注於 **{selected_level_label}** 單字訓練 (獨立資料庫)。")

# 過濾當前級別的單字，並排除空單字
current_df = df_words[df_words['category'] == current_category].copy() if not df_words.empty else pd.DataFrame()
if not current_df.empty and 'word' in current_df.columns:
    current_df = current_df[current_df['word'] != ""]

# --- 3. 頁面頂部資訊呈現 ---
st.markdown("## 📚 智慧英文單字學習與管理系統")
if app_mode == "✨ 智慧單字新增":
    st.caption(f"歡迎使用專為高效背單字與教學設計的整合平台。(目前分類：{selected_level_label})")

col_info1, col_info2, col_info3 = st.columns(3)
with col_info1:
    label_text = "📌 字庫總單字數" if app_mode == "✨ 智慧單字新增" else "📌 總單字數"
    st.metric(label=label_text, value=f"{len(current_df)} 個")
with col_info2:
    if app_mode == "✨ 智慧單字新增":
        st.metric(label="⚙️ 系統狀態", value="運行中")
    else:
        st.metric(label="目前模式", value=f"{app_mode[2:]} ({selected_level_label})")
with col_info3:
    st.metric(label="⚡ 目前級別", value=selected_level_label)

st.markdown("---")

# --- 4. 各功能分頁實作 ---

if app_mode == "✨ 智慧單字新增":
    st.markdown(f"### ✨ 智慧單字新增 ({selected_level_label})")
    col_add1, col_add2 = st.columns(2)
    with col_add1:
        st.markdown("#### 📄 單筆快速建檔")
        st.text_input("輸入想要學習的英文單字：", placeholder="例如: resilient, meticulous...")
        st.button("✨ 自動生成並加入字庫", type="primary", use_container_width=True)
    with col_add2:
        st.markdown("#### 📁 批量 CSV 檔案匯入")
        st.file_uploader("選擇您的 CSV 檔案", type=["csv"])

elif app_mode == "📖 字庫管理與搜尋":
    st.markdown(f"### 📁 字庫管理與搜尋 ({selected_level_label})")
    unit_tags = ["全部單元"] + list(current_df['unit_tag'].unique()) if not current_df.empty and 'unit_tag' in current_df.columns else ["全部單元"]
    
    col_filter1, col_filter2 = st.columns(2)
    with col_filter1:
        selected_unit = st.selectbox("依學習單元篩選：", unit_tags)
    with col_filter2:
        st.write("") # 為了對齊按鈕的空白
        st.write("")
        st.button("🪄 選取並進行自動修復中文", type="primary", use_container_width=True)
        
    col_search1, col_search2 = st.columns(2)
    with col_search1:
        search_query = st.text_input("🔍 搜尋單字或釋義：", placeholder="輸入關鍵字...")
    with col_search2:
        st.selectbox("🗑️ 勾選要刪除的單字：", ["選擇單字..."])
        
    # 篩選邏輯
    table_df = current_df
    if selected_unit != "全部單元":
        table_df = table_df[table_df['unit_tag'] == selected_unit]
    if search_query:
        table_df = table_df[table_df.apply(lambda row: row.astype(str).str.contains(search_query, case=False).any(), axis=1)]
        
    with st.expander("🔽 點擊收合/展開：單字總表與快速編輯區", expanded=True):
        st.dataframe(table_df, use_container_width=True, hide_index=True)

elif app_mode == "🃏 沉浸式閃卡複習":
    unit_tags = ["全部單字"] + list(current_df['unit_tag'].unique()) if not current_df.empty and 'unit_tag' in current_df.columns else ["全部單字"]
    selected_unit = st.selectbox("選擇要複習的單元範圍：", unit_tags)
    
    flash_df = current_df if selected_unit == "全部單字" else current_df[current_df['unit_tag'] == selected_unit]
    
    if flash_df.empty:
        st.warning("此分類目前沒有單字可以複習。")
    else:
        if 'flash_index' not in st.session_state:
            st.session_state.flash_index = 0
            
        st.session_state.flash_index %= len(flash_df)
        row = flash_df.iloc[st.session_state.flash_index]
        word_str = str(row['word'])
        
        # 閃卡精美外框
        with st.container(border=True):
            st.markdown(f"<div class='card-header'>CARD {st.session_state.flash_index + 1} OF {len(flash_df)} | 🏷️ {row.get('unit_tag', '')}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='big-word'>abc {word_str}</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='phonetic-pos'>{row['phonetic']} | {row['part_of_speech']}</div>", unsafe_allow_html=True)
            
        with st.expander("💡 點擊展開詳細釋義與例句解析"):
            st.markdown(f"**📌 核心釋義：**\n\n{row['definition']}")
            basic_sent = str(row.get('basic_sentence', ''))
            if basic_sent:
                masked_basic = re.sub(re.escape(word_str), '______', basic_sent, flags=re.IGNORECASE)
                st.info(f"💡 **基礎例句**：{masked_basic}")
                
            adv_sent = str(row.get('advanced_sentence', ''))
            if adv_sent:
                masked_adv = re.sub(re.escape(word_str), '______', adv_sent, flags=re.IGNORECASE)
                st.success(f"🔥 **進階例句**：{masked_adv}")
                
        if st.button("➡️ 下一張", use_container_width=True):
            st.session_state.flash_index += 1
            st.rerun()

elif app_mode == "🔥 拼字王挑戰遊戲":
    unit_tags = ["全部單字"] + list(current_df['unit_tag'].unique()) if not current_df.empty and 'unit_tag' in current_df.columns else ["全部單字"]
    selected_unit = st.selectbox("選擇遊戲挑戰的單元範圍：", unit_tags)
    
    spell_df = current_df if selected_unit == "全部單字" else current_df[current_df['unit_tag'] == selected_unit]
    
    if spell_df.empty:
        st.warning("此分類目前沒有單字可以進行拼字挑戰。")
    else:
        if 'spelling_target' not in st.session_state or st.session_state.get('spelling_cat') != f"{current_category}_{selected_unit}":
            st.session_state.spelling_target = spell_df.sample(1).iloc[0]
            st.session_state.spelling_cat = f"{current_category}_{selected_unit}"
            st.session_state.spelling_result = None
            st.session_state.spelling_mistakes = st.session_state.get('spelling_mistakes', 0)

        target = st.session_state.spelling_target
        word_str = str(target['word'])
        hint_display = "".join([" _ " if c.isalpha() else "   " for c in word_str])
        
        with st.container(border=True):
            st.markdown(f"#### ❌ 累積答錯題數： `{st.session_state.get('spelling_mistakes', 0)}` 次 | 🏷️ {target.get('unit_tag', '')}")
            st.markdown(f"**📌 中文釋義**：{target['definition']}")
            
            basic_sent = str(target.get('basic_sentence', ''))
            if basic_sent:
                masked_basic = re.sub(re.escape(word_str), '______', basic_sent, flags=re.IGNORECASE)
                st.markdown(f"**📖 基礎例句**：{masked_basic}")
                
            st.markdown(f"**🔤 拼字提示**：`{hint_display}` （字數：{len(word_str)}個字母）")
            
        user_input = st.text_input("請輸入你的拼字答案 (輸入完可直接按 Enter 送出)：", key="spelling_input_box")
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("🚀 送出答案", type="primary", use_container_width=True):
                if user_input.strip().lower() == word_str.lower():
                    st.session_state.spelling_result = "correct"
                else:
                    st.session_state.spelling_result = "wrong"
                    st.session_state.spelling_mistakes = st.session_state.get('spelling_mistakes', 0) + 1
        with col_btn2:
            if st.button("🔄 換一題", use_container_width=True):
                st.session_state.spelling_target = spell_df.sample(1).iloc[0]
                st.session_state.spelling_result = None
                st.rerun()
                
        if st.session_state.spelling_result == "correct":
            st.balloons()
            st.success(f"🎉 太神啦！答對了！正確答案就是 **{word_str}**")
            if st.button("繼續下一題"):
                st.session_state.spelling_target = spell_df.sample(1).iloc[0]
                st.session_state.spelling_result = None
                st.rerun()
        elif st.session_state.spelling_result == "wrong":
            st.error("❌ 答錯囉！請再試一次。")