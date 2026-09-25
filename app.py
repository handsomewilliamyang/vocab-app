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
.big-word { 
    font-size: 3.8rem; 
    font-weight: bold; 
    text-align: center; 
    margin-bottom: 0; 
    color: #4facf7; 
    padding: 15px 0;
}
.phonetic-pos { 
    font-size: 1.3rem; 
    color: #cbd5e1; 
    text-align: center; 
    margin-top: -10px; 
    margin-bottom: 20px;
}
.card-header { 
    text-align: right; 
    color: #94a3b8; 
    font-size: 0.95rem; 
    margin-bottom: 10px; 
}
</style>
""", unsafe_allow_html=True)

# --- 1. 核心資料載入 (最穩定標準版，不亂加網址參數) ---
@st.cache_data(ttl=10) # 讓系統自然每 10 秒過期一次快取，最安全
def load_data_from_sheets():
    sheet_id = "1eI46TU3fR8vPAtKvHYGEF0D85_2n4zxR9H5Wff4OqcY"
    tabs = ["Junior", "Senior", "TOEIC"]
    all_data = []
    
    for tab in tabs:
        try:
            # 乾淨標準的網址，絕不引發 400 錯誤
            csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={tab}"
            df = pd.read_csv(csv_url)
            if not df.empty:
                df.columns = df.columns.str.strip()
                df['category'] = tab
                all_data.append(df)
        except Exception:
            continue
            
    if all_data:
        df_combined = pd.concat(all_data, ignore_index=True)
        # 清理無效與空值字串，消滅醜陋的 None
        df_combined = df_combined.fillna("")
        df_combined = df_combined.replace(["None", "nan", "NaN"], "")
        return df_combined
    else:
        return pd.DataFrame(columns=["id", "word", "phonetic", "part_of_speech", "definition", "basic_sentence", "advanced_sentence", "collocations", "unit_tag", "srs_stage", "category"])

df_words = load_data_from_sheets()

# --- 2. 側邊欄導覽與設定 ---
with st.sidebar:
    st.markdown("### ⚙️ 系統設定與導覽")
    
    # 安全的資料同步按鈕
    if st.button("🔄 同步 Google 試算表最新資料", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
        
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
    
    st.info(f"💡 目前模式：專注於 **{selected_level_label}** 單字訓練。")

# 過濾當前級別資料，排除空單字
current_df = df_words[df_words['category'] == current_category].copy() if not df_words.empty else pd.DataFrame()
if not current_df.empty and 'word' in current_df.columns:
    current_df = current_df[current_df['word'].astype(str).str.strip() != ""]

# --- 3. 頁面頂部資訊 ---
st.markdown("## 📚 智慧英文單字學習與管理系統")
col_info1, col_info2, col_info3 = st.columns(3)
with col_info1:
    st.metric(label="📌 字庫總單字數", value=f"{len(current_df)} 個")
with col_info2:
    st.metric(label="⚙️ 系統狀態", value="運行中")
with col_info3:
    st.metric(label="⚡ 目前級別", value=selected_level_label)

st.markdown("---")

# --- 輔助功能：雙層選單過濾 (年級與課別) ---
def render_unit_filter(df):
    if df.empty or 'unit_tag' not in df.columns:
        return df
    
    all_tags = [str(t).strip() for t in df['unit_tag'].unique() if str(t).strip() != ""]
    if not all_tags:
        return df
        
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        grades = ["全部年級/冊別"] + sorted(list(set([t.split('>')[0].strip() if '>' in t else t for t in all_tags])))
        selected_grade = st.selectbox("🎯 選擇年級/冊別：", grades)
        
    filtered_df = df.copy()
    if selected_grade != "全部年級/冊別":
        filtered_df = filtered_df[filtered_df['unit_tag'].astype(str).str.contains(selected_grade, regex=False)]
        
    with col_f2:
        lessons = ["全部課別/單元"] + sorted(list(filtered_df['unit_tag'].unique()))
        selected_lesson = st.selectbox("📖 選擇課別/單元：", lessons)
        
    if selected_lesson != "全部課別/單元":
        filtered_df = filtered_df[filtered_df['unit_tag'] == selected_lesson]
        
    return filtered_df

# --- 4. 功能模組實作 ---

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
    st.markdown(f"### 📖 字庫管理與搜尋 ({selected_level_label})")
    
    if current_df.empty:
        st.warning(f"目前 `{current_category}` 分頁中沒有資料。")
    else:
        table_df = render_unit_filter(current_df)
        search_query = st.text_input("🔍 搜尋單字或釋義：", placeholder="輸入關鍵字...")
        if search_query:
            table_df = table_df[table_df.apply(lambda row: row.astype(str).str.contains(search_query, case=False).any(), axis=1)]
            
        with st.expander("🔽 點擊收合/展開：單字總表與快速編輯區", expanded=True):
            st.dataframe(table_df, use_container_width=True, hide_index=True)

elif app_mode == "🃏 沉浸式閃卡複習":
    st.markdown(f"### 🃏 沉浸式閃卡複習 ({selected_level_label})")
    
    if current_df.empty:
        st.warning(f"目前 `{selected_level_label}` 沒有單字可以複習。")
    else:
        flash_df = render_unit_filter(current_df)
        
        if flash_df.empty:
            st.info("此篩選條件下目前沒有單字。")
        else:
            if 'flash_index' not in st.session_state:
                st.session_state.flash_index = 0
                
            st.session_state.flash_index %= len(flash_df)
            row = flash_df.iloc[st.session_state.flash_index]
            word_str = str(row['word'])
            phonetic_str = str(row.get('phonetic', '')).strip()
            pos_str = str(row.get('part_of_speech', '')).strip()
            def_str = str(row.get('definition', '')).strip()
            
            with st.container(border=True):
                unit_label = row.get('unit_tag', '')
                st.markdown(f"<div class='card-header'>CARD {st.session_state.flash_index + 1} OF {len(flash_df)} | 🏷️ {unit_label if unit_label else '未分類'}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='big-word'>{word_str}</div>", unsafe_allow_html=True)
                
                phonetic_display = f"/{phonetic_str.strip('/')}/" if phonetic_str else ""
                info_line = " | ".join(filter(None, [phonetic_display, pos_str]))
                if info_line:
                    st.markdown(f"<div class='phonetic-pos'>{info_line}</div>", unsafe_allow_html=True)
                
            with st.expander("💡 點擊展開詳細釋義與例句解析", expanded=True):
                st.markdown(f"**📌 核心釋義：** {def_str if def_str else '（未提供）'}")
                
                basic_sent = str(row.get('basic_sentence', '')).strip()
                if basic_sent:
                    masked_basic = re.sub(re.escape(word_str), '______', basic_sent, flags=re.IGNORECASE)
                    st.info(f"💡 **基礎例句**：{masked_basic}")
                    
                adv_sent = str(row.get('advanced_sentence', '')).strip()
                if adv_sent:
                    masked_adv = re.sub(re.escape(word_str), '______', adv_sent, flags=re.IGNORECASE)
                    st.success(f"🔥 **進階例句**：{masked_adv}")
                    
            if st.button("➡️ 下一張卡片", use_container_width=True, type="primary"):
                st.session_state.flash_index += 1
                st.rerun()

elif app_mode == "🔥 拼字王挑戰遊戲":
    st.markdown(f"### 🔥 拼字王挑戰遊戲 ({selected_level_label})")
    
    if current_df.empty:
        st.warning(f"目前 `{selected_level_label}` 沒有單字可以進行拼字挑戰。")
    else:
        spell_df = render_unit_filter(current_df)
        
        if spell_df.empty:
            st.info("此篩選條件下目前沒有單字。")
        else:
            if 'spelling_target' not in st.session_state:
                st.session_state.spelling_target = spell_df.sample(1).iloc[0]
                st.session_state.spelling_result = None
                st.session_state.spelling_mistakes = 0

            target = st.session_state.spelling_target
            word_str = str(target['word'])
            hint_display = "".join([" _ " if c.isalpha() else "   " for c in word_str])
            
            with st.container(border=True):
                st.markdown(f"#### ❌ 累積答錯題數： `{st.session_state.get('spelling_mistakes', 0)}` 次 | 🏷️ {target.get('unit_tag', '未分類')}")
                st.markdown(f"**📌 中文釋義**：{target.get('definition', '（未提供）')}")
                
                basic_sent = str(target.get('basic_sentence', '')).strip()
                if basic_sent:
                    masked_basic = re.sub(re.escape(word_str), '______', basic_sent, flags=re.IGNORECASE)
                    st.markdown(f"**📖 基礎例句**：{masked_basic}")
                    
                st.markdown(f"**🔤 拼字提示**：`{hint_display}` （字數：{len(word_str)}個字元）")
                
            user_input = st.text_input("請輸入你的拼字答案 (輸入完可直接按 Enter 送出)：", key="spelling_input_box")
            
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("🚀 送出答案", type="primary", use_container_width=True):
                    if user_input.strip().lower() == word_str.lower():
                        st.session_state.spelling_result = "correct"
                    else:
                        st.session_state.spelling_result = "wrong"
                        st.session_state.spelling_mistakes += 1
            with col_btn2:
                if st.button("🔄 換一題", use_container_width=True):
                    st.session_state.spelling_target = spell_df.sample(1).iloc[0]
                    st.session_state.spelling_result = None
                    st.rerun()
                    
            if st.session_state.spelling_result == "correct":
                st.balloons()
                st.success(f"🎉 太神啦！答對了！正確答案就是 **{word_str}**")
            elif st.session_state.spelling_result == "wrong":
                st.error("❌ 答錯囉！請再試一次。")