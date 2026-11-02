import hmac
import html
import random
import re

import gspread
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import inspect
from google.oauth2.service_account import Credentials


def _wide(fn):
    """新版 Streamlit 改用 width="stretch"，舊版用 use_container_width=True；自動挑對的。"""
    try:
        if "width" in inspect.signature(fn).parameters:
            return {"width": "stretch"}
    except (TypeError, ValueError):
        pass
    return {"use_container_width": True}


W_BTN = _wide(st.button)
W_FORM = _wide(st.form_submit_button)
W_EDIT = _wide(st.data_editor)

st.set_page_config(
    page_title="我愛背單字",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
    <style>
    :root { --acc: var(--primary-color, #4a76a8); --line: rgba(128,128,128,.28); --r: 10px; }
    .block-container { padding-top: 2.2rem; max-width: 1100px; }

    /* 只保留：卡片／數據卡有淡灰底與細邊框；輸入框與下拉選單用 Streamlit 原生淡灰底，不加框 */
    [data-testid="stVerticalBlockBorderWrapper"], [data-testid="stMetric"] {
        border-radius: 12px !important; border: 1px solid var(--line) !important;
        background: rgba(128,128,128,.06) !important;
    }
    [data-testid="stVerticalBlockBorderWrapper"] { padding: 18px !important; }
    [data-testid="stMetric"] { padding: 12px 18px; }
    [data-testid="stExpander"], div[data-testid="stForm"] { border-radius: 12px !important; border-color: var(--line) !important; }

    .stButton button, .stFormSubmitButton button, .stDownloadButton button,
    .stTextInput input, .stTextArea textarea, [data-baseweb="select"] > div { border-radius: var(--r) !important; }
    .stButton button:not([kind="primary"]), .stDownloadButton button { border: 1px solid var(--line); }
    .stButton button:hover, .stFormSubmitButton button:hover { border-color: var(--acc); color: var(--acc); }
    hr { margin: 1.2rem 0 !important; }


    div[data-testid="stForm"] [data-testid="stHorizontalBlock"] { align-items: flex-end !important; }
    .stDataFrame [data-testid="stTable"] td {
        white-space: normal !important; word-wrap: break-word !important; height: auto !important;
        padding: 12px 0 !important; font-size: clamp(13px,1.6vw,15px) !important;
    }

    /* 發音按鈕 */
    .vsp-wrap { display: flex; gap: 8px; align-items: center; margin: 4px 0; flex-wrap: wrap; }
    .vsp-btn {
        background: transparent; color: inherit; border: 1px solid var(--line); border-radius: var(--r);
        padding: 6px 14px; font-size: clamp(13px,3.4vw,15px); cursor: pointer;
    }
    .vsp-btn:hover { border-color: var(--acc); color: var(--acc); }

    /* 背誦卡片 */
    .fc-def { font-size: clamp(20px,5vw,28px); font-weight: 600; text-align: center; margin: 4px 0 14px; }
    .fc-line { font-size: clamp(15px,2.6vw,18px); margin: 6px 0; line-height: 1.6; }
    .fc-meta { text-align: right; font-size: 13px; opacity: .6; margin-bottom: 6px; }
    .fc-pos { font-size: clamp(16px,4.5vw,24px); font-weight: 400; opacity: .6; }
    .fc-word { text-align: center; font-size: clamp(30px,9vw,48px); font-weight: 700; line-height: 1.2; margin: 4px 0 6px; word-break: break-word; }
    .fc-line b { opacity: .6; font-weight: 500; margin-right: .5em; }

    .fc-hint { text-align: center; font-family: ui-monospace,Consolas,monospace; font-size: clamp(20px,5vw,28px); letter-spacing: .15em; white-space: pre-wrap; word-break: break-all; margin: 12px 0; opacity: .85; }

    /* 隱藏 Streamlit Cloud 右下角的徽章與頭像（平台加的，不保證每個版本都藏得掉） */
    [class*="viewerBadge"], [class*="_profileContainer_"], [class*="_profilePreview"],
    [data-testid="appCreatorAvatar"], [data-testid="manage-app-button"], .stDeployButton { display: none !important; }

    /* 標題與數據卡：整體縮小、更精簡 */
    h1, h2, h3, [data-testid="stMetricValue"], [data-testid="stMetricLabel"] { line-height: 1.5 !important; overflow: visible !important; }
    [data-testid="stMetricValue"] > div, [data-testid="stMetricLabel"] > div { overflow: visible !important; text-overflow: clip !important; }
    .stTextInput input, .stTextArea textarea, [data-baseweb="select"] > div { line-height: 1.5 !important; }
    h1 { font-size: clamp(26px,6.5vw,36px) !important; padding: .2rem 0 .4rem !important; }
    h3 { font-size: clamp(18px,4.2vw,22px) !important; }
    [data-testid="stMetricValue"] { font-size: clamp(20px,4.6vw,28px) !important; }
    [data-testid="stMetricLabel"] { font-size: 13px !important; opacity: .75; }

    /* 手機 */
    @media (max-width: 640px) {
        .block-container { padding: 2.5rem .8rem 1rem !important; }
        [data-testid="stVerticalBlock"] { gap: .7rem !important; }
        [data-testid="stMetric"] { padding: 8px 14px !important; }
        [data-testid="stVerticalBlockBorderWrapper"] { padding: 12px !important; }
        [data-testid="stHorizontalBlock"]:has(> div:nth-child(4)):not(:has(> div:nth-child(5))) { flex-wrap: nowrap !important; gap: .3rem !important; }
        [data-testid="stHorizontalBlock"]:has(> div:nth-child(4)):not(:has(> div:nth-child(5))) > div { min-width: 0 !important; }
        [data-testid="stHorizontalBlock"]:has(> div:nth-child(4)):not(:has(> div:nth-child(5))) button { padding: 0 4px !important; font-size: 13px !important; }
    }
    @media (pointer: coarse) {
        .stButton button, .stFormSubmitButton button { min-height: 46px; }
        [data-baseweb="select"] > div, .stTextInput input { min-height: 44px; }
    }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# 輕量發音：按鈕只是一小段 HTML，不再每換一張卡／每答一題就新建一個 iframe。
# 只放一個「內容固定不變」的隱形 iframe，負責在瀏覽器裡安裝一次「點按鈕 → 唸出來」。
# ---------------------------------------------------------------------
SPEECH_INIT_HTML = """
<script>
(function () {
  var p = window.parent;
  if (!p || p.__vspInit) return;
  try {
    p.__vspInit = true;
    var s = p.document.createElement('script');
    s.textContent = '(' + function () {
      document.addEventListener('click', function (e) {
        var b = e.target && e.target.closest ? e.target.closest('.vsp-btn') : null;
        if (!b) return;
        var t = b.getAttribute('data-t');
        if (!t) return;
        speechSynthesis.cancel();
        var u = new SpeechSynthesisUtterance(t);
        u.lang = b.getAttribute('data-l') || 'en-US';
        u.rate = 0.9;
        speechSynthesis.speak(u);
      }, true);
    }.toString() + ')();';
    p.document.head.appendChild(s);
  } catch (err) {
    p.__vspInit = false;
  }
})();
</script>
"""


def speech_init():
    components.html(SPEECH_INIT_HTML, height=0)


def speech_buttons(text, justify="center"):
    t = html.escape(str(text), quote=True)
    st.markdown(
        f'<div class="vsp-wrap" style="justify-content:{justify}">'
        f'<button type="button" class="vsp-btn" data-t="{t}" data-l="en-US">US 美式</button>'
        f'<button type="button" class="vsp-btn" data-t="{t}" data-l="en-GB">GB 英式</button>'
        f'<button type="button" class="vsp-btn" data-t="{t}" data-l="en-AU">AU 澳洲</button>'
        f'</div>',
        unsafe_allow_html=True
    )


# ---------------------------------------------------------------------
# 密碼保護（選用）：在 secrets 加一行  app_password = "你的密碼"  就會啟用；
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

st.title("📚 我愛背單字")

MENUS = ["背誦單字", "我是拼字王", "新增單字", "字彙管理"]
LEVELS = ["國中部", "高中部", "TOEIC"]


def top_choice(label, options, key):
    """頁面頂端的橫向選單；舊版 Streamlit 沒有 segmented_control 就退回橫向單選。"""
    if hasattr(st, "segmented_control"):
        v = st.segmented_control(label, options, default=options[0], key=key, label_visibility="collapsed")
        return v if v in options else st.session_state.get(f"_last_{key}", options[0])   # 點到已選的那個不會變成空值
    return st.radio(label, options, horizontal=True, key=key, label_visibility="collapsed")


main_menu = top_choice("功能", MENUS, "menu_sel")
selected_level = top_choice("級別", LEVELS, "level_sel")
st.session_state["_last_menu_sel"], st.session_state["_last_level_sel"] = main_menu, selected_level

if main_menu in ("背誦單字", "我是拼字王"):
    speech_init()

current_sheet_name = selected_level

# 儲存後的提示訊息（因為存完會 rerun，訊息要先存起來，重跑後才顯示）
if st.session_state.get("_flash"):
    st.success(st.session_state.pop("_flash"))
if st.session_state.get("_warn"):
    st.warning(st.session_state.pop("_warn"))

ALL_SEM = "全部單字"
ALL_UNIT = "全部單元"

# 課次：每個級別（國中部／高中部／TOEIC）都是 第一課 ～ 第十五課
CN_NUMS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二", "十三", "十四", "十五"]
LESSONS = [f"第{c}課" for c in CN_NUMS]
LESSON_NO = {name: i + 1 for i, name in enumerate(LESSONS)}

# 欄位順序固定放這裡，存檔時共用
HEADERS = ['id', 'word', 'phonetic', 'part_of_speech', 'definition',
           'advanced_sentence', 'basic_sentence', 'collocations', 'unit_tag', 'srs_stage']

# 可編輯的欄位（預覽表、總表共用）
EDIT_COLS = ['word', 'part_of_speech', 'definition',
             'advanced_sentence', 'basic_sentence', 'collocations']

PAGE_SIZE = 100   # 字彙管理總表每頁筆數（避免一次把上千列塞進瀏覽器）

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


# ---------------------------------------------------------------------
# 讀取資料（只留常用欄位，長文字延後到需要時才讀）
#   常用欄位 LIGHT_COLS 一直放在記憶體；例句、搭配詞、英文釋義這類較長的文字不放進共用快取，
#   只有「真的要顯示」的那幾筆（總表當頁、背誦翻開答案、進階模式出題）才向雲端讀，用完就丟。
#   讀的時候用「列號」：載入時順便記下每一筆在試算表的第幾列（_row），之後只讀那幾列，
#   不再整欄下載。讀回來時會核對編號與單字，對不上（資料被改動過）就當作沒讀到，不會顯示錯的內容。
#   要寫入雲端之前，一律另外讀一份完整的表（load_vocab_full），不經過快取，所以不會漏掉長文字。
# ---------------------------------------------------------------------
LIGHT_COLS = ['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'unit_tag', 'srs_stage']
LONG_COLS = ['advanced_sentence', 'basic_sentence', 'collocations']
WORD_LETTER = chr(65 + HEADERS.index('word'))
LONG_IDX = [HEADERS.index(c) for c in LONG_COLS]                      # 長文字欄在 A~H 範圍裡的位置
ROW_FETCH_MAX_RANGES = 25     # 一次最多讀幾段列範圍；超過就改整欄讀取（避免請求網址太長）


def _rows_to_df(all_values, columns):
    """只把 columns 指定的欄位轉成 DataFrame（依標題名稱找欄位，其他欄位不建立，省記憶體）。"""
    if len(all_values) > 1:
        pos = {}
        for i, h in enumerate(all_values[0]):
            pos.setdefault(str(h).strip().lower(), i)        # 欄名重複時只取第一個
        body = all_values[1:]
        data = {c: ([(r[pos[c]] if pos[c] < len(r) else "") for r in body] if c in pos else [""] * len(body))
                for c in columns}
        return pd.DataFrame(data, columns=list(columns))
    return pd.DataFrame(columns=list(columns))


def _finish_df(df_temp):
    # 注意：不再把 "none"/"nan" 當成空值。它們是真正的英文單字，以前會被當成空白而消失，
    # 而且之後一刪除就會被整張覆寫洗掉。從試算表讀出來的本來就都是字串，不需要轉型。
    df_temp = df_temp[df_temp['word'].str.strip() != ''].reset_index(drop=True)

    def normalize_tag(tag):
        t = str(tag).strip()
        if '>' in t:
            parts = t.split('>', 1)
            return f"{parts[0].strip()} > {parts[1].strip()}"
        return t

    # 只對「不重複的標籤」整理，再對應回每一列（比逐列處理快很多）
    norm_map = {u: normalize_tag(u) for u in df_temp['unit_tag'].unique()}
    df_temp['unit_tag'] = df_temp['unit_tag'].map(norm_map)
    sem_map, unit_map = {}, {}
    for u in set(norm_map.values()):
        if '>' in u:
            a, b = u.split('>', 1)
            sem_map[u], unit_map[u] = a.strip(), b.strip()
        else:
            sem_map[u], unit_map[u] = "", ""
    # 用 category 型態存：省記憶體，篩選時只是整數比對，不必每次對全部列做字串比對
    df_temp['_sem'] = df_temp['unit_tag'].map(sem_map).astype('category')
    df_temp['_unit'] = df_temp['unit_tag'].map(unit_map).astype('category')
    df_temp.attrs["unit_tags"] = tuple(sem_map.keys())
    df_temp.attrs["unique_words"] = int(df_temp['word'].str.strip().str.lower().nunique()) if not df_temp.empty else 0
    return df_temp


# 用 cache_resource：所有操作共用同一份資料、不會每次點擊都整份複製（比 cache_data 快、省記憶體）。
# 因此「不可以直接修改 df_vocab」；要寫入前一律用 load_vocab_full 另外讀一份。
@st.cache_resource(ttl=300, show_spinner=False)
def load_vocab_dataframe(_worksheet, cache_key):
    # 讀取失敗時讓錯誤直接往上丟（由下方 try/except 顯示並停止），
    # 不可以變成「空表」，否則之後存檔會把雲端資料蓋掉。
    # 只向雲端要「常用欄位」（A~E、F 只看有沒有、I~J），例句／搭配詞（G、H）連下載都省掉。
    res = _worksheet.batch_get(["A1:J1", "A2:E", "F2:F", "I2:J"])
    hdr = [str(h).strip().lower() for h in (res[0][0] if res[0] else [])]
    if hdr and hdr[:len(HEADERS)] != HEADERS:       # 全新的空白工作表（沒有標題列）沒關係，第一次存檔會自動寫入
        raise ValueError("試算表第 1 列（標題列）必須依序是：" + ", ".join(HEADERS))
    n = max(len(res[1]), len(res[2]), len(res[3]))
    if n == 0:              # 空白工作表或只有標題列
        return _finish_df(pd.DataFrame(columns=LIGHT_COLS + ['_has_adv', '_row'], dtype=object))

    def col(rows, i):
        return [(r[i] if i < len(r) else "") for r in rows] + [""] * (n - len(rows))
    data = {c: col(res[1], i) for i, c in enumerate(HEADERS[:5])}
    data['unit_tag'], data['srs_stage'] = col(res[3], 0), col(res[3], 1)
    df_temp = pd.DataFrame(data, columns=LIGHT_COLS)
    df_temp['_has_adv'] = pd.Series(col(res[2], 0), dtype=object).str.strip().ne('').to_numpy()
    df_temp['_row'] = range(2, n + 2)       # 這幾個範圍都從第 2 列開始，所以第 i 筆就是第 i+2 列
    return _finish_df(df_temp)


def load_vocab_full(_worksheet):
    """完整的表（含例句、搭配詞）：寫入雲端前用，每次都重新從雲端讀、不放進快取。"""
    return _finish_df(_rows_to_df(_worksheet.get_all_values(), HEADERS))


def drop_caches():
    """資料有變動後呼叫：清掉常用欄位的快取，以及暫存的例句／搭配詞。"""
    load_vocab_dataframe.clear()
    st.session_state.pop("_long_cache", None)


def _row_groups(rows, gap=3):
    """把列號合併成幾段連續（或幾乎連續）的範圍，例如 [5,6,7,9,40] → [[5,9],[40,40]]。"""
    groups = []
    for r in sorted(set(int(x) for x in rows)):
        if groups and r - groups[-1][1] <= gap + 1:
            groups[-1][1] = r
        else:
            groups.append([r, r])
    return groups


def fetch_long_text(ws, wanted):
    """wanted = {編號字串: (單字, 試算表列號)}。只向雲端讀這幾列的 英文釋義／例句／搭配詞。
    回傳 (結果 {編號: {欄位: 文字}}, 錯誤訊息)。編號或單字對不上（資料已被改動）的不會出現在結果裡。"""
    out = {}
    try:
        groups = _row_groups([r for _, r in wanted.values()])
        for k in range(0, len(groups), ROW_FETCH_MAX_RANGES):     # 範圍太多就分批，避免請求網址太長
            for block in ws.batch_get([f"A{a}:H{b}" for a, b in groups[k:k + ROW_FETCH_MAX_RANGES]]):
                for cells in block:
                    if len(cells) < 2:
                        continue
                    rid = str(cells[0]).strip()
                    if (rid in wanted and rid not in out
                            and str(cells[1]).strip().lower() == wanted[rid][0].strip().lower()):
                        out[rid] = {c: (cells[i] if i < len(cells) else "")
                                    for c, i in zip(LONG_COLS, LONG_IDX)}
        return out, ""
    except Exception as e:
        return {}, str(e)


def get_page_long_text(orig):
    """總表當頁的長文字。暫存在 session，只留「目前這一頁」（換頁就換掉，不會越累積越多）。"""
    wanted = {str(i): (w, int(r)) for i, w, r in zip(orig['id'], orig['word'], orig['_row'])}
    key = (current_sheet_name, tuple(sorted(wanted)))
    cache = st.session_state.get("_long_cache")
    if cache and cache["key"] == key:
        return cache["data"], ""
    data, err = fetch_long_text(active_worksheet, wanted)
    if not err and len(data) < len(wanted):
        err = "有幾筆資料在雲端已被改動或刪除，請重新整理網頁後再試。"
    if not err:
        st.session_state["_long_cache"] = {"key": key, "data": data}
    return data, err


def ensure_flash_long(queue, idx, ahead=8):
    """背誦：只讀「目前這張＋後面 7 張」的例句／搭配詞（一次 API 呼叫），其他等翻到再讀。"""
    todo = [d for d in queue[idx: idx + ahead] if not d.get("_long")]
    if not todo:
        return
    data, err = fetch_long_text(active_worksheet, {str(d["id"]): (d["word"], int(d["_row"])) for d in todo})
    if err:
        st.warning(f"例句／搭配詞暫時讀不到（{err}），先只顯示中文釋義。")
    for d in todo:
        d.update(data.get(str(d["id"]), {}))
        d["_long"] = True           # 失敗也先標記，避免每次點擊都重試、被 Google 限速


try:
    with st.spinner("⏳ 正在從雲端載入單字資料庫..."):
        gs_client = init_gsheets_client()
        active_worksheet = get_active_worksheet(gs_client, st.secrets["sheet_url"], current_sheet_name)
        df_vocab = load_vocab_dataframe(active_worksheet, current_sheet_name)
except Exception as e:
    st.error(f"連線或讀取 Google 試算表發生錯誤：{e}")
    st.stop()

unique_words = df_vocab.attrs.get("unique_words", 0)
if main_menu in ("新增單字", "字彙管理"):
    st.metric(label=f"{selected_level}　雲端單字量", value=f"{unique_words} 個單字／{len(df_vocab)} 筆",
              help="「筆」= 資料列數；同一個單字有多個詞性、或出現在不同單元時，會算多筆。")
else:
    st.caption(f"{selected_level}　共 {unique_words} 個單字／{len(df_vocab)} 筆")

# ---------------------------------------------------------------------
# 解析貼上的單字清單：格式固定為  單字 | 詞性 | 中文釋義 | 英文釋義 | 例句 | 搭配詞
# （沒填的欄位留空白；只貼單字也可以）
# ---------------------------------------------------------------------
def parse_line(line):
    """一行 → 一筆資料；空行回傳 None。"""
    parts = [p.strip() for p in re.sub(r'^\d+[\.\)、\s]+', '', line).strip().split('|')] + [""] * 5
    word, pos, definition, eng, sent, colloc = parts[:6]
    return {"word": word, "phonetic": "", "part_of_speech": pos or ("phr." if " " in word else "n."),
            "definition": definition, "advanced_sentence": eng, "basic_sentence": sent,
            "collocations": colloc} if word else None


def ai_prompt_text(level):
    """給你複製到任何 AI 的固定提示詞；輸出格式剛好是下方批次貼上可以直接吃的格式。"""
    return f"""請幫我整理英文單字，對象是台灣的「{level}」學生。我會在最後貼上單字清單，請每個單字輸出一行，格式固定為（用 | 分隔；不要加編號、不要加表格、不要加程式碼區塊、不要加任何說明文字）：
單字 | 詞性 | 中文釋義 | 英文釋義 | 例句 | 搭配詞

格式範例：
torture | n. | 酷刑；折磨 | The act of causing great pain to someone as punishment, or something very unpleasant. | Waiting for the exam results was torture. | under torture / torture chamber
torture | v. | 折磨；使痛苦 | To cause someone great pain or suffering. | The noise tortured me all night. | be tortured by / torture oneself

規則：
1. 中文用繁體中文（台灣用語），釋義簡短。
2. 詞性用縮寫：n. v. adj. adv. prep. conj. pron. phr.；一個單字有多個常見詞性時，每個詞性各寫一行，而且每一行的中文釋義、英文釋義、例句、搭配詞都要對應「該詞性」的意思，不可以複製貼上同一份。名詞寫名詞的意思（例如「酷刑」），動詞寫動詞的意思（例如「折磨」）。
3. 英文釋義用簡單英文寫一句話，不要在釋義裡直接使用該單字。
4. 例句要自然、日常、母語者真的會說；字義必須符合該行的中文與詞性；難度適合「{level}」學生；不要荒謬、誇張或硬湊的句子。
5. 搭配詞給 2～3 個母語者真實常用的，用 / 分隔；沒把握就少給，不要編造。
6. 不確定的欄位請留空，但必須保留 | 分隔符，確保每行都剛好有 6 個欄位。
7. 各欄位內容中不要出現 | 符號。

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
        if len(rows) + 1 > _worksheet.row_count:      # 多留一列，清尾巴的範圍才不會超出表格
            _worksheet.resize(rows=len(rows) + 200)
        _worksheet.update(values=rows, range_name="A1", value_input_option="RAW")
        _worksheet.batch_clear([f"A{len(rows) + 1}:J"])
        st.session_state["srs_local"] = {}
        drop_caches()
        return True, "成功"
    except Exception as e:
        return False, str(e)


def delete_rows(match):
    """match(df) 回傳要刪除的列（布林）。重新讀最新資料、刪除、編號重排後整張寫回。"""
    drop_caches()
    df = load_vocab_full(active_worksheet)
    df = df[~match(df)].copy()
    if not df.empty:
        df['id'] = range(1, len(df) + 1)
    return save_all_vocab_to_sheet(active_worksheet, df)


def get_next_id(df):
    """目前最大編號 + 1（刪過資料後編號才不會重複）。"""
    ids = pd.to_numeric(df['id'], errors='coerce').dropna()
    return int(ids.max()) + 1 if not ids.empty else 1


def persist_changes(_worksheet, df_after, new_rows, updated, was_empty):
    """只有新增 → 只在表格最後面補幾列（快）；有修改舊資料、或原本是空表 → 整張覆寫。"""
    if updated or was_empty:
        return save_all_vocab_to_sheet(_worksheet, df_after)
    if not new_rows:
        return True, "沒有變更"
    try:
        values = [[str(r.get(h, '')) for h in HEADERS] for r in new_rows]
        try:
            _worksheet.append_rows(values, value_input_option="RAW", insert_data_option="INSERT_ROWS", table_range="A1")
        except TypeError:      # 舊版 gspread 沒有這個參數
            _worksheet.append_rows(values, value_input_option="RAW", table_range="A1")
        drop_caches()
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
        if rec["word"]:
            rows.append(rec)
    return rows


# ---------------------------------------------------------------------
# 學期 / 單元
# ---------------------------------------------------------------------
def parse_lesson_number(unit_str):
    """課次排序用：第一課=1 … 第十五課=15；其他舊式寫法（上／中／下）照舊；認不得的排最後。"""
    s = str(unit_str).strip()
    for name in sorted(LESSON_NO, key=len, reverse=True):      # 先比長的，避免「第十一課」被當成別的課
        if name in s:
            return LESSON_NO[name]
    for k, v in (('上', 1), ('中', 2), ('下', 3)):
        if k in s:
            return v
    return 99


def sem_sort_key(sem):
    return (SEM_ORDER.index(sem) if sem in SEM_ORDER else 999, sem)


def get_hierarchical_units(df):
    semesters = []
    semester_to_units = {}
    if 'unit_tag' in df.columns:
        for ut in (df.attrs.get("unit_tags") or df['unit_tag'].dropna().unique()):
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
    """依「學期/篇章、單元」回傳要包含哪些列（用載入時預先算好的 _sem/_unit 欄位）。"""
    if sem == ALL_SEM:
        return pd.Series(True, index=df.index)
    m = df['_sem'] == sem
    return m if unit == ALL_UNIT else (m & (df['_unit'] == unit))


def scoped(df, sem, unit):
    """全部單字時直接用原表（不複製）；其他才篩選。"""
    return df if sem == ALL_SEM else df[scope_mask(df, sem, unit)]


def _count_maps(df):
    """各學期、各單元的筆數（用來顯示在下拉選單，例如「第一課 (66)」）。"""
    sem_c = {str(k): int(v) for k, v in df['_sem'].value_counts().items()}
    unit_c = {(str(a), str(b)): int(n)
              for (a, b), n in df.groupby(['_sem', '_unit'], observed=True).size().items()}
    return sem_c, unit_c


def sem_label_fn(df):
    """學期/篇章下拉選單的顯示文字：名稱 (筆數)。選項的實際值不變，只改顯示。"""
    sem_c, _ = _count_maps(df)
    return lambda v: f"{v} ({len(df)})" if v == ALL_SEM else f"{v} ({sem_c.get(v, 0)})"


def unit_label_fn(df, sem):
    """單元/課次下拉選單的顯示文字：名稱 (筆數)。sem 是目前選的學期/篇章。"""
    _, unit_c = _count_maps(df)
    total = len(df) if sem == ALL_SEM else sum(n for (a, _b), n in unit_c.items() if a == sem)
    return lambda v: f"{v} ({total})" if v == ALL_UNIT else f"{v} ({unit_c.get((sem, v), 0)})"



# ---------------------------------------------------------------------
# 發音：瀏覽器內建語音，不用連網
# ---------------------------------------------------------------------
def scope_picker(df, prefix, sem_label, unit_label):
    """「學期/篇章」＋「單元/課次」兩個下拉選單（顯示筆數）。回傳 (學期, 單元)；選全部時單元為 ALL_UNIT。"""
    semesters, sem_to_units = get_hierarchical_units(df)
    c1, c2 = st.columns(2, gap="medium")
    sem = c1.selectbox(sem_label, [ALL_SEM] + semesters, key=f"{prefix}_sem_{selected_level}",
                       format_func=sem_label_fn(df))
    unit = c2.selectbox(unit_label, [ALL_UNIT] + sem_to_units.get(sem, []), key=f"{prefix}_unit_{selected_level}",
                        format_func=unit_label_fn(df, sem), disabled=(sem == ALL_SEM))
    return sem, (ALL_UNIT if sem == ALL_SEM else unit)


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


SRS_FLUSH_EVERY = 3   # 累積幾筆熟練度就在背景自動同步一次到雲端（不會跳提示）


def queue_srs_stage(row, new_stage):
    """按「記得／不記得」只先記在本機（瞬間完成），之後再批次寫入雲端。"""
    rid = str(row.get("id", "")).strip()
    word = str(row.get("word", "")).strip().lower()
    st.session_state.setdefault("srs_pending", {})[(current_sheet_name, rid)] = (word, new_stage, row.get("_row"))
    st.session_state.setdefault("srs_local", {})[(current_sheet_name, rid)] = new_stage
    row["_stage"] = new_stage


def flush_srs():
    """把累積的熟練度一次寫進雲端：每個級別 2 次 API 呼叫（讀單字核對、一次批次寫入）。
    寫入前會確認該列的單字沒變，避免寫錯列。成功回傳 True。"""
    pend = st.session_state.get("srs_pending", {})
    by_sheet = {}
    for (sheet, rid), v in pend.items():
        by_sheet.setdefault(sheet, {})[rid] = v          # v = (單字, 熟練度, 列號)
    srs_col = chr(65 + HEADERS.index("srs_stage"))
    all_ok = True
    for sheet, items in by_sheet.items():
        try:
            ws = get_active_worksheet(gs_client, st.secrets["sheet_url"], sheet)
            rids = list(items)
            res = ws.batch_get([f"{WORD_LETTER}{int(items[r][2])}" for r in rids])
            data = [{"range": f"{srs_col}{int(items[r][2])}", "values": [[items[r][1]]]}
                    for r, cell in zip(rids, res)
                    if cell and cell[0] and str(cell[0][0]).strip().lower() == items[r][0]]
            if data:
                ws.batch_update(data, value_input_option="RAW")
            for r in rids:          # 寫成功，或確定對不上（資料已變動）→ 都從待寫清單移除
                pend.pop((sheet, r), None)
        except Exception:
            all_ok = False             # 失敗就留著，下次再試
    return all_ok


def save_row_edits(changes, orig):
    """只更新有修改的那幾列（一次 batch_update），不重寫整張表。
    回傳 (成功與否, 套用幾筆, 略過幾筆, 錯誤訊息)。"""
    try:
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
            data.append({"range": f"D{rn}:H{rn}", "values": [[vals[c] for c in EDIT_COLS[1:]]]})
            applied += 1
        if data:
            active_worksheet.batch_update(data, value_input_option="RAW")
        drop_caches()
        return True, applied, skipped, ""
    except Exception as e:
        return False, 0, 0, str(e)


def _num(v):
    x = pd.to_numeric(v, errors="coerce")
    return 0 if pd.isna(x) else x


FLASH_COLS = ["id", "word", "part_of_speech", "definition", "srs_stage", "_row"]   # 長文字在顯示答案時才讀


def build_flash_queue(df, order_mode):
    local = st.session_state.get("srs_local", {})     # 本機還沒同步到雲端的熟練度優先
    items = df[FLASH_COLS].to_dict("records")
    for d in items:
        d["_stage"] = parse_stage(local.get((current_sheet_name, str(d["id"])), d.pop("srs_stage")))
        d.pop("srs_stage", None)
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
        status = "已存在（會更新）" if key in existing else "新增"
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
    st.markdown(f"**目標：** `{pb['sheet']} ({pb['unit_tag']})`　共 **{len(pb['rows'])}** 筆")
    st.caption("檢查重點：單字和中文有沒有切對位置？詞性對嗎？例句自然嗎？　"
               "點兩下格子可以直接修改；不要的整列，選取最左邊的框後按 Delete 刪除。「狀態」只是初步判斷。")

    wrong_sheet = pb["sheet"] != current_sheet_name
    if wrong_sheet:
        st.warning(f"這批資料是要匯入「{pb['sheet']}」的，目前選的級別是「{current_sheet_name}」。請切回該級別再確認，或按取消。")

    edited = st.data_editor(
        pd.DataFrame(pb["rows"]).astype({c: "string" for c in EDIT_COLS}),
        key=f"batch_preview_{pb['token']}",
        num_rows="dynamic",
        hide_index=True,
        **W_EDIT,
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
    if c1.button("確認寫入雲端", type="primary", **W_BTN, disabled=wrong_sheet):
        rows = clean_rows(edited)
        if not rows:
            st.warning("表格裡沒有可寫入的單字。")
        else:
            with st.spinner("寫入雲端中…"):
                drop_caches()   # 寫入前重讀最新資料，避免蓋掉別處的修改
                df_current = load_vocab_full(active_worksheet)
                was_empty = df_current.empty
                df_current, new_rows, updated, stats = merge_records(df_current, rows, pb["unit_tag"])
                ok, msg = persist_changes(active_worksheet, df_current, new_rows, updated, was_empty)
            if not ok:
                st.error(f"寫入失敗：{msg}")
                st.stop()
            st.session_state["_flash"] = f"匯入完成：{result_text(stats)}"
            st.session_state["clear_paste"] = True
            st.session_state.pop("pending_batch", None)
            st.rerun()
    if c2.button("取消，不寫入", **W_BTN):
        st.session_state["paste_restore"] = pb["raw_text"]   # 把剛貼的內容還給你
        st.session_state.pop("pending_batch", None)
        st.rerun()


# 離開「背誦單字」頁、或切換級別時，把累積的熟練度一次同步到雲端
_pend = st.session_state.get("srs_pending", {})
_in_game = main_menu == "我是拼字王" and not st.session_state.get("is_finished")   # 拼字王作答中先不同步，測驗結束或離開頁面才一次寫入
if _pend and ((main_menu != "背誦單字" and not _in_game) or any(k[0] != current_sheet_name for k in _pend)):
    if not flush_srs():
        st.session_state["_warn"] = "熟練度同步失敗（網路或 Google 限速），資料還留在本機，回到「背誦單字」頁繼續作答時會自動重試。"

# =====================================================================
# 新增單字
# =====================================================================
if main_menu == "新增單字":
    if st.session_state.get("pending_batch"):
        render_batch_preview()
    else:
        _c1, _c2 = st.columns(2)
        with _c1:
            semester = st.selectbox("主題篇章：" if selected_level == "TOEIC" else "學期：",
                                    {"國中部": SEM_ORDER[:6], "高中部": SEM_ORDER[6:12]}.get(selected_level, SEM_ORDER[12:]),
                                    format_func=sem_label_fn(df_vocab))
        with _c2:
            unit = st.selectbox("課次：", LESSONS, format_func=unit_label_fn(df_vocab, semester))
        current_unit_tag = f"{semester} > {unit}"
        st.caption(f"匯入目標：{selected_level}　{current_unit_tag}")

        # 匯入成功後清空貼上框、取消預覽後還原貼上內容（必須在 text_area 建立之前處理）
        if st.session_state.pop("clear_paste", False):
            st.session_state["paste_box"] = ""
        if "paste_restore" in st.session_state:
            st.session_state["paste_box"] = st.session_state.pop("paste_restore")

        with st.expander("複製這段給 AI，再把結果貼到下面"):
            st.caption("點程式碼框右上角的複製鈕 → 貼給任何 AI → 把單字清單貼在最後 → 把 AI 的回答整段貼回下面的框。")
            st.code(ai_prompt_text(selected_level), language=None)

        pasted_text = st.text_area(
            "貼上完整單字清單", key="paste_box", height=160, label_visibility="collapsed",
            placeholder="source | n. | 來源 | A place... | Sentence | Collocation\n只貼單字也可以：resilient"
        )
        valid_lines = [l for l in (pasted_text or "").split("\n") if l.strip()]
        if valid_lines:
            st.info(f"偵測到 {len(valid_lines)} 個項目，按「解析並預覽」檢查後再寫入。")
        if st.button("解析並預覽", **W_BTN):
            records = [r for r in map(parse_line, valid_lines) if r]
            if records:
                start_batch_preview(records, current_unit_tag, pasted_text)
            else:
                st.warning("請先貼上單字清單")

# =====================================================================
# 字彙管理
# =====================================================================
elif main_menu == "字彙管理":
    if df_vocab.empty:
        st.info("目前雲端尚無單字，請到上方「新增單字」新增！")
    else:
        selected_sem, selected_unit = scope_picker(df_vocab, "mng", "1. 選擇學期/篇章：", "2. 選擇單元/課次：")

        filtered_df = scoped(df_vocab, selected_sem, selected_unit)

        col_f1, col_f2 = st.columns([3, 2], gap="medium")
        with col_f2:          # 右邊：搜尋（要先執行，頁碼才知道篩出幾筆）
            search_query = st.text_input("搜尋單字或釋義：")
            if search_query:
                filtered_df = filtered_df[
                    filtered_df['word'].str.contains(search_query, case=False, na=False, regex=False) |
                    filtered_df['definition'].str.contains(search_query, case=False, na=False, regex=False)
                ]
            n_pages = max(1, -(-len(filtered_df) // PAGE_SIZE))
        with col_f1:          # 左邊：頁碼 + 重複單字檢查
            page_no = st.number_input(
                f"頁碼（每頁 {PAGE_SIZE} 筆，目前範圍共 {len(filtered_df)} 筆）",
                min_value=1, max_value=n_pages, value=1, step=1,
                key=f"page_{selected_level}_{selected_sem}_{selected_unit}_{search_query}"
            )
            page_df = filtered_df.iloc[(page_no - 1) * PAGE_SIZE: page_no * PAGE_SIZE]

            # ---- 左邊：重複單字檢查（寬一點，才看得到完整資訊）----
            with st.expander("🔎 檢查重複單字（整個級別）"):
                _d = df_vocab[['id', 'word', 'part_of_speech', 'definition', 'unit_tag']].copy()
                _d['_w'] = _d['word'].str.strip().str.lower()
                _d['_p'] = _d['part_of_speech'].str.strip().str.lower()
                # 真重複：單字＋詞性都一樣（可能在不同單元，也可能同單元貼了兩次）
                _dup_full = _d[_d.duplicated(['_w', '_p'], keep=False)].sort_values(['_w', '_p'])
                # 同一個字有多筆但詞性不同：通常是正常的（例如 n. 和 v.），只列出來參考
                _multi = _d[_d.duplicated('_w', keep=False) & ~_d.index.isin(_dup_full.index)].sort_values('_w')
                _show = ['id', 'word', 'part_of_speech', 'definition', 'unit_tag']
                _cfg = {"id": "編號", "word": "單字", "part_of_speech": "詞性",
                        "definition": "中文釋義", "unit_tag": "所在單元"}
                if _dup_full.empty:
                    st.success("沒有發現「單字＋詞性」都相同的重複資料。")
                else:
                    # 同一組裡，有中文釋義的排前面（預設保留它），其餘依原順序
                    _dup_full = _dup_full.assign(_has_def=_dup_full['definition'].str.strip().ne(''))
                    _dup_full = _dup_full.sort_values(['_w', '_p', '_has_def'], ascending=[True, True, False], kind='stable')
                    st.warning(f"發現 {_dup_full['_w'].nunique()} 個重複的單字，共 {len(_dup_full)} 筆（單字與詞性都相同）。"
                               "勾選最左邊的「刪除」欄，再按下方按鈕就會刪除。")
                    _auto = st.checkbox("自動勾選：每一組只保留第一筆（優先保留有中文釋義的），其餘預設勾選刪除",
                                        value=True, key=f"dup_auto_{selected_level}")
                    _tbl = _dup_full[_show].reset_index(drop=True).astype({c: "string" for c in _show})
                    _flags = _dup_full.duplicated(['_w', '_p'], keep='first').to_numpy() if _auto else [False] * len(_dup_full)
                    _tbl.insert(0, "delete", _flags)
                    _dctr = st.session_state.get("dupdel_ctr", 0)
                    _dedit = st.data_editor(
                        _tbl,
                        key=f"dupdel_{selected_level}_{_auto}_{_dctr}_{hash(tuple(_tbl['id']))}",
                        num_rows="fixed", hide_index=True, disabled=_show, **W_EDIT,
                        column_config={"delete": st.column_config.CheckboxColumn("刪除", width="small"),
                                       **{k: st.column_config.TextColumn(v) for k, v in _cfg.items()}},
                    )
                    _del_ids = {str(i) for i in _dedit.loc[_dedit['delete'], 'id']}
                    _all_gone = (_dedit.assign(_w=_dedit['word'].str.strip().str.lower(),
                                               _p=_dedit['part_of_speech'].str.strip().str.lower())
                                 .groupby(['_w', '_p'])['delete'].all())
                    if _all_gone.any():
                        st.warning("注意：有些單字的重複資料「全部」被勾選了，刪除後這個單字會完全消失。"
                                   "如果要保留，請取消其中一筆的勾選。")
                    if _del_ids and st.button(f"刪除勾選的 {len(_del_ids)} 筆", type="primary", **W_BTN, key="dup_del_btn"):
                        with st.spinner("刪除中…"):
                            ok, msg = delete_rows(lambda d: d['id'].astype(str).isin(_del_ids))
                        if not ok:
                            st.error(f"刪除失敗：{msg}")
                            st.stop()
                        st.session_state["dupdel_ctr"] = _dctr + 1
                        st.session_state["_flash"] = f"已刪除 {len(_del_ids)} 筆重複單字"
                        st.rerun()
                    elif not _del_ids:
                        st.caption("目前沒有勾選任何一筆。")
                if not _multi.empty:
                    # 注意：Streamlit 不允許展開區塊包展開區塊，所以改用勾選框
                    if st.checkbox(f"顯示「同一個字、不同詞性」（{_multi['_w'].nunique()} 個字，通常是正常的）",
                                   key=f"show_multi_{selected_level}"):
                        st.dataframe(_multi[_show], hide_index=True, column_config=_cfg, **_wide(st.dataframe))
        with col_f2:
            # ---- 右邊：刪除整課（只有選到某一課時才會出現）----
            if selected_sem != ALL_SEM and selected_unit != ALL_UNIT:
                target_tag = f"{selected_sem} > {selected_unit}"
                _n_unit = int((df_vocab['unit_tag'] == target_tag).sum())
                with st.expander(f"🗑️ 刪除整課：{target_tag}（{_n_unit} 筆）"):
                    ctr = st.session_state.get("del_ctr", 0)
                    confirm_unit_del = st.checkbox(f"我確認要刪除「{target_tag}」的全部 {_n_unit} 筆單字",
                                                   key=f"confirm_del_unit_{ctr}")
                    if st.button("刪除整課", type="primary", **W_BTN, key="del_unit_btn",
                                 disabled=not confirm_unit_del):
                        ok, msg = delete_rows(lambda d: d['unit_tag'] == target_tag)
                        if not ok:
                            st.error(f"刪除失敗：{msg}")
                            st.stop()
                        st.session_state["del_ctr"] = ctr + 1   # 換一個新的勾選框，確認狀態才會重置
                        st.session_state["_flash"] = f"已成功刪除「{target_tag}」整課單字！"
                        st.rerun()


        st.markdown("---")
        with st.expander("單字總表（點兩下修改，改完按「儲存修改」；勾選最左邊「刪除」欄可直接刪除）", expanded=True):
            orig = page_df[['id', 'word', 'part_of_speech', 'definition', '_row']].reset_index(drop=True)
            _longs, _lerr = get_page_long_text(orig)
            if _lerr:
                st.error(f"讀取例句、搭配詞失敗，為了避免存檔時把它們清空，這一頁暫時不能編輯：{_lerr}")
                st.stop()
            for _c in LONG_COLS:
                orig[_c] = [_longs[str(i)][_c] for i in orig['id']]
            orig = orig[['id'] + EDIT_COLS]
            orig = orig.astype({c: "string" for c in EDIT_COLS})
            orig_view = orig.copy()
            orig_view.insert(0, "delete", False)          # 最左邊多一欄「刪除」勾選框
            edit_key = f"vocab_editor_{selected_level}_{st.session_state.get('edit_ver', 0)}_{hash(tuple(orig['id']))}"
            edited = st.data_editor(
                orig_view,
                key=edit_key,
                num_rows="fixed",
                hide_index=True,
                **W_EDIT,
                disabled=["id"],
                column_config={
                    "delete": st.column_config.CheckboxColumn("刪除", width="small"),
                    "id": st.column_config.TextColumn("編號", width="small"),
                    "word": st.column_config.TextColumn("單字", width="medium"),
                    "part_of_speech": st.column_config.TextColumn("詞性", width="small"),
                    "definition": st.column_config.TextColumn("中文釋義", width="medium"),
                    "advanced_sentence": st.column_config.TextColumn("英文釋義", width="large"),
                    "basic_sentence": st.column_config.TextColumn("真實例句", width="large"),
                    "collocations": st.column_config.TextColumn("搭配詞", width="medium"),
                }
            )
            _row_del_ids = {str(i) for i in edited.loc[edited['delete'].fillna(False).astype(bool), 'id']}
            b_save, b_del = st.columns(2)
            if b_save.button("儲存修改", type="primary", **W_BTN):
                changes = {}
                for i in range(len(orig)):
                    new_vals = {c: ("" if pd.isna(edited.at[i, c]) else str(edited.at[i, c]).strip()) for c in EDIT_COLS}
                    if any(str(orig.at[i, c]) != new_vals[c] for c in EDIT_COLS):
                        changes[str(orig.at[i, 'id'])] = new_vals
                if not changes:
                    st.info("沒有偵測到任何修改。")
                else:
                    with st.spinner("儲存中…"):
                        ok, applied, skipped, msg = save_row_edits(changes, orig)
                    if not ok:
                        st.error(f"儲存失敗：{msg}")
                        st.stop()
                    st.session_state["edit_ver"] = st.session_state.get("edit_ver", 0) + 1
                    note = f"已儲存 {applied} 筆修改"
                    if skipped:
                        note += f"（{skipped} 筆因單字空白或資料已變動而略過）"
                    st.session_state["_flash"] = note
                    st.rerun()
            if _row_del_ids:
                if b_del.button(f"刪除勾選的 {len(_row_del_ids)} 筆", **W_BTN, key="row_del_btn"):
                    with st.spinner("刪除中…"):
                        ok, msg = delete_rows(lambda d: d['id'].astype(str).isin(_row_del_ids))
                    if not ok:
                        st.error(f"刪除失敗：{msg}")
                        st.stop()
                    st.session_state["edit_ver"] = st.session_state.get("edit_ver", 0) + 1
                    st.session_state["_flash"] = f"已刪除 {len(_row_del_ids)} 筆單字"
                    st.rerun()
                st.caption("提醒：刪除會讓還沒按「儲存修改」的內容消失，請先儲存再刪除。刪除後編號會重新從 1 排起。")

        if st.button("產生備份檔（CSV）"):
            try:
                backup = load_vocab_full(active_worksheet)[HEADERS].copy()
            except Exception as e:
                st.error(f"備份失敗：{e}")
                st.stop()
            for (sheet, rid), stg in st.session_state.get("srs_local", {}).items():
                if sheet == current_sheet_name:       # 還沒同步到雲端的熟練度也一起備份
                    backup.loc[backup['id'].astype(str) == rid, 'srs_stage'] = str(stg)
            st.download_button(
                "點此下載",
                data=backup.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"vocab_{selected_level}.csv",
                mime="text/csv",
            )

# =====================================================================
# 背誦單字
# =====================================================================
elif main_menu == "背誦單字":
    if df_vocab.empty:
        st.warning("目前雲端沒有單字！")
    else:
        sel_sem_flash, sel_unit_flash = scope_picker(df_vocab, "flash", "選擇學期/篇章：", "選擇單元/課次：")

        col_o1, col_o2 = st.columns(2)
        with col_o1:
            order_mode = st.radio("出題順序：", ["不熟的優先", "隨機", "依編號順序"], horizontal=True, key="flash_order")
        with col_o2:
            hide_answer = st.checkbox("先隱藏答案（自己想完再點「顯示答案」）", key="flash_hide")

        df_filtered_flash = scoped(df_vocab, sel_sem_flash, sel_unit_flash)

        if df_filtered_flash.empty:
            st.info("這個範圍沒有單字。")
        else:
            sig = f"{selected_level}|{sel_sem_flash}|{sel_unit_flash}|{order_mode}|{len(df_filtered_flash)}|{st.session_state.get('srs_ver', 0)}"
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
            if show_answer and not row.get("_long"):
                with st.spinner("載入例句與搭配詞…"):
                    ensure_flash_long(queue, st.session_state.flashcard_index)
            mastered = sum(1 for r in queue if r["_stage"] >= 4)

            def flash_move(step):
                st.session_state.flashcard_index = (st.session_state.flashcard_index + step) % total_count
                st.session_state.flash_revealed = False

            def flash_mark(new_stage):
                queue_srs_stage(row, new_stage)       # 瞬間完成，不用等雲端
                # 自動同步（靜默）：累積夠多筆、或剛做完最後一張就寫入；失敗的留著，下次自動重試
                if (len(st.session_state.get("srs_pending", {})) >= SRS_FLUSH_EVERY
                        or st.session_state.flashcard_index == total_count - 1):
                    flush_srs()
                flash_move(1)

            st.progress(mastered / total_count, text=f"已熟練（4 級以上）{mastered} / {total_count}")
            with st.container(border=True):
                st.markdown(
                    f"<div class='fc-meta'>第 {st.session_state.flashcard_index + 1} / {total_count} 張　熟練度 {'●' * stage}{'○' * (5 - stage)}</div>",
                    unsafe_allow_html=True
                )
                pos_disp = str(row.get('part_of_speech', '')).strip().rstrip('.')
                pos_html = (f" <span class='fc-pos'>({esc(pos_disp)})</span>"
                            if pos_disp else "")
                st.markdown(
                    f"<div class='fc-word'>{esc(row['word'])}{pos_html}</div>",
                    unsafe_allow_html=True
                )

                speech_buttons(row['word'])

                st.markdown("---")
                if show_answer:
                    st.markdown(f"<div class='fc-def'>{esc(row['definition'])}</div>", unsafe_allow_html=True)
                    if row.get('advanced_sentence'):
                        st.markdown(f"<div class='fc-line'><b>英文釋義</b>{esc(row.get('advanced_sentence'))}</div>", unsafe_allow_html=True)
                    if row.get('basic_sentence'):
                        st.markdown(f"<div class='fc-line'><b>例句</b>{esc(row.get('basic_sentence'))}</div>", unsafe_allow_html=True)
                    if row.get('collocations'):
                        st.markdown(f"<div class='fc-line'><b>搭配詞</b>{esc(row.get('collocations'))}</div>", unsafe_allow_html=True)
                else:
                    if st.button("顯示答案", **W_BTN):
                        st.session_state.flash_revealed = True
                        st.rerun()

            b1, b2, b3, b4 = st.columns(4)
            if b1.button("‹ 上一個", **W_BTN):
                flash_move(-1)
                st.rerun()
            if b2.button("不記得", **W_BTN):
                flash_mark(0)
                st.rerun()
            if b3.button("記得", **W_BTN):
                flash_mark(min(stage + 1, 5))
                st.rerun()
            if b4.button("下一個 ›", **W_BTN):
                flash_move(1)
                st.rerun()
            st.caption("「不記得」熟練度歸零；「記得」+1（最高 5）。出題順序選「不熟的優先」時，熟練度低的會先出現。")

# =====================================================================
# 我是拼字王
# =====================================================================
elif main_menu == "我是拼字王":
    if df_vocab.empty:
        st.warning("目前沒有足夠的單字來進行遊戲！")
    else:
        game_mode = st.radio("選擇遊戲模式：", ["標準模式 (中文提示 + 發音)", "進階挑戰模式 (聽英文解釋拼單字)"], horizontal=True)
        is_advanced = "進階" in game_mode
        st.markdown("---")
        sel_sem_game, sel_unit_game = scope_picker(df_vocab, "game", "選擇學期/篇章範圍：", "選擇單元/課次範圍：")

        # 級別、模式、範圍、資料筆數任何一個變動，才重新篩選與出題（答題過程中的每次操作都不再重算）
        game_key = f"{selected_level}|{game_mode}|{sel_sem_game}|{sel_unit_game}|{len(df_vocab)}"
        if st.session_state.get("game_key") != game_key:
            df_filtered_game = scoped(df_vocab, sel_sem_game, sel_unit_game)
            if is_advanced:
                # 進階模式要唸英文釋義，沒有英文釋義的單字不出題
                df_filtered_game = df_filtered_game[df_filtered_game['_has_adv']]
            df_game_queue_source = df_filtered_game.drop_duplicates(subset=['word'])
            st.session_state.game_key = game_key
            st.session_state.game_empty = bool(df_game_queue_source.empty)
            st.session_state.game_queue = []
            st.session_state.game_index = 0
            st.session_state.wrong_answers = []
            st.session_state.is_finished = False
            st.session_state.last_feedback = None
            if not df_game_queue_source.empty:
                # 同一個單字有多個詞性時，把各詞性的中文釋義合併顯示（只掃一次）
                defs_by_word = {}
                for w, p, d in zip(df_filtered_game['word'], df_filtered_game['part_of_speech'], df_filtered_game['definition']):
                    if d.strip():
                        defs_by_word.setdefault(w, []).append(f"{p} {d}".strip())
                items = df_game_queue_source[['id', 'word', 'definition', '_row']].sample(frac=1).to_dict('records')
                for it in items:
                    it['definition'] = "；".join(defs_by_word.get(it['word'], []))
                if is_advanced:       # 英文釋義只有進階模式用得到，這時才向雲端讀
                    longs, lerr = fetch_long_text(active_worksheet, {str(it['id']): (it['word'], int(it['_row'])) for it in items})
                    if lerr:
                        st.session_state.game_key = None      # 讓下次重新嘗試
                        st.error(f"讀取英文釋義失敗：{lerr}")
                        st.stop()
                    for it in items:
                        it['advanced_sentence'] = longs.get(str(it['id']), {}).get('advanced_sentence', '')
                    items = [it for it in items if it['advanced_sentence'].strip()]
                    st.session_state.game_empty = not items
                st.session_state.game_queue = items

        if st.session_state.get("game_empty"):
            if is_advanced:
                st.info("這個範圍內的單字都還沒有「英文釋義」，進階模式沒有題目可出。請改用標準模式，或先補上英文釋義。")
            else:
                st.info("這個範圍沒有單字。")
        else:
            if st.session_state.game_index >= len(st.session_state.game_queue):
                st.session_state.is_finished = True

            if st.session_state.get("is_finished", False):
                st.subheader("🎉 測驗圓滿結束！")
                wrong = st.session_state.get("wrong_answers", [])
                total_q = len(st.session_state.game_queue)
                st.markdown(f"答對 **{total_q - len(wrong)}** / {total_q} 題")
                if wrong:
                    st.markdown("**答錯的單字：**")
                    for w in wrong:
                        st.markdown(f"- `{w['word']}`　{w.get('definition', '')}")
                    if st.button("只重考答錯的題目", type="primary", **W_BTN):
                        retry = list(wrong)
                        random.shuffle(retry)
                        st.session_state.game_queue = retry
                        st.session_state.game_index = 0
                        st.session_state.wrong_answers = []
                        st.session_state.is_finished = False
                        st.session_state.last_feedback = None
                        st.rerun()
                if st.button("重新挑戰本範圍", **W_BTN):
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

                with st.container(border=True):
                    st.progress((current_q_num - 1) / total_q_count, text=f"第 {current_q_num} / {total_q_count} 題")

                    if not is_advanced:
                        st.markdown(f"<div class='fc-def'>{esc(target_def)}</div>", unsafe_allow_html=True)
                        speech_buttons(target_word)
                    else:
                        # 把釋義裡的答案遮起來（顯示成 ____，唸出來變成 blank），避免直接洩漏答案
                        st.caption("聽英文解釋，拼出單字")
                        st.markdown(
                            f"<div class='fc-line' style='text-align:center'>{esc(mask_word(target_adv_def, target_word))}</div>",
                            unsafe_allow_html=True
                        )
                        speech_buttons(mask_word(target_adv_def, target_word, repl="blank"))

                    st.markdown(f"<div class='fc-hint'>{esc(hint_masked)}</div>", unsafe_allow_html=True)

                    if st.session_state.get("last_feedback"):
                        fb = st.session_state.last_feedback
                        if fb["type"] == "success":
                            st.success(fb["msg"])
                        else:
                            st.error(fb["msg"])
                        if st.button("下一題 ›", type="primary", **W_BTN):
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
                                submitted = st.form_submit_button("送出", type="primary", **W_FORM)

                            if submitted:
                                if norm_answer(user_ans) == norm_answer(target_word):
                                    st.session_state.last_feedback = {"type": "success", "msg": f"答對了！就是 `{target_word}`"}
                                else:
                                    st.session_state.wrong_answers.append(current_item)
                                    queue_srs_stage(current_item, 0)                 # 拼錯 → 熟練度歸零，背誦頁會優先出這個字
                                    st.session_state["srs_ver"] = st.session_state.get("srs_ver", 0) + 1
                                    st.session_state.last_feedback = {"type": "error", "msg": f"答錯囉！正確答案是：`{target_word}`"}
                                st.rerun()

st.markdown("<p style='text-align:center; opacity:.5; font-size:12px; margin-top:2rem;'>版權所有，切勿模仿</p>", unsafe_allow_html=True)

# ===== 檔案結束（看到這一行代表程式碼完整）=====
