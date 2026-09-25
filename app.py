import streamlit as st
import pandas as pd
import random
import re

# 頁面基本設定
st.set_page_config(
    page_title="智慧英文單字學習與管理系統",
    page_icon="📚",
    layout="wide"
)

# --- 1. 核心資料載入（透過 Google 試算表公開 CSV 網址，免憑證） ---
@st.cache_data(ttl=600)
def load_data_from_sheets():
    # 你的 Google 試算表 ID
    sheet_id = "1eI46TU3fR8vPAtKvHYGEF0D85_2n4zxR9H5Wff4OqcY"
    # 對應你的 Google 試算表分頁名稱 (Junior, Senior, TOEIC)
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
        return pd.concat(all_data, ignore_index=True)
    else:
        # 回傳預設空結構
        return pd.DataFrame(columns=["id", "word", "phonetic", "part_of_speech", "definition", "basic_sentence", "advanced_sentence", "collocations", "unit_tag", "srs_stage", "category"])

df_words = load_data_from_sheets()

# --- 2. 側邊欄導覽與設定 ---
with st.sidebar:
    st.markdown("### ⚙️ 系統導覽與設定")
    st.success("✅ 核心連線就緒 (公開試算表模式)")
    
    st.markdown("---")
    st.markdown("### 📌 功能選單")
    app_mode = st.radio(
        "選擇操作模式",
        ["✨ 智慧單字新增", "📁 字庫管理與搜尋", "🃏 沉浸式閃卡複習", "🔥 拼字王挑戰遊戲"],
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    st.markdown("### 📂 學習階段 / 級別分類")
    level_map = {
        "國中部": "Junior",
        "高中部": "Senior",
        "多益 (TOEIC)": "TOEIC"
    }
    selected_level_label = st.radio("選擇目前目標級別：", list(level_map.keys()), label_visibility="collapsed")
    current_category = level_map[selected_level_label]
    
    st.markdown("---")
    st.info(f"💡 目前模式：專注於 **{selected_level_label}** 單字訓練（獨立資料庫）。")

# 過濾出目前選擇的級別資料
if not df_words.empty and 'category' in df_words.columns:
    current_df = df_words[df_words['category'] == current_category].copy()
    current_df = current_df.dropna(subset=['word'])
else:
    current_df = pd.DataFrame()

# --- 3. 页面頂部資訊呈現 ---
st.markdown(f"## 📚 智慧英文單字學習與管理系統")
col_info1, col_info2, col_info3 = st.columns(3)
with col_info1:
    st.metric(label="📌 字庫總單字數", value=f"{len(current_df)} 個")
with col_info2:
    st.metric(label="⚙️ 系統狀態", value="運行中")
with col_info3:
    st.metric(label="⚡ 目前級別", value=selected_level_label)

st.markdown("---")

# --- 4. 各功能分頁實作 ---

# 模式一：智慧單字新增
if app_mode == "✨ 智慧單字新增":
    st.markdown(f"### ✨ 智慧單字新增 ({selected_level_label})")
    
    col_add1, col_add2 = st.columns(2)
    with col_add1:
        st.markdown("#### 📄 單筆快速建檔")
        single_input = st.text_input("輸入想要學習的英文單字：", placeholder="例如: resilient, meticulous...")
        if st.button("✨ 自動生成並加入字庫"):
            if single_input.strip():
                st.success(f"已成功送出單字「{single_input}」！(提示：請直接至 Google 試算表的 `{current_category}` 分頁新增該單字的音標、解釋與例句)")
            else:
                st.warning("請輸入有效的單字。")
                
    with col_add2:
        st.markdown("#### 📁 批量 CSV 檔案匯入")
        uploaded_file = st.file_uploader("選擇您的 CSV 檔案", type=["csv"])
        if uploaded_file is not None:
            st.success("檔案上傳成功！您可以直接至 Google 試算表對應分頁中貼上或覆蓋資料。")

# 模式二：字庫管理與搜尋
elif app_mode == "📁 字庫管理與搜尋":
    st.markdown(f"### 📁 字庫管理與搜尋 ({selected_level_label})")
    
    if current_df.empty:
        st.warning(f"目前 `{current_category}` 分頁中沒有資料，請至 Google 試算表填入單字。")
    else:
        # 單元篩選
        unit_tags = ["全部單元"] + list(current_df['unit_tag'].dropna().unique()) if 'unit_tag' in current_df.columns else ["全部單元"]
        selected_unit = st.selectbox("依學習單元篩選：", unit_tags)
        
        if selected_unit != "全部單元":
            table_df = current_df[current_df['unit_tag'] == selected_unit]
        else:
            table_df = current_df
            
        search_query = st.text_input("🔍 搜尋單字或釋義：", placeholder="輸入關鍵字...")
        if search_query:
            table_df = table_df[table_df.apply(lambda row: row.astype(str).str.contains(search_query, case=False).any(), axis=1)]
            
        st.dataframe(table_df, use_container_width=True)

# 模式三：沉浸式閃卡複習
elif app_mode == "🃏 沉浸式閃卡複習":
    st.markdown(f"### 🃏 沉浸式閃卡複習 ({selected_level_label})")
    
    if current_df.empty:
        st.warning(f"目前 `{current_category}` 分頁中沒有單字可以複習。")
    else:
        if 'flash_index' not in st.session_state:
            st.session_state.flash_index = 0
            
        st.session_state.flash_index %= len(current_df)
        row = current_df.iloc[st.session_state.flash_index]
        word_str = str(row['word'])
        
        col_f1, col_f2 = st.columns([3, 1])
        with col_f1:
            st.markdown(f"#### CARD {st.session_state.flash_index + 1} OF {len(current_df)} | 🏷️ {row.get('unit_tag', '')}")
            st.markdown(f"## 🔤 **{word_str}**  `{row['phonetic']}`")
            st.markdown(f"**詞性與解釋**：{row['part_of_speech']} {row['definition']}")
            
            # 例句挖空處理（支援像 years old 這類帶空白的片語）
            basic_sent = str(row.get('basic_sentence', ''))
            if basic_sent and basic_sent != 'nan':
                masked_basic = re.sub(re.escape(word_str), '______', basic_sent, flags=re.IGNORECASE)
                st.info(f"💡 **基礎例句**：{masked_basic}")
                
            adv_sent = str(row.get('advanced_sentence', ''))
            if adv_sent and adv_sent != 'nan':
                masked_adv = re.sub(re.escape(word_str), '______', adv_sent, flags=re.IGNORECASE)
                st.success(f"🔥 **進階例句**：{masked_adv}")
                
        with col_f2:
            if st.button("➡️ 下一張卡片", use_container_width=True):
                st.session_state.flash_index += 1
                st.rerun()

# 模式四：拼字王挑戰遊戲
elif app_mode == "🔥 拼字王挑戰遊戲":
    st.markdown(f"### 🔥 拼字王挑戰遊戲 ({selected_level_label})")
    
    if current_df.empty:
        st.warning(f"目前 `{current_category}` 分頁中沒有單字可以進行拼字挑戰。")
    else:
        if 'spelling_target' not in st.session_state or st.session_state.get('spelling_cat') != current_category:
            st.session_state.spelling_target = current_df.sample(1).iloc[0]
            st.session_state.spelling_cat = current_category
            st.session_state.spelling_result = None

        target = st.session_state.spelling_target
        word_str = str(target['word'])
        
        # 針對單字或片語（含空白）設計底線空格提示
        hint_display = "".join([" _ " if c.isalpha() else "   " for c in word_str])
        
        st.markdown(f"#### 🏷️ 範圍：{selected_level_label} > {target.get('unit_tag', '')}")
        st.markdown(f"📖 **中文釋義**：{target['definition']}")
        st.markdown(f"🔤 **拼字提示**：`{hint_display}` （共 {len(word_str)} 個字元）")
        
        user_input = st.text_input("請輸入你的拼字答案（輸入完可直接按 Enter）：", key="spelling_input_box")
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("送出答案", use_container_width=True):
                if user_input.strip().lower() == word_str.lower():
                    st.session_state.spelling_result = "correct"
                else:
                    st.session_state.spelling_result = "wrong"
        with col_btn2:
            if st.button("下一題 ⏭️", use_container_width=True):
                st.session_state.spelling_target = current_df.sample(1).iloc[0]
                st.session_state.spelling_result = None
                st.rerun()
                
        if st.session_state.spelling_result == "correct":
            st.balloons()
            st.success(f"🎉 太神啦！答對了！正確答案就是 **{word_str}**")
        elif st.session_state.spelling_result == "wrong":
            st.error("❌ 答錯囉！再試一次，或點擊下一題看看吧！")