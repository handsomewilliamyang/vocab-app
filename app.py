import hmac
import html
import json
import random
import re

import gspread
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from google.oauth2.service_account import Credentials

st.set_page_config(
    page_title="我愛背單字",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 14px !important;
        border: 1px solid rgba(128, 128, 128, 0.2) !important;
        padding: 20px !important;
        background-color: rgba(128, 128, 128, 0.03) !important;
        animation: fadeIn 0.25s ease-in-out;
    }
    @keyframes fadeIn {
        from { opacity: 0.4; transform: translateY(4px); }
        to { opacity: 1; transform: translateY(0); }
    }
    div[data-testid="stForm"] [data-testid="stHorizontalBlock"] {
        align-items: flex-end !important;
    }
    .stDataFrame [data-testid="stTable"] td {
        white-space: normal !important;
        word-wrap: break-word !important;
        height: auto !important;
        padding-top: 12px !important;
        padding-bottom: 12px !important;
        font-size: 15px !important;
    }
    [data-testid="stSidebar"] .stRadio label p {
        font-size: 18px !important;
        font-weight: 500 !important;
    }
    [data-testid="stSidebar"] h5 {
        font-size: 17px !important;
        font-weight: 600;
    }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# 🔒 密碼保護（選用）：在 secrets 加一行  app_password = "你的密碼"  就會啟用；
# 沒設定就不會要求密碼。
# ---------------------------------------------------------------------
APP_PASSWORD = str(st.secrets.get("app_password", ""))
if APP_PASSWORD and not st.session_state.get("_authed"):
    st.title("🔒 我愛背單字")
    pw = st.text_input("請輸入密碼：", type="password")
    if pw:
        if hmac.compare_digest(pw.encode(), APP_PASSWORD.encode()):
            st.session_state["_authed"] = True
            st.rerun()
        else:
            st.error("密碼錯誤")
    st.stop()

main_menu = st.sidebar.radio(
    "選擇主要功能：",
    ["✨ 新增單字", "📖 字彙管理", "🎯 背誦單字", "🎮 我是拼字王"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")
st.sidebar.markdown("##### 📚 選擇級別")

selected_level = st.sidebar.radio(
    "選擇級別：",
    ["國中部", "高中部", "TOEIC"],
    label_visibility="collapsed"
)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "<p style='text-align: center; color: gray; font-size: 13px; margin-top: 20px;'>版權所有，切勿模仿</p>",
    unsafe_allow_html=True
)

current_sheet_name = selected_level
st.title("📚 我愛背單字")

# 儲存後的提示訊息（因為存完會 rerun，訊息要先存起來，重跑後才顯示）
if st.session_state.get("_flash"):
    st.success(st.session_state.pop("_flash"))
if st.session_state.get("_warn"):
    st.warning(st.session_state.pop("_warn"))

ALL_SEM = "全部單字"
ALL_UNIT = "全部單元"

# 欄位順序固定放這裡，存檔時共用
HEADERS = ['id', 'word', 'phonetic', 'part_of_speech', 'definition',
           'advanced_sentence', 'basic_sentence', 'collocations', 'unit_tag', 'srs_stage']

# 可編輯的欄位（預覽表、總表共用）
EDIT_COLS = ['word', 'part_of_speech', 'definition',
             'advanced_sentence', 'basic_sentence', 'collocations']

# 學期/篇章的顯示順序
SEM_ORDER = [
    "國一上", "國一下", "國二上", "國二下", "國三上", "國三下",
    "高一上", "高一下", "高二上", "高二下", "高三上", "高三下",
    "旅館篇", "旅遊篇", "交通篇", "公司篇", "醫療篇",
]


@st.cache_resource(show_spinner=False)
def init_gsheets_client():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    return gspread.authorize(creds)


@st.cache_resource(show_spinner=False)
def get_active_worksheet(_client, sheet_url, sheet_name):
    spreadsheet = _client.open_by_url(sheet_url)
    try:
        return spreadsheet.worksheet(sheet_name)
    except Exception:
        return spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=10)


@st.cache_data(ttl=300, show_spinner=False)
def load_vocab_dataframe(_worksheet, cache_key):
    # 讀取失敗時讓錯誤直接往上丟（由下方 try/except 顯示並停止），
    # 不可以變成「空表」，否則之後存檔會把雲端資料蓋掉。
    all_values = _worksheet.get_all_values()

    if len(all_values) > 1:
        headers = [str(h).strip().lower() for h in all_values[0]]
        df_temp = pd.DataFrame(all_values[1:], columns=headers[:len(all_values[0])])
    else:
        df_temp = pd.DataFrame(columns=HEADERS)

    for col in HEADERS:
        if col not in df_temp.columns:
            df_temp[col] = ""

    df_temp = df_temp.fillna("").astype(str)
    df_temp = df_temp.replace({"nan": "", "None": "", "none": ""})
    df_temp = df_temp[df_temp['word'].str.strip() != ''].reset_index(drop=True)

    def normalize_tag(tag):
        t = str(tag).strip()
        if '>' in t:
            parts = t.split('>', 1)
            return f"{parts[0].strip()} > {parts[1].strip()}"
        return t

    df_temp['unit_tag'] = df_temp['unit_tag'].apply(normalize_tag)
    return df_temp


try:
    with st.spinner("⏳ 正在從雲端載入單字資料庫..."):
        gs_client = init_gsheets_client()
        active_worksheet = get_active_worksheet(gs_client, st.secrets["sheet_url"], current_sheet_name)
        df_vocab = load_vocab_dataframe(active_worksheet, current_sheet_name)
except Exception as e:
    st.error(f"⚠️ 連線或讀取 Google 試算表發生錯誤：{e}")
    st.stop()

# 套用本機已存的熟練度（背誦時按「記得」不用每次重讀整張表）
for (_sheet, _rid), _stg in st.session_state.get("srs_local", {}).items():
    if _sheet == current_sheet_name:
        df_vocab.loc[df_vocab['id'].astype(str) == _rid, 'srs_stage'] = str(_stg)

unique_words = df_vocab['word'].str.strip().str.lower().nunique() if not df_vocab.empty else 0
col_m1, col_m2 = st.columns(2)
col_m1.metric(label="雲端單字量", value=f"{unique_words} 個單字／{len(df_vocab)} 筆",
              help="「筆」= 資料列數；同一個單字有多個詞性、或出現在不同單元時，會算多筆。")
clean_mode_name = main_menu.replace("✨ ", "").replace("📖 ", "").replace("🎯 ", "").replace("🎮 ", "")
col_m2.metric(label="目前模式", value=f"{clean_mode_name}【{selected_level}】")
st.markdown("<br>", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# 簡體 → 繁體（簡易版）。已拿掉「文件、项目」：它們繁簡同形，會誤改正常的繁體字。
# ---------------------------------------------------------------------
S2T_DICT = {
    "餐厅": "餐廳", "饭厅": "餐廳", "计算机": "電腦", "网络": "網路",
    "软件": "軟體", "硬件": "硬體", "信息": "資訊", "视频": "影片",
    "音频": "音訊", "打印": "列印", "鼠标": "滑鼠",
    "键盘": "鍵盤", "屏幕": "螢幕", "组": "組",
    "默认": "預設", "词": "詞", "语法": "語法"
}


def simple_s2t_convert(text):
    if not text:
        return text
    for s, t in S2T_DICT.items():
        text = text.replace(s, t)
    return text


# ---------------------------------------------------------------------
# 解析輸入（不使用 AI、不連外部字典：沒填的欄位就留空白）
# ---------------------------------------------------------------------
# 詞性標記，前面不能緊接英文字母（避免把 "Mon." 之類的字誤判成 n.）
POS_RE = re.compile(r'(?<![A-Za-z])(v|n|adj|adv|prep|conj|pron|phr|aux)\.', re.IGNORECASE)
SEP_CHARS = ';,；，、 '


def make_record(word, pos, definition, eng="", sent="", colloc=""):
    return {
        "word": word,
        "phonetic": "",
        "part_of_speech": pos,
        "definition": definition,
        "advanced_sentence": eng,
        "basic_sentence": sent,
        "collocations": colloc,
    }


def split_def_by_pos(text):
    """'v.張貼；n.職位' → [('v.', '張貼'), ('n.', '職位')]，每個詞性各自對應自己的釋義。"""
    parts = POS_RE.split(text)  # [前面的字, 詞性, 釋義, 詞性, 釋義, ...]
    lead = parts[0].strip(SEP_CHARS)
    pairs = []
    for i in range(1, len(parts), 2):
        pos = parts[i].lower() + '.'
        d = parts[i + 1].strip(SEP_CHARS)
        pairs.append([pos, d])
    if pairs and lead:
        pairs[0][1] = f"{lead}；{pairs[0][1]}" if pairs[0][1] else lead
    return [(p, d) for p, d in pairs]


def parse_mixed_vocab_input(word, raw_def="", pasted_pos="", pasted_eng_def="",
                            pasted_sent="", pasted_colloc=""):
    w_clean = word.strip()
    cleaned_def = simple_s2t_convert(raw_def.strip()) if raw_def else ""
    records = []

    # 1) 使用者直接指定詞性（用 | 格式貼上時）
    if pasted_pos:
        pos_list = [p.strip() for p in re.split(r'[,/]', pasted_pos) if p.strip()]
        for p in pos_list:
            records.append(make_record(w_clean, simple_s2t_convert(p), cleaned_def,
                                       pasted_eng_def, pasted_sent, pasted_colloc))
        if records:
            return records

    # 2) 釋義裡有 v. n. adj. 等標記 → 一個詞性一筆
    pairs = split_def_by_pos(cleaned_def)
    if pairs:
        for pos, d in pairs:
            records.append(make_record(w_clean, pos, d, pasted_eng_def, pasted_sent, pasted_colloc))
        return records

    # 3) 都沒有 → 猜一個詞性
    fallback_pos = "phr." if " " in w_clean else "n."
    records.append(make_record(w_clean, fallback_pos, cleaned_def,
                               pasted_eng_def, pasted_sent, pasted_colloc))
    return records


# 切開「英文單字」與「後面的釋義」：遇到第一個中文字或詞性標記就切
SPLIT_RE = re.compile(r'[\u4e00-\u9fa5]|(?<![A-Za-z])(?:v|n|adj|adv|prep|conj|pron|phr)\.', re.IGNORECASE)


def parse_raw_vocab_line_advanced(line):
    # 只去掉「1. 」「2) 」「3、」「4 」這種行首編號；像 3D 這種單字不會被吃掉
    line_clean = re.sub(r'^\d+[\.\)、\s]+', '', line).strip()
    if not line_clean:
        return []

    if '|' in line_clean:
        parts = [p.strip() for p in line_clean.split('|')]
        w = parts[0]
        d = parts[1] if len(parts) > 1 else ""
        pasted_p = parts[2] if len(parts) > 2 else ""
        pasted_eng = parts[3] if len(parts) > 3 else ""
        pasted_s = parts[4] if len(parts) > 4 else ""
        pasted_c = parts[5] if len(parts) > 5 else ""
        return parse_mixed_vocab_input(w, raw_def=d, pasted_pos=pasted_p,
                                       pasted_eng_def=pasted_eng, pasted_sent=pasted_s,
                                       pasted_colloc=pasted_c)

    match_split = SPLIT_RE.search(line_clean)
    if not match_split:
        return [make_record(line_clean, "phr." if " " in line_clean else "n.", "")]

    word_end_idx = match_split.start()
    word = line_clean[:word_end_idx].strip()
    rest = line_clean[word_end_idx:].strip()

    if not word:
        parts = line_clean.split(maxsplit=1)
        word = parts[0] if len(parts) > 0 else line_clean
        rest = parts[1] if len(parts) > 1 else ""

    return parse_mixed_vocab_input(word, raw_def=rest)


def ai_prompt_text(level):
    """給你複製到任何 AI 的固定提示詞；輸出格式剛好是下方批次貼上可以直接吃的格式。"""
    return f"""請幫我整理英文單字，對象是台灣的「{level}」學生。我會在最後貼上單字清單，請每個單字輸出一行，格式固定為（用 | 分隔；不要加編號、不要加表格、不要加任何說明文字）：
單字 | 中文釋義 | 詞性 | 英文釋義 | 例句 | 搭配詞

規則：
1. 中文用繁體中文（台灣用語），釋義簡短。
2. 詞性用縮寫：n. v. adj. adv. prep. conj. pron. phr.；一個單字有多個常見詞性時，每個詞性各寫一行。
3. 英文釋義用簡單英文寫一句話，不要在釋義裡直接使用該單字。
4. 例句要自然、日常、母語者真的會說；字義必須符合該行的中文與詞性；難度適合「{level}」學生；不要荒謬、誇張或硬湊的句子。
5. 搭配詞給 2～3 個母語者真實常用的，用 / 分隔；沒把握就少給，不要編造。
6. 不確定的欄位請留空，不要亂填。

單字清單：
（把單字貼在這裡）"""


# ---------------------------------------------------------------------
# 存檔
# ---------------------------------------------------------------------
def save_all_vocab_to_sheet(_worksheet, df):
    """整張覆寫（只有「修改舊資料」或「刪除」才會用到）。
    先把新內容寫進去，再清掉多出來的尾巴，中途出錯雲端也不會變成空表。"""
    try:
        out = df.reindex(columns=HEADERS).fillna("").astype(str)
        rows = [HEADERS] + out.values.tolist()
        if len(rows) > _worksheet.row_count:
            _worksheet.resize(rows=len(rows) + 200)
        _worksheet.update(values=rows, range_name="A1", value_input_option="RAW")
        _worksheet.batch_clear([f"A{len(rows) + 1}:J"])
        st.session_state["srs_local"] = {}
        st.session_state[f"_hdr_ok_{_worksheet.title}"] = True
        load_vocab_dataframe.clear()
        return True, "成功"
    except Exception as e:
        return False, str(e)


def get_next_id(df):
    """目前最大編號 + 1（刪過資料後編號才不會重複）。"""
    ids = pd.to_numeric(df['id'], errors='coerce').dropna()
    return int(ids.max()) + 1 if not ids.empty else 1


def persist_changes(_worksheet, df_after, new_rows, updated, was_empty):
    """只有新增 → 只在表格最後面補幾列（快）；
    有修改舊資料、原本是空表、或雲端標題列順序和程式不同 → 整張覆寫。"""
    hkey = f"_hdr_ok_{_worksheet.title}"
    if hkey not in st.session_state:
        try:
            header = [str(h).strip().lower() for h in _worksheet.row_values(1)]
            st.session_state[hkey] = header[:len(HEADERS)] == HEADERS
        except Exception:
            st.session_state[hkey] = False
    if updated or was_empty or not st.session_state[hkey]:
        return save_all_vocab_to_sheet(_worksheet, df_after)
    if not new_rows:
        return True, "沒有變更"
    try:
        values = [[str(r.get(h, '')) for h in HEADERS] for r in new_rows]
        _worksheet.append_rows(values, value_input_option="RAW", table_range="A1")
        load_vocab_dataframe.clear()
        return True, "成功"
    except Exception as e:
        return False, str(e)


def merge_records(df_current, records, unit_tag):
    """把解析好的資料併入 df_current：同單字+同詞性+同單元 → 更新（只更新有填的欄位）；否則新增。
    回傳 (df, 新增的列, 是否有更新舊資料, stats)；stats = 新增/更新/重複略過 各幾筆。"""
    new_rows = []
    updated = False
    stats = {"new": 0, "updated": 0, "same": 0}
    for data in records:
        word = str(data.get('word', '')).strip()
        pos = str(data.get('part_of_speech', '')).strip()
        if not word:
            continue

        mask = None
        if not df_current.empty:
            mask = (
                (df_current['word'].astype(str).str.strip().str.lower() == word.lower()) &
                (df_current['part_of_speech'].astype(str).str.strip().str.lower() == pos.lower()) &
                (df_current['unit_tag'].astype(str).str.strip() == unit_tag)
            )

        if mask is not None and mask.any():
            idx = df_current.index[mask][0]
            changed = False
            for col in ['definition', 'advanced_sentence', 'basic_sentence', 'collocations']:
                v = str(data.get(col, '') or '').strip()
                if v and str(df_current.at[idx, col]) != v:
                    df_current.at[idx, col] = v
                    changed = True
            if changed:
                updated = True
                stats["updated"] += 1
            else:
                stats["same"] += 1
        else:
            new_row = {
                'id': get_next_id(df_current),
                'word': word,
                'phonetic': '',
                'part_of_speech': pos,
                'definition': data.get('definition', ''),
                'advanced_sentence': data.get('advanced_sentence', ''),
                'basic_sentence': data.get('basic_sentence', ''),
                'collocations': data.get('collocations', ''),
                'unit_tag': unit_tag,
                'srs_stage': 0
            }
            new_rows.append(new_row)
            df_current = pd.concat([df_current, pd.DataFrame([new_row])], ignore_index=True)
            stats["new"] += 1
    return df_current, new_rows, updated, stats


def result_text(stats):
    parts = [f"新增 {stats['new']} 筆"]
    if stats["updated"]:
        parts.append(f"更新 {stats['updated']} 筆")
    if stats["same"]:
        parts.append(f"重複略過 {stats['same']} 筆")
    return "、".join(parts)


def clean_rows(df):
    """把表格（可能含 NaN）整理成乾淨的 dict 清單，空白單字的列直接丟掉。"""
    rows = []
    for _, row in df.iterrows():
        rec = {}
        for c in EDIT_COLS:
            v = row.get(c)
            rec[c] = "" if pd.isna(v) else str(v).strip()
        if rec["word"] and rec["word"].lower() not in ("nan", "none"):
            rows.append(rec)
    return rows


# ---------------------------------------------------------------------
# 學期 / 單元
# ---------------------------------------------------------------------
def parse_lesson_number(unit_str):
    order_map = {
        '第一課': 1, '第二課': 2, '第三課': 3, '第四課': 4, '第五課': 5,
        '第六課': 6, '第七課': 7, '第八課': 8, '第九課': 9, '第十課': 10,
        '上': 1, '中': 2, '下': 3
    }
    for k, v in order_map.items():
        if k in unit_str:
            return v
    return 99


def sem_sort_key(sem):
    return (SEM_ORDER.index(sem) if sem in SEM_ORDER else 999, sem)


def get_hierarchical_units(df):
    semesters = []
    semester_to_units = {}
    if 'unit_tag' in df.columns:
        for ut in df['unit_tag'].dropna().unique():
            ut_str = str(ut).strip()
            if not ut_str or '>' not in ut_str:
                continue
            sem, un = ut_str.split('>', 1)
            sem = sem.strip()
            un = un.strip()
            if sem not in semesters:
                semesters.append(sem)
            semester_to_units.setdefault(sem, [])
            if un not in semester_to_units[sem]:
                semester_to_units[sem].append(un)

    for sem in semester_to_units:
        semester_to_units[sem].sort(key=parse_lesson_number)

    return sorted(semesters, key=sem_sort_key), semester_to_units


def scope_mask(df, sem, unit):
    """依「學期/篇章、單元」回傳要包含哪些列。"""
    if sem == ALL_SEM:
        return pd.Series(True, index=df.index)
    tags = df['unit_tag'].astype(str)
    if unit == ALL_UNIT:
        return tags.str.startswith(f"{sem} >")
    return tags == f"{sem} > {unit}"


# ---------------------------------------------------------------------
# 發音：瀏覽器內建語音，不用連網
# ---------------------------------------------------------------------
def speech_html(text, justify="flex-start"):
    t = json.dumps(text).replace("</", "<\\/")
    return f"""
<style>
  body {{ margin:0; display:flex; align-items:center; justify-content:{justify};
         gap:10px; height:100vh; overflow:hidden; background:transparent; }}
  button {{ background:rgba(255,255,255,.2); border:1px solid rgba(255,255,255,.5);
           border-radius:6px; cursor:pointer; font-size:15px; padding:8px 16px;
           color:#fff; font-weight:600; font-family:'Segoe UI',sans-serif; }}
  button:hover {{ border-color:#ff4b4b; color:#ff4b4b; }}
  button:active {{ transform:scale(.95); }}
  @media (prefers-color-scheme: light) {{
    button {{ color:#333; border-color:rgba(0,0,0,.2); }}
  }}
</style>
<button onclick="say('en-US')">US 美式</button>
<button onclick="say('en-GB')">GB 英式</button>
<button onclick="say('en-AU')">AU 澳洲</button>
<script>
  const T = {t};
  function say(lang) {{
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(T);
    u.lang = lang; u.rate = 0.9;
    speechSynthesis.speak(u);
  }}
</script>
"""


def esc(x):
    """放進 HTML 之前先跳脫，避免單字或例句裡有 < > & 把畫面弄壞。"""
    return html.escape(str(x))


def mask_word(text, word, repl="____"):
    """把釋義裡出現的答案單字（含 -ing、-ed 等變化）遮起來，避免進階模式直接洩漏答案。"""
    if not text or not word:
        return text
    return re.sub(r'\b' + re.escape(word.strip()) + r'\w*', repl, text, flags=re.IGNORECASE)


def norm_answer(s):
    return " ".join(str(s).lower().split())


# ---------------------------------------------------------------------
# 熟練度（srs_stage 0~5）
# ---------------------------------------------------------------------
def parse_stage(v):
    try:
        return max(0, min(5, int(float(str(v).strip()))))
    except Exception:
        return 0


SRS_FLUSH_EVERY = 8   # 累積幾筆熟練度就同步一次到雲端


def _a1(row, col):
    letters = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row}"


def queue_srs_stage(row, new_stage):
    """按「記得／不記得」只先記在本機（瞬間完成），之後再批次寫入雲端。"""
    rid = str(row.get("id", "")).strip()
    word = str(row.get("word", "")).strip().lower()
    st.session_state.setdefault("srs_pending", {})[(current_sheet_name, rid)] = (word, new_stage)
    st.session_state.setdefault("srs_local", {})[(current_sheet_name, rid)] = new_stage
    row["_stage"] = new_stage


def flush_srs():
    """把累積的熟練度一次寫進雲端：不管幾筆，都只用 4 次 API 呼叫（讀標題、讀編號欄、讀單字欄、一次批次寫入）。
    寫入前會確認編號對應的單字沒變，避免寫錯列。成功回傳 True。"""
    pend = st.session_state.get("srs_pending", {})
    if not pend:
        return True
    by_sheet = {}
    for (sheet, rid), (word, stage) in pend.items():
        by_sheet.setdefault(sheet, {})[rid] = (word, stage)
    all_ok = True
    for sheet, items in by_sheet.items():
        try:
            ws = get_active_worksheet(gs_client, st.secrets["sheet_url"], sheet)
            hdr = [str(h).strip().lower() for h in ws.row_values(1)]
            c_id, c_word, c_srs = hdr.index("id") + 1, hdr.index("word") + 1, hdr.index("srs_stage") + 1
            ids = ws.col_values(c_id)
            words = ws.col_values(c_word)
            row_of = {}
            for i, v in enumerate(ids):
                row_of.setdefault(str(v).strip(), i + 1)
            data = []
            for rid, (word, stage) in items.items():
                rn = row_of.get(rid)
                if rn and rn <= len(words) and str(words[rn - 1]).strip().lower() == word:
                    data.append({"range": _a1(rn, c_srs), "values": [[stage]]})
            if data:
                ws.batch_update(data, value_input_option="RAW")
            for rid in items:          # 寫成功，或確定對不上（資料已變動）→ 都從待寫清單移除
                pend.pop((sheet, rid), None)
        except Exception:
            all_ok = False             # 失敗就留著，下次再試
    return all_ok


def save_row_edits(changes, orig):
    """只更新有修改的那幾列（一次 batch_update），不重寫整張表。
    回傳 (成功與否, 套用幾筆, 略過幾筆, 錯誤訊息)；成功與否為 None 表示雲端欄位順序不同，要改用整張覆寫。"""
    try:
        hdr = [str(h).strip().lower() for h in active_worksheet.row_values(1)]
        if hdr[:len(HEADERS)] != HEADERS:
            return None, 0, 0, ""
        ids = active_worksheet.col_values(1)
        words = active_worksheet.col_values(2)
        row_of = {}
        for i, v in enumerate(ids):
            row_of.setdefault(str(v).strip(), i + 1)
        orig_word = dict(zip(orig['id'].astype(str), orig['word']))
        data, applied, skipped = [], 0, 0
        for rid, vals in changes.items():
            rn = row_of.get(rid)
            if (not vals['word'] or not rn or rn > len(words)
                    or str(words[rn - 1]).strip().lower() != str(orig_word.get(rid, '')).strip().lower()):
                skipped += 1       # 單字空白，或雲端那一列已經不是原本那個字
                continue
            data.append({"range": f"B{rn}", "values": [[vals['word']]]})
            data.append({"range": f"D{rn}:H{rn}", "values": [[
                vals['part_of_speech'], simple_s2t_convert(vals['definition']),
                vals['advanced_sentence'], vals['basic_sentence'], vals['collocations']]]})
            applied += 1
        if data:
            active_worksheet.batch_update(data, value_input_option="RAW")
        load_vocab_dataframe.clear()
        return True, applied, skipped, ""
    except Exception as e:
        return False, 0, 0, str(e)


def save_row_edits_full(changes):
    """備援：整張覆寫（雲端欄位順序和程式不同時才會用到）。"""
    load_vocab_dataframe.clear()
    df_current = load_vocab_dataframe(active_worksheet, current_sheet_name).copy()
    applied, skipped = 0, 0
    for rid, vals in changes.items():
        m = df_current['id'].astype(str) == rid
        if not vals['word'] or not m.any():
            skipped += 1
            continue
        for c in EDIT_COLS:
            df_current.loc[m, c] = simple_s2t_convert(vals[c]) if c == 'definition' else vals[c]
        applied += 1
    if applied:
        ok, msg = save_all_vocab_to_sheet(active_worksheet, df_current)
        if not ok:
            return False, 0, 0, msg
    return True, applied, skipped, ""


def _num(v):
    x = pd.to_numeric(v, errors="coerce")
    return 0 if pd.isna(x) else x


def build_flash_queue(df, order_mode):
    items = []
    for _, r in df.iterrows():
        d = r.to_dict()
        d["_stage"] = parse_stage(d.get("srs_stage"))
        items.append(d)
    if order_mode == "依編號順序":
        items.sort(key=lambda d: _num(d.get("id")))
    else:
        random.shuffle(items)
        if order_mode == "不熟的優先":
            items.sort(key=lambda d: d["_stage"])   # 穩定排序：同熟練度內維持隨機
    return items


# ---------------------------------------------------------------------
# 批次匯入：先預覽、確認後才寫入
# ---------------------------------------------------------------------
def start_batch_preview(records, unit_tag, raw_text):
    existing = set(zip(
        df_vocab['word'].str.strip().str.lower(),
        df_vocab['part_of_speech'].str.strip().str.lower(),
        df_vocab['unit_tag']
    ))
    rows = []
    for r in records:
        key = (r["word"].strip().lower(), r["part_of_speech"].strip().lower(), unit_tag)
        status = "✏️ 已存在（會更新）" if key in existing else "🆕 新增"
        rows.append({"status": status, **{c: r.get(c, "") for c in EDIT_COLS}})
    st.session_state["preview_token"] = st.session_state.get("preview_token", 0) + 1
    st.session_state["pending_batch"] = {
        "rows": rows, "unit_tag": unit_tag, "sheet": current_sheet_name,
        "raw_text": raw_text, "token": st.session_state["preview_token"],
    }
    st.rerun()


def render_batch_preview():
    pb = st.session_state["pending_batch"]
    st.subheader("🔍 請先檢查，確認後才會寫入雲端")
    st.markdown(f"📍 **目標：** `{pb['sheet']} ({pb['unit_tag']})`　共 **{len(pb['rows'])}** 筆")
    st.caption("檢查重點：單字和中文有沒有切對位置？詞性對嗎？例句自然嗎？　"
               "點兩下格子可以直接修改；不要的整列，選取最左邊的框後按 Delete 刪除。「狀態」只是初步判斷。")

    wrong_sheet = pb["sheet"] != current_sheet_name
    if wrong_sheet:
        st.warning(f"這批資料是要匯入「{pb['sheet']}」的，目前側邊欄選的是「{current_sheet_name}」。請切回該級別再確認，或按取消。")

    edited = st.data_editor(
        pd.DataFrame(pb["rows"]),
        key=f"batch_preview_{pb['token']}",
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        disabled=["status"],
        column_config={
            "status": st.column_config.TextColumn("狀態", width="small"),
            "word": st.column_config.TextColumn("單字", width="small", required=True),
            "part_of_speech": st.column_config.TextColumn("詞性", width="small"),
            "definition": st.column_config.TextColumn("中文釋義", width="medium"),
            "advanced_sentence": st.column_config.TextColumn("英文釋義", width="large"),
            "basic_sentence": st.column_config.TextColumn("例句", width="large"),
            "collocations": st.column_config.TextColumn("搭配詞", width="medium"),
        },
    )

    c1, c2 = st.columns(2)
    if c1.button("✅ 確認寫入雲端", type="primary", use_container_width=True, disabled=wrong_sheet):
        rows = clean_rows(edited)
        if not rows:
            st.warning("表格裡沒有可寫入的單字。")
        else:
            with st.spinner("寫入雲端中…"):
                load_vocab_dataframe.clear()   # 寫入前重讀最新資料，避免蓋掉別處的修改
                df_current = load_vocab_dataframe(active_worksheet, current_sheet_name).copy()
                was_empty = df_current.empty
                df_current, new_rows, updated, stats = merge_records(df_current, rows, pb["unit_tag"])
                ok, msg = persist_changes(active_worksheet, df_current, new_rows, updated, was_empty)
            if not ok:
                st.error(f"寫入失敗：{msg}")
                st.stop()
            st.session_state["_flash"] = f"🎊 匯入完成：{result_text(stats)}"
            st.session_state["clear_paste"] = True
            st.session_state.pop("pending_batch", None)
            st.rerun()
    if c2.button("❌ 取消，不寫入", use_container_width=True):
        st.session_state["paste_restore"] = pb["raw_text"]   # 把剛貼的內容還給你
        st.session_state.pop("pending_batch", None)
        st.rerun()


# 離開「背誦單字」頁、或切換級別時，把累積的熟練度一次同步到雲端
_pend = st.session_state.get("srs_pending", {})
if _pend and (main_menu != "🎯 背誦單字" or any(k[0] != current_sheet_name for k in _pend)):
    if not flush_srs():
        st.session_state["_warn"] = "⚠️ 熟練度同步失敗（網路或 Google 限速），回到「背誦單字」頁按「立即同步」再試一次。"

# =====================================================================
# ✨ 新增單字
# =====================================================================
if main_menu == "✨ 新增單字":
    if st.session_state.get("pending_batch"):
        render_batch_preview()
    else:
        if selected_level == "國中部":
            semester = st.selectbox("選擇年級學期：", ["國一上", "國一下", "國二上", "國二下", "國三上", "國三下"])
            unit = st.selectbox("選擇課次單元：", ["第一課", "第二課", "第三課", "第四課", "第五課", "第六課", "第七課", "第八課", "第九課", "第十課"])
        elif selected_level == "高中部":
            semester = st.selectbox("選擇年級學期：", ["高一上", "高一下", "高二上", "高二下", "高三上", "高三下"])
            unit = st.selectbox("選擇課次單元：", ["第一課", "第二課", "第三課", "第四課", "第五課", "第六課", "第七課", "第八課", "第九課", "第十課"])
        else:
            semester = st.selectbox("選擇 TOEIC 主題篇章：", ["旅館篇", "旅遊篇", "交通篇", "公司篇", "醫療篇"])
            unit = st.selectbox("選擇課次：", ["第一課", "第二課", "第三課", "第四課"])

        current_unit_tag = f"{semester} > {unit}"
        st.markdown("---")

        # 匯入成功後清空貼上框、取消預覽後還原貼上內容（必須在 text_area 建立之前處理）
        if st.session_state.pop("clear_paste", False):
            st.session_state["paste_box"] = ""
        if "paste_restore" in st.session_state:
            st.session_state["paste_box"] = st.session_state.pop("paste_restore")

        col_input1, col_input2 = st.columns(2, gap="large")
        with col_input1:
            st.subheader("📝 單筆快速建檔")
            with st.form("single_add_form", clear_on_submit=True):
                single_word = st.text_input("輸入想要學習的英文單字：", placeholder="例如：resilient")
                single_def = st.text_input("中文釋義（選填）：", placeholder="例如：v.張貼；n.職位")
                single_eng = st.text_input("英文釋義（選填）：", placeholder="例如：able to recover quickly")
                single_sent = st.text_input("真實例句（選填）：", placeholder="例如：Sentence here")
                single_colloc = st.text_input("搭配詞（選填）：", placeholder="例如：Collocation here")
                submitted_single = st.form_submit_button("🚀 瞬間寫入雲端", type="primary", use_container_width=True)

            if submitted_single:
                if single_word.strip():
                    records = parse_mixed_vocab_input(
                        single_word, raw_def=single_def, pasted_eng_def=single_eng,
                        pasted_sent=single_sent, pasted_colloc=single_colloc
                    )
                    # 寫入前重讀一次最新資料，避免蓋掉別處的修改
                    load_vocab_dataframe.clear()
                    df_current = load_vocab_dataframe(active_worksheet, current_sheet_name).copy()
                    was_empty = df_current.empty

                    df_current, new_rows_list, any_updated, stats = merge_records(df_current, records, current_unit_tag)

                    ok, msg = persist_changes(active_worksheet, df_current, new_rows_list, any_updated, was_empty)
                    if not ok:
                        st.error(f"寫入失敗：{msg}")
                        st.stop()
                    st.session_state["_flash"] = f"🎉 {single_word.strip()}：{result_text(stats)}"
                    st.rerun()
                else:
                    st.warning("請先輸入英文單字")

        with col_input2:
            st.subheader("📋 智慧多格式快速貼上匯入")
            st.markdown(f"📍 **[狀態欄] 目前目標分類：** `{selected_level} ({current_unit_tag})`")

            with st.expander("🤖 懶得整理？複製這段給 AI，再把結果貼到下面"):
                st.caption("點程式碼框右上角的複製鈕 → 貼給任何 AI → 把單字清單貼在最後 → 把 AI 的回答整段貼回下面的框。")
                st.code(ai_prompt_text(selected_level), language=None)

            pasted_text = st.text_area(
                "貼上完整單字清單", key="paste_box",
                placeholder="source | 來源 | n. | A place... | Sentence | Collocation\n或：resilient 有彈性的\n或只貼單字：resilient",
                height=140, label_visibility="collapsed"
            )

            valid_lines = [l for l in pasted_text.strip().split('\n') if l.strip()] if pasted_text else []
            total_preview_count = len(valid_lines)
            if total_preview_count > 0:
                st.info(f"📊 **狀態預覽：** 偵測到 **{total_preview_count}** 個項目準備匯入至「{current_unit_tag}」")
            else:
                st.caption(f"📊 **狀態預覽：** 尚未貼上資料（目標：{current_unit_tag}）")

            if st.button("📥 解析並預覽", use_container_width=True):
                if valid_lines:
                    records_all = []
                    for line in valid_lines:
                        records_all.extend(parse_raw_vocab_line_advanced(line))
                    if records_all:
                        start_batch_preview(records_all, current_unit_tag, pasted_text)
                    else:
                        st.warning("沒有解析到任何單字，請檢查格式")
                else:
                    st.warning("請先貼上單字清單")

# =====================================================================
# 📖 字彙管理
# =====================================================================
elif main_menu == "📖 字彙管理":
    if df_vocab.empty:
        st.info("📭 目前雲端尚無單字，請至側邊欄新增！")
    else:
        semesters, sem_to_units = get_hierarchical_units(df_vocab)
        col_sel1, col_sel2 = st.columns(2, gap="medium")
        with col_sel1:
            selected_sem = st.selectbox("1️⃣ 選擇學期/篇章：", [ALL_SEM] + semesters)
        with col_sel2:
            if selected_sem == ALL_SEM:
                selected_unit = ALL_UNIT
                st.selectbox("2️⃣ 選擇單元/課次：", [ALL_UNIT], disabled=True)
            else:
                selected_unit = st.selectbox("2️⃣ 選擇單元/課次：", [ALL_UNIT] + sem_to_units.get(selected_sem, []))

        filtered_df = df_vocab[scope_mask(df_vocab, selected_sem, selected_unit)]

        col_f1, col_f2 = st.columns(2, gap="medium")
        with col_f1:
            search_query = st.text_input("🔍 搜尋單字或釋義：")
            if search_query:
                filtered_df = filtered_df[
                    filtered_df['word'].str.contains(search_query, case=False, na=False, regex=False) |
                    filtered_df['definition'].str.contains(search_query, case=False, na=False, regex=False)
                ]
        with col_f2:
            sub_col1, sub_col2 = st.columns([3, 1], gap="small")
            with sub_col1:
                # 以「那一筆」為單位刪除（同一個字不同詞性不會一起被刪）
                placeholder_opt = "--請選擇要刪除的單字--"
                del_map = {}
                for _, r in filtered_df.iterrows():
                    del_map[f"{r['word']}　{r['part_of_speech']}　(#{r['id']})"] = str(r['id'])
                word_to_delete = st.selectbox("🗑️ 快速刪除單字：", [placeholder_opt] + list(del_map.keys()))
                if word_to_delete != placeholder_opt:
                    if st.button("確認刪除這一筆", type="primary", use_container_width=True):
                        rid = del_map[word_to_delete]
                        load_vocab_dataframe.clear()
                        df_current = load_vocab_dataframe(active_worksheet, current_sheet_name).copy()
                        df_current = df_current[df_current['id'].astype(str) != rid].copy()
                        if not df_current.empty:
                            df_current['id'] = range(1, len(df_current) + 1)
                        ok, msg = save_all_vocab_to_sheet(active_worksheet, df_current)
                        if not ok:
                            st.error(f"刪除失敗：{msg}")
                            st.stop()
                        st.session_state["_flash"] = f"已刪除：{word_to_delete.split('　')[0]}"
                        st.rerun()
            with sub_col2:
                st.write("")
                st.write("")
                ctr = st.session_state.get("del_ctr", 0)
                confirm_unit_del = st.checkbox("確認", key=f"confirm_del_unit_{ctr}", help="勾選後才能刪除整個單元")
                if st.button("🗑️ 刪除該單元", type="secondary", use_container_width=True):
                    if selected_sem == ALL_SEM or selected_unit == ALL_UNIT:
                        st.warning("⚠️ 請先在上方選單選擇到具體某個單元，才能執行刪除！")
                    elif not confirm_unit_del:
                        st.warning("⚠️ 請先勾選「確認」。")
                    else:
                        target_tag = f"{selected_sem} > {selected_unit}"
                        load_vocab_dataframe.clear()
                        df_current = load_vocab_dataframe(active_worksheet, current_sheet_name).copy()
                        df_current = df_current[df_current['unit_tag'] != target_tag].copy()
                        if not df_current.empty:
                            df_current['id'] = range(1, len(df_current) + 1)
                        ok, msg = save_all_vocab_to_sheet(active_worksheet, df_current)
                        if not ok:
                            st.error(f"刪除失敗：{msg}")
                            st.stop()
                        st.session_state["del_ctr"] = ctr + 1   # 換一個新的勾選框，確認狀態才會重置
                        st.session_state["_flash"] = f"🗑️ 已成功刪除「{target_tag}」整單元單字！"
                        st.rerun()

        st.markdown("---")
        with st.expander("📋 單字總表（可直接點兩下修改，改完按「儲存修改」）", expanded=True):
            orig = filtered_df[['id'] + EDIT_COLS].reset_index(drop=True)
            edit_key = f"vocab_editor_{selected_level}_{st.session_state.get('edit_ver', 0)}_{hash(tuple(orig['id']))}"
            edited = st.data_editor(
                orig,
                key=edit_key,
                num_rows="fixed",
                hide_index=True,
                use_container_width=True,
                disabled=["id"],
                column_config={
                    "id": st.column_config.TextColumn("編號", width="small"),
                    "word": st.column_config.TextColumn("單字", width="medium"),
                    "part_of_speech": st.column_config.TextColumn("詞性", width="small"),
                    "definition": st.column_config.TextColumn("中文釋義", width="medium"),
                    "advanced_sentence": st.column_config.TextColumn("英文釋義", width="large"),
                    "basic_sentence": st.column_config.TextColumn("真實例句", width="large"),
                    "collocations": st.column_config.TextColumn("搭配詞", width="medium"),
                }
            )
            if st.button("💾 儲存修改", type="primary"):
                changes = {}
                for i in range(len(orig)):
                    new_vals = {c: ("" if pd.isna(edited.at[i, c]) else str(edited.at[i, c]).strip()) for c in EDIT_COLS}
                    if any(str(orig.at[i, c]) != new_vals[c] for c in EDIT_COLS):
                        changes[str(orig.at[i, 'id'])] = new_vals
                if not changes:
                    st.info("沒有偵測到任何修改。")
                else:
                    with st.spinner("儲存中…"):
                        res = save_row_edits(changes, orig)
                        if res[0] is None:     # 雲端欄位順序和程式不同 → 退回整張覆寫
                            res = save_row_edits_full(changes)
                    ok, applied, skipped, msg = res
                    if not ok:
                        st.error(f"儲存失敗：{msg}")
                        st.stop()
                    st.session_state["edit_ver"] = st.session_state.get("edit_ver", 0) + 1
                    note = f"💾 已儲存 {applied} 筆修改"
                    if skipped:
                        note += f"（{skipped} 筆因單字空白或資料已變動而略過）"
                    st.session_state["_flash"] = note
                    st.rerun()

        st.download_button(
            "⬇️ 下載備份（CSV，包含全部欄位）",
            data=df_vocab[HEADERS].to_csv(index=False).encode("utf-8-sig"),
            file_name=f"vocab_{selected_level}.csv",
            mime="text/csv",
        )

# =====================================================================
# 🎯 背誦單字
# =====================================================================
elif main_menu == "🎯 背誦單字":
    if df_vocab.empty:
        st.warning("📭 目前雲端沒有單字！")
    else:
        semesters, sem_to_units = get_hierarchical_units(df_vocab)
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            sel_sem_flash = st.selectbox("🎯 選擇學期/篇章：", [ALL_SEM] + semesters,
                                         key=f"flash_sem_select_{selected_level}")
        with col_f2:
            if sel_sem_flash == ALL_SEM:
                sel_unit_flash = ALL_UNIT
                st.selectbox("🎯 選擇單元/課次：", [ALL_UNIT], disabled=True,
                             key=f"flash_unit_disabled_{selected_level}")
            else:
                sel_unit_flash = st.selectbox("🎯 選擇單元/課次：",
                                              [ALL_UNIT] + sem_to_units.get(sel_sem_flash, []),
                                              key=f"flash_unit_select_{selected_level}")

        col_o1, col_o2 = st.columns(2)
        with col_o1:
            order_mode = st.radio("出題順序：", ["不熟的優先", "隨機", "依編號順序"], horizontal=True, key="flash_order")
        with col_o2:
            hide_answer = st.checkbox("🙈 先隱藏答案（自己想完再點「顯示答案」）", key="flash_hide")

        df_filtered_flash = df_vocab[scope_mask(df_vocab, sel_sem_flash, sel_unit_flash)]

        if df_filtered_flash.empty:
            st.info("📭 這個範圍沒有單字。")
        else:
            sig = f"{selected_level}|{sel_sem_flash}|{sel_unit_flash}|{order_mode}|{len(df_filtered_flash)}"
            if st.session_state.get("flash_sig") != sig:
                st.session_state.flash_sig = sig
                st.session_state.flash_queue = build_flash_queue(df_filtered_flash, order_mode)
                st.session_state.flashcard_index = 0
                st.session_state.flash_revealed = False

            queue = st.session_state.flash_queue
            total_count = len(queue)
            st.session_state.flashcard_index = st.session_state.flashcard_index % total_count
            row = queue[st.session_state.flashcard_index]
            stage = row["_stage"]
            show_answer = (not hide_answer) or st.session_state.get("flash_revealed", False)
            mastered = sum(1 for r in queue if r["_stage"] >= 4)

            def flash_move(step):
                st.session_state.flashcard_index = (st.session_state.flashcard_index + step) % total_count
                st.session_state.flash_revealed = False

            def flash_mark(new_stage):
                queue_srs_stage(row, new_stage)       # 瞬間完成，不用等雲端
                if len(st.session_state.get("srs_pending", {})) >= SRS_FLUSH_EVERY:
                    with st.spinner("同步熟練度到雲端…"):
                        if not flush_srs():
                            st.session_state["_warn"] = "⚠️ 熟練度同步失敗（網路或 Google 限速），會自動重試，請先不要關閉頁面。"
                flash_move(1)

            st.caption(f"已熟練（⭐ 4 以上）：{mastered} / {total_count}")
            with st.container(border=True):
                st.markdown(
                    f"<div style='text-align:right; color:gray; font-size:14px;'>第 {st.session_state.flashcard_index + 1} / {total_count} 張　熟練度 {'⭐' * stage}{'☆' * (5 - stage)}</div>",
                    unsafe_allow_html=True
                )
                pos_disp = str(row.get('part_of_speech', '')).strip().rstrip('.')
                pos_html = (f" <span style='font-size: 28px; color: gray; font-weight: 400;'>({esc(pos_disp)})</span>"
                            if pos_disp else "")
                st.markdown(
                    f"<h1 style='text-align: center; font-size: 54px; margin-bottom: 5px;'>{esc(row['word'])}{pos_html}</h1>",
                    unsafe_allow_html=True
                )

                components.html(speech_html(row['word'], justify="center"), height=50)

                st.markdown("---")
                if show_answer:
                    st.markdown(f"<h4>中文釋義：{esc(row['definition'])}</h4>", unsafe_allow_html=True)
                    if row.get('advanced_sentence'):
                        st.markdown(f"<p style='font-size: 19px;'>📖 英文釋義：{esc(row.get('advanced_sentence'))}</p>", unsafe_allow_html=True)
                    if row.get('basic_sentence'):
                        st.markdown(f"<p style='font-style: italic; font-size: 19px;'>💬 例句：{esc(row.get('basic_sentence'))}</p>", unsafe_allow_html=True)
                    if row.get('collocations'):
                        st.markdown(f"<p style='font-size: 17px;'>🔗 搭配詞：{esc(row.get('collocations'))}</p>", unsafe_allow_html=True)
                else:
                    if st.button("👀 顯示答案", use_container_width=True):
                        st.session_state.flash_revealed = True
                        st.rerun()

            b1, b2, b3, b4 = st.columns(4)
            if b1.button("⬅️ 上一個", use_container_width=True):
                flash_move(-1)
                st.rerun()
            if b2.button("❌ 不記得", use_container_width=True):
                flash_mark(0)
                st.rerun()
            if b3.button("✅ 記得", use_container_width=True):
                flash_mark(min(stage + 1, 5))
                st.rerun()
            if b4.button("➡️ 下一個", use_container_width=True):
                flash_move(1)
                st.rerun()
            st.caption("「不記得」熟練度歸零；「記得」+1（最高 5）。出題順序選「不熟的優先」時，熟練度低的會先出現。")
            pend_n = len(st.session_state.get("srs_pending", {}))
            if pend_n:
                sy1, sy2 = st.columns([3, 1])
                sy1.caption(f"☁️ 有 {pend_n} 筆熟練度還沒同步到雲端（累積 {SRS_FLUSH_EVERY} 筆或離開此頁時會自動同步）")
                if sy2.button("💾 立即同步", use_container_width=True):
                    with st.spinner("同步中…"):
                        if flush_srs():
                            st.session_state["_flash"] = "☁️ 熟練度已同步到雲端"
                        else:
                            st.session_state["_warn"] = "⚠️ 同步失敗，請稍後再試。"
                    st.rerun()

# =====================================================================
# 🎮 我是拼字王
# =====================================================================
elif main_menu == "🎮 我是拼字王":
    if df_vocab.empty:
        st.warning("📭 目前沒有足夠的單字來進行遊戲！")
    else:
        game_mode = st.radio("選擇遊戲模式：🎮", ["標準模式 (中文提示 + 發音)", "進階挑戰模式 (聽英文解釋拼單字)"], horizontal=True)
        is_advanced = "進階" in game_mode
        st.markdown("---")
        semesters, sem_to_units = get_hierarchical_units(df_vocab)
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            sel_sem_game = st.selectbox("選擇學期/篇章範圍：", [ALL_SEM] + semesters,
                                        key=f"game_sem_select_{selected_level}")
        with col_g2:
            if sel_sem_game == ALL_SEM:
                sel_unit_game = ALL_UNIT
                st.selectbox("選擇單元/課次範圍：", [ALL_UNIT], disabled=True,
                             key=f"game_unit_disabled_{selected_level}")
            else:
                sel_unit_game = st.selectbox("選擇單元/課次範圍：",
                                             [ALL_UNIT] + sem_to_units.get(sel_sem_game, []),
                                             key=f"game_unit_select_{selected_level}")

        df_filtered_game = df_vocab[scope_mask(df_vocab, sel_sem_game, sel_unit_game)]
        if is_advanced:
            # 進階模式要唸英文釋義，沒有英文釋義的單字不出題
            df_filtered_game = df_filtered_game[df_filtered_game['advanced_sentence'].str.strip() != '']
        df_game_queue_source = df_filtered_game.drop_duplicates(subset=['word'])

        if df_game_queue_source.empty:
            if is_advanced:
                st.info("📭 這個範圍內的單字都還沒有「英文釋義」，進階模式沒有題目可出。請改用標準模式，或先補上英文釋義。")
            else:
                st.info("📭 這個範圍沒有單字。")
        else:
            def build_queue():
                """出題清單：同一個單字有多個詞性時，把各詞性的中文釋義合併顯示。"""
                items = df_game_queue_source.sample(frac=1).to_dict('records')
                for it in items:
                    same = df_filtered_game[df_filtered_game['word'] == it['word']]
                    defs = [f"{p} {d}".strip() for p, d in zip(same['part_of_speech'], same['definition']) if d.strip()]
                    it['definition'] = "；".join(defs)
                return items

            # 級別、模式、範圍任何一個變動，就重新出題（避免用到上一個級別的舊題目）
            game_key = f"{selected_level}|{game_mode}|{sel_sem_game}|{sel_unit_game}"
            if st.session_state.get("game_key") != game_key:
                st.session_state.game_key = game_key
                st.session_state.game_queue = build_queue()
                st.session_state.game_index = 0
                st.session_state.wrong_answers = []
                st.session_state.is_finished = False
                st.session_state.last_feedback = None

            if st.session_state.game_index >= len(st.session_state.game_queue):
                st.session_state.is_finished = True

            if st.session_state.get("is_finished", False):
                st.balloons()
                st.markdown("## 🎉 測驗圓滿結束！")
                wrong = st.session_state.get("wrong_answers", [])
                total_q = len(st.session_state.game_queue)
                st.markdown(f"答對 **{total_q - len(wrong)}** / {total_q} 題")
                if wrong:
                    st.markdown("**答錯的單字：**")
                    for w in wrong:
                        st.markdown(f"- `{w['word']}`　{w.get('definition', '')}")
                    if st.button("🔁 只重考答錯的題目", type="primary", use_container_width=True):
                        retry = list(wrong)
                        random.shuffle(retry)
                        st.session_state.game_queue = retry
                        st.session_state.game_index = 0
                        st.session_state.wrong_answers = []
                        st.session_state.is_finished = False
                        st.session_state.last_feedback = None
                        st.rerun()
                if st.button("🔄 重新挑戰本範圍", use_container_width=True):
                    st.session_state.game_key = None
                    st.rerun()
            else:
                current_item = st.session_state.game_queue[st.session_state.game_index]
                target_word = str(current_item['word']).strip()
                target_def = str(current_item['definition']).strip() or "(尚無中文釋義)"
                target_adv_def = str(current_item.get('advanced_sentence', '')).strip()
                hint_masked = "".join([" _ " if c.isalpha() else "   " for c in target_word])

                total_q_count = len(st.session_state.game_queue)
                current_q_num = st.session_state.game_index + 1
                remaining_count = total_q_count - current_q_num + 1

                with st.container(border=True):
                    q_col1, q_col2 = st.columns([5, 1])
                    with q_col2:
                        st.markdown(
                            f"<div style='text-align: right; color: gray; font-size: 15px; font-weight: bold;'>剩餘題數：{remaining_count}</div>",
                            unsafe_allow_html=True
                        )

                    if not is_advanced:
                        r_col1, r_col2 = st.columns([2, 3])
                        with r_col1:
                            st.markdown(f"<h3 style='margin: 0; padding-top: 5px;'>中文：{esc(target_def)}</h3>", unsafe_allow_html=True)
                        with r_col2:
                            components.html(speech_html(target_word), height=45)
                    else:
                        # 把釋義裡的答案遮起來（顯示成 ____，唸出來變成 blank），避免直接洩漏答案
                        st.markdown("<h3 style='margin-bottom: 5px;'>🔊 英文解釋聽力提示：</h3>", unsafe_allow_html=True)
                        st.markdown(
                            f"<p style='font-size: 17px; font-weight: 500; margin-bottom: 10px;'>{esc(mask_word(target_adv_def, target_word))}</p>",
                            unsafe_allow_html=True
                        )
                        components.html(speech_html(mask_word(target_adv_def, target_word, repl="blank")), height=45)

                    st.markdown(
                        f"<div style='margin-top: 15px; margin-bottom: 15px;'><b>單字提示：</b> <code>{esc(hint_masked)}</code></div>",
                        unsafe_allow_html=True
                    )

                    if st.session_state.get("last_feedback"):
                        fb = st.session_state.last_feedback
                        if fb["type"] == "success":
                            st.success(fb["msg"])
                        else:
                            st.error(fb["msg"])
                        if st.button("➡️ 點擊進入下一題", type="primary", use_container_width=True):
                            st.session_state.last_feedback = None
                            st.session_state.game_index += 1
                            st.rerun()
                    else:
                        with st.form(key=f"quiz_form_{st.session_state.game_index}"):
                            f_col1, f_col2 = st.columns([4, 1], gap="small")
                            with f_col1:
                                user_ans = st.text_input(
                                    "輸入答案", placeholder="在此輸入拼寫答案...",
                                    key=f"ans_input_{st.session_state.game_index}",
                                    label_visibility="collapsed"
                                )
                            with f_col2:
                                submitted = st.form_submit_button("🚀 送出", type="primary", use_container_width=True)

                            if submitted:
                                if norm_answer(user_ans) == norm_answer(target_word):
                                    st.session_state.last_feedback = {"type": "success", "msg": f"🎉 答對了！就是 `{target_word}`"}
                                else:
                                    st.session_state.wrong_answers.append(current_item)
                                    st.session_state.last_feedback = {"type": "error", "msg": f"❌ 答錯囉！正確答案是：`{target_word}`"}
                                st.rerun()
