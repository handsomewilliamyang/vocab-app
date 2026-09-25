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

# -------------------------------------------------------------------------
# 0. 頁面全域設定
# -------------------------------------------------------------------------
st.set_page_config(
    page_title="我愛背單字 (雲端版)",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -------------------------------------------------------------------------
# 1. 側邊欄導覽與 Google Sheets 雲端設定
# -------------------------------------------------------------------------
st.sidebar.markdown("<h2 style='font-size: 24px;'>⚙️ 系統導覽與雲端設定</h2>", unsafe_allow_html=True)

# 💡 讓您可以直接貼上您的 Google Sheets 試算表公開 CSV 連結
cloud_sheet_url = st.sidebar.text_input(
    "📊 Google Sheets 公開 CSV 連結：", 
    value=st.session_state.get("sheet_url", ""),
    placeholder="https://docs.google.com/spreadsheets/d/.../export?format=csv"
)
if cloud_sheet_url:
    st.session_state["sheet_url"] = cloud_sheet_url

st.sidebar.markdown("---")
st.sidebar.markdown("<h3 style='font-size: 20px;'>📌 功能選單</h3>", unsafe_allow_html=True)
main_menu = st.sidebar.radio(
    "選擇主要功能：",
    ["✨ 智慧單字新增", "📖 雲端字庫管理", "🎯 沉浸式閃卡複習", "🎮 拼字王挑戰遊戲"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")
st.sidebar.markdown("<h3 style='font-size: 20px;'>📂 學習階段 / 級別分類</h3>", unsafe_allow_html=True)
selected_level = st.sidebar.radio(
    "選擇目前目標級別：",
    ["國中部", "高中部", "多益 (TOEIC)"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")
st.sidebar.info(f"💡 目前模式：專注於 {selected_level} 雲端單字訓練。")

# -------------------------------------------------------------------------
# 2. 簡繁轉換與雲端資料載入核心
# -------------------------------------------------------------------------
S2T_DICT = {
    "餐厅": "餐廳", "饭厅": "餐廳", "计算机": "電腦", "网络": "網路", 
    "软件": "軟體", "硬件": "硬體", "信息": "資訊", "视频": "影片", 
    "音频": "音訊", "文件": "檔案", "打印": "列印", "鼠标": "滑鼠", 
    "键盘": "鍵盤", "屏幕": "螢幕", "项目": "專案", "组": "組", 
    "默认": "預設", "句": "句", "词": "詞", "语法": "語法"
}

def simple_s2t_convert(text):
    if not text:
        return text
    for s, t in S2T_DICT.items():
        text = text.replace(s, t)
    return text

def load_vocab_from_cloud():
    sheet_url = st.session_state.get("sheet_url", "")
    if not sheet_url:
        # 若尚未設定雲端連結，則提供預設範例 DataFrame 避免報錯
        data = {
            "word": ["person", "kitchen", "crack"],
            "phonetic": ["/ˈpɜːrsn/", "/ˈkɪtʃən/", "/kræk/"],
            "part_of_speech": ["n.", "n.", "n. / v."],
            "definition": ["人物；人", "廚房", "破裂；裂痕"],
            "basic_sentence": [
                "He is a very kind person in our class.", 
                "Mom is cooking delicious dinner in the kitchen.", 
                "There is a small crack on the window."
            ],
            "unit_tag": ["國一上 > 第一課", "國一上 > 第二課", "國一上 > 第二課"]
        }
        return pd.DataFrame(data)
    try:
        df = pd.read_csv(sheet_url)
        # 確保必要欄位存在
        expected_cols = ['word', 'definition', 'basic_sentence', 'unit_tag']
        for col in expected_cols:
            if col not in df.columns:
                df[col] = ""
        df['unit_tag'] = df['unit_tag'].fillna('國一上 > 第一課')
        df['word'] = df['word'].astype(str).str.strip()
        df['definition'] = df['definition'].apply(simple_s2t_convert)
        return df
    except Exception as e:
        st.error(f"⚠️ 無法讀取 Google Sheets 連結，請確認該試算表已設為「知道連結的任何人都能檢視」，且網址結尾為 export?format=csv。錯誤訊息：{e}")
        return pd.DataFrame(columns=['word', 'phonetic', 'part_of_speech', 'definition', 'basic_sentence', 'unit_tag'])

# -------------------------------------------------------------------------
# 3. 核心工具函式
# -------------------------------------------------------------------------
def clean_sentence(text):
    if not text or pd.isna(text):
        return ""
    text = re.sub(r'\s*\(.*?\)', '', str(text)).strip()
    if "example sentence using" in text.lower():
        return ""
    return text

def get_or_generate_sentence(word):
    w = word.strip()
    return f"We can easily see how {w} is used in our daily communication."

@st.cache_data(show_spinner=False)
def generate_audio_bytes(text, lang='en'):
    tts = gTTS(text=text, lang=lang)
    fp = io.BytesIO()
    tts.write_to_fp(fp)
    return fp.getvalue()

# -------------------------------------------------------------------------
# 4. 主畫面佈局
# -------------------------------------------------------------------------
st.title("📚 我愛背單字 (Google Sheets 雲端版)")

df_vocab = load_vocab_from_cloud()
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
    st.info("💡 提示：使用 Google Sheets 雲端版時，建議您直接在您的 Google 試算表中新增與維護單字、中文釋義與例句，雲端更新後此處會同步載入！")
    
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        semester = st.selectbox("選擇年級學期：", ["國一上", "國一下", "國二上", "國二下", "國三上", "國三下"])
    with col_u2:
        unit = st.selectbox("選擇課次單元：", ["第一課", "第二課", "第三課", "第四課", "第五課", "第六課"])
        
    current_unit_tag = f"{semester} > {unit}"
    st.markdown(f"📌 目前歸類單元：**{current_unit_tag}**")

elif main_menu == "📖 雲端字庫管理":
    df_vocab = load_vocab_from_cloud()
    if df_vocab.empty:
        st.warning("📭 雲端資料庫目前無資料，請檢查您的 Google Sheets 連結！")
    else:
        unit_list = sorted(df_vocab['unit_tag'].dropna().unique().tolist()) + ["全部單字"]
        selected_unit_filter = st.selectbox("依學習單元篩選：", unit_list)
        filtered_df = df_vocab if selected_unit_filter == "全部單字" else df_vocab[df_vocab['unit_tag'] == selected_unit_filter]
        
        search_query = st.text_input("🔍 搜尋雲端單字或釋義：")
        if search_query:
            filtered_df = filtered_df[filtered_df['word'].str.contains(search_query, case=False, na=False) | filtered_df['definition'].str.contains(search_query, case=False, na=False)]
        
        with st.expander("📋 雲端單字清單預覽", expanded=True):
            st.dataframe(filtered_df, use_container_width=True, hide_index=True)

elif main_menu == "🎯 沉浸式閃卡複習":
    df_vocab_flash = load_vocab_from_cloud()
    if df_vocab_flash.empty:
        st.warning("📭 雲端尚無單字！")
    else:
        if "flashcard_index" not in st.session_state:
            st.session_state.flashcard_index = 0
        total_count = len(df_vocab_flash)
        st.session_state.flashcard_index = st.session_state.flashcard_index % total_count
        row = df_vocab_flash.iloc[st.session_state.flashcard_index]
        
        with st.container(border=True):
            st.markdown(f"<h1 style='text-align: center; font-size: 54px;'>🔤 {row['word']}</h1>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align: center; color: gray;'>{row.get('phonetic','')} | {row.get('part_of_speech','')}</p>", unsafe_allow_html=True)
            
        with st.expander("💡 詳細釋義與例句", expanded=True):
            st.markdown(f"**中文釋義：** {row['definition']}")
            display_sent = clean_sentence(row.get('basic_sentence', ''))
            if not display_sent:
                display_sent = get_or_generate_sentence(row['word'])
            st.markdown(f"**基礎例句：** {display_sent}")
        
        c1, c2 = st.columns(2)
        if c1.button("⬅️ 上一個", use_container_width=True):
            st.session_state.flashcard_index = (st.session_state.flashcard_index - 1) % total_count
            st.rerun()
        if c2.button("➡️ 下一個", use_container_width=True):
            st.session_state.flashcard_index = (st.session_state.flashcard_index + 1) % total_count
            st.rerun()

elif main_menu == "🎮 拼字王挑戰遊戲":
    df_vocab_game = load_vocab_from_cloud()
    if df_vocab_game.empty:
        st.warning("📭 雲端目前沒有足夠的單字來進行遊戲！")
    else:
        unit_list_game = ["全部單字"] + sorted(df_vocab_game['unit_tag'].dropna().unique().tolist())
        selected_game_unit = st.selectbox("選擇遊戲挑戰的單元範圍：", unit_list_game, key="game_unit_select")
        df_vocab_game = df_vocab_game if selected_game_unit == "全部單字" else df_vocab_game[df_vocab_game['unit_tag'] == selected_game_unit]
        
        if df_vocab_game.empty:
            st.warning("📭 該分類中沒有單字！")
        else:
            game_mode = st.radio("選擇挑戰模式：", ["🟢 經典單字挑戰 (考卷填空克漏字 + 單字發音)", "🔴 進階盲拼挑戰 (聽中文定義發音 + 打單字)"], horizontal=True)

            if "game_errors" not in st.session_state:
                st.session_state.game_errors = 0

            if "current_game_item" not in st.session_state or st.session_state.get("game_scope_lock") != selected_game_unit:
                st.session_state.game_scope_lock = selected_game_unit
                row = df_vocab_game.sample(1).iloc[0]
                w = str(row['word']).strip()
                
                db_b = clean_sentence(row.get('basic_sentence', ''))
                if not db_b or w.lower() not in db_b.lower():
                    active_b = get_or_generate_sentence(w)
                else:
                    active_b = db_b

                word_audio = generate_audio_bytes(w, lang='en')
                
                st.session_state.current_game_item = {
                    "word": w,
                    "definition": row.get('definition', ''),
                    "unit_tag": row.get('unit_tag', ''),
                    "basic_sentence": active_b,
                    "audio_bytes": word_audio
                }

            item = st.session_state.current_game_item
            word_str = item["word"]
            hint_masked = "".join([" _ " if c.isalpha() else "   " for c in word_str])
            
            with st.container(border=True):
                st.markdown(f"### ❌ 累積答錯題數：`{st.session_state.game_errors} 次` &nbsp;|&nbsp; 🏷️ {item['unit_tag']}")
                
                # 模式一：經典單字挑戰 (考卷填空克漏字)
                if "經典" in game_mode:
                    masked_basic = re.sub(re.escape(word_str), '______', item['basic_sentence'], flags=re.IGNORECASE)
                    
                    st.markdown(f"**📖 考卷填空題 (Context Sentence)：**")
                    st.markdown(f"> ### {masked_basic}")
                    
                    col_a1, col_a2 = st.columns([1, 4])
                    with col_a1:
                        st.markdown("<div style='margin-top: 15px;'>**🔊 單字發音 (Pronunciation)：**</div>", unsafe_allow_html=True)
                    with col_a2:
                        try:
                            st.audio(item["audio_bytes"], format="audio/mp3")
                        except Exception:
                            st.warning("發音載入失敗。")
                            
                # 模式二：進階盲拼挑戰
                else:
                    st.markdown("### 🎧 Listen to the pronunciation and spell the word based on its definition!")
                    st.markdown(f"**📌 中文釋義提示：** `{item['definition']}`")
                    
                    col_a1, col_a2 = st.columns([1, 4])
                    with col_a1:
                        st.markdown("<div style='margin-top: 15px;'>**🔊 Audio Prompt：**</div>", unsafe_allow_html=True)
                    with col_a2:
                        try:
                            st.audio(item["audio_bytes"], format="audio/mp3")
                        except Exception:
                            st.warning("發音載入失敗。")

                st.markdown(f"**🔤 拼字提示 (Spelling Hint)：** `{hint_masked}` &nbsp;&nbsp; (Length: {len(word_str)} letters)")

            user_guess = st.text_input("Enter your spelling answer:", key="game_input_box").strip().lower()
            
            col_g1, col_g2 = st.columns(2)
            with col_g1:
                submit_guess = st.button("🚀 Submit Answer", type="primary", use_container_width=True)
            with col_g2:
                skip_question = st.button("🔄 Next Question", use_container_width=True)

            if submit_guess:
                if user_guess == word_str.lower():
                    st.success(f"🎉 Correct! Excellent job! The word is **{word_str}**")
                    time.sleep(0.8)
                    if "current_game_item" in st.session_state:
                        del st.session_state["current_game_item"]
                    st.rerun()
                else:
                    st.session_state.game_errors += 1
                    st.error("❌ Incorrect! Try again, you can do it!")

            if skip_question:
                if "current_game_item" in st.session_state:
                    del st.session_state["current_game_item"]
                st.rerun()