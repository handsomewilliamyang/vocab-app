import concurrent.futures
import html
import json
import random
import re
import urllib.parse

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
import gspread
from google.oauth2.service_account import Credentials

# ---- Gemini：新舊套件都支援（新：google-genai；舊：google-generativeai）----
try:
    from google import genai as genai_new
    HAS_GENAI_NEW = True
except Exception:
    HAS_GENAI_NEW = False
try:
    import google.generativeai as genai_old
    HAS_GENAI_OLD = True
except Exception:
    HAS_GENAI_OLD = False

# ---- 簡轉繁：有裝 opencc 就用，沒裝就只用下方的詞彙表 ----
try:
    from opencc import OpenCC
    _OPENCC = OpenCC("s2tw")
except Exception:
    _OPENCC = None

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

st.session_state.gemini_api_key = st.secrets.get("gemini_api_key", "")
GEMINI_MODEL = st.secrets.get("gemini_model", "gemini-3.8-flash")   # 模型名稱改了可在 secrets 設 gemini_model
HAS_AI = bool(st.session_state.gemini_api_key) and (HAS_GENAI_NEW or HAS_GENAI_OLD)

current_sheet_name = selected_level
st.title("📚 我愛背單字")

HEADERS = ['id', 'word', 'phonetic', 'part_of_speech', 'definition',
           'advanced_sentence', 'basic_sentence', 'collocations', 'unit_tag', 'srs_stage']


# =====================================================================
# Google 試算表
# =====================================================================
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
        return spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols="10")


@st.cache_data(ttl=300, show_spinner=False)
def load_vocab_dataframe(_worksheet, cache_key):
    # 讀取失敗時讓錯誤直接往上丟（不會被當成空表快取，避免之後存檔把雲端蓋成空的）
    all_values = _worksheet.get_all_values()

    if len(all_values) > 1:
        headers = [str(h).strip().lower() for h in all_values[0]]
        df_temp = pd.DataFrame(all_values[1:], columns=headers[:len(all_values[0])])
    else:
        df_temp = pd.DataFrame(columns=HEADERS)

    for col in HEADERS:
        if col not in df_temp.columns:
            df_temp[col] = ""

    df_temp = df_temp[df_temp['word'].astype(str).str.strip() != '']

    # 向量化清理（取代原本逐格迴圈，單字多時快很多）
    df_temp = df_temp.astype(str)
    junk = df_temp.apply(lambda s: s.str.strip().str.lower().isin(['nan', 'none', '']))
    df_temp = df_temp.mask(junk, '')

    def normalize_tag(tag):
        t = str(tag).strip()
        if '>' in t:
            parts = t.split('>', 1)
            return f"{parts[0].strip()} > {parts[1].strip()}"
        return t
    df_temp['unit_tag'] = df_temp['unit_tag'].apply(normalize_tag)

    # 注意：刻意保留原本的 index → 試算表列號 = index + 2（熟練度更新要用）
    return df_temp


try:
    with st.spinner("⏳ 正在從雲端載入單字資料庫..."):
        gs_client = init_gsheets_client()
        active_worksheet = get_active_worksheet(gs_client, st.secrets["sheet_url"], current_sheet_name)
        df_vocab = load_vocab_dataframe(active_worksheet, current_sheet_name)
except Exception as e:
    st.error(f"⚠️ 連線或讀取 Google 試算表發生錯誤：{e}")
    st.stop()

# 套用本機已存的熟練度（避免每按一次都要重讀整張表）
for (_sheet, _rid, _w), _stg in st.session_state.get("srs_local", {}).items():
    if _sheet == current_sheet_name:
        _m = (df_vocab['id'].astype(str) == _rid) & (df_vocab['word'] == _w)
        df_vocab.loc[_m, 'srs_stage'] = str(_stg)

col_m1, col_m2 = st.columns(2)
col_m1.metric(label="雲端總單字數", value=f"{len(df_vocab)} 個")
clean_mode_name = main_menu.replace("✨ ", "").replace("📖 ", "").replace("🎯 ", "").replace("🎮 ", "")
col_m2.metric(label="目前模式", value=f"{clean_mode_name}【{selected_level}】")
st.markdown("<br>", unsafe_allow_html=True)

# 重新整理後仍能看到的提示訊息
for _kind, _msg in st.session_state.pop("flash", []):
    {"success": st.success, "warning": st.warning, "error": st.error}.get(_kind, st.info)(_msg)


def esc(x):
    return html.escape(str(x if x is not None else ""))


# =====================================================================
# 簡轉繁
# =====================================================================
S2T_DICT = {
    "餐厅": "餐廳", "饭厅": "餐廳", "计算机": "電腦", "网络": "網路",
    "软件": "軟體", "硬件": "硬體", "信息": "資訊", "视频": "影片",
    "音频": "音訊", "打印": "列印", "鼠标": "滑鼠", "键盘": "鍵盤",
    "屏幕": "螢幕", "默认": "預設", "组": "組", "词": "詞", "语法": "語法"
}


def simple_s2t_convert(text):
    if not text:
        return text
    for s, t in S2T_DICT.items():
        text = text.replace(s, t)
    if _OPENCC:
        text = _OPENCC.convert(text)
    return text


# =====================================================================
# 解析貼上的文字
# =====================================================================
def parse_mixed_vocab_input(word, raw_def="", pasted_pos="", pasted_eng_def="", pasted_sent="", pasted_colloc=""):
    w_clean = word.strip()
    w_lower = w_clean.lower()
    cleaned_def = simple_s2t_convert(raw_def) if raw_def else ""
    records = []

    if pasted_pos:
        pos_list = [p.strip() for p in re.split(r'[,/]', pasted_pos) if p.strip()]
        for p in pos_list:
            records.append({
                "word": w_clean,
                "phonetic": f"/{w_lower}/",
                "part_of_speech": simple_s2t_convert(p),
                "definition": cleaned_def,
                "advanced_sentence": pasted_eng_def or f"An English term meaning {cleaned_def}.",
                "basic_sentence": pasted_sent or f"Example sentence for {w_clean}.",
                "collocations": pasted_colloc or f"{w_clean} collocation"
            })
        return records

    matches = re.findall(r'(v\.|n\.|adj\.|adv\.|prep\.|conj\.|pron\.|phr\.|aux\.)', cleaned_def, flags=re.IGNORECASE)
    if matches and len(matches) > 0:
        pure_def = cleaned_def
        for m in matches:
            pure_def = pure_def.replace(m, "")
        pure_def = pure_def.strip().strip(';').strip(',').strip('；').strip()

        for idx, m in enumerate(matches):
            p_formatted = m.lower()
            if not p_formatted.endswith('.'):
                p_formatted += '.'

            records.append({
                "word": w_clean,
                "phonetic": f"/{w_lower}/",
                "part_of_speech": simple_s2t_convert(p_formatted),
                "definition": simple_s2t_convert(pure_def),
                "advanced_sentence": pasted_eng_def or f"An English term referring to {w_clean}.",
                "basic_sentence": pasted_sent or f"Example sentence for {w_clean}.",
                "collocations": pasted_colloc or f"{w_clean} related expression"
            })
        if records:
            return records

    fallback_pos = "phr." if " " in w_clean else "n."
    records.append({
        "word": w_clean,
        "phonetic": f"/{w_lower}/",
        "part_of_speech": fallback_pos,
        "definition": cleaned_def,
        "advanced_sentence": pasted_eng_def or f"A standard English expression referring to {w_clean}.",
        "basic_sentence": pasted_sent or f"Example sentence for {w_clean}.",
        "collocations": pasted_colloc or f"Common collocation with {w_clean}"
    })

    return records


def parse_raw_vocab_line_advanced(line):
    line_clean = re.sub(r'^\d+[\.\s]*', '', line).strip()
    if not line_clean:
        return []

    if '|' in line_clean:
        parts = [p.strip() for p in line_clean.split('|')]
        w = parts[0].strip()
        d = parts[1].strip() if len(parts) > 1 else ""
        pasted_p = parts[2].strip() if len(parts) > 2 else ""
        pasted_eng = parts[3].strip() if len(parts) > 3 else ""
        pasted_s = parts[4].strip() if len(parts) > 4 else ""
        pasted_c = parts[5].strip() if len(parts) > 5 else ""
        return parse_mixed_vocab_input(w, raw_def=d, pasted_pos=pasted_p, pasted_eng_def=pasted_eng, pasted_sent=pasted_s, pasted_colloc=pasted_c)

    match_split = re.search(r'([\u4e00-\u9fa5]|v\.|n\.|adj\.|adv\.|prep\.|conj\.|pron\.|phr\.)', line_clean, re.IGNORECASE)
    if not match_split:
        return [{
            "word": line_clean,
            "phonetic": f"/{line_clean.lower()}/",
            "part_of_speech": "phr." if " " in line_clean else "n.",
            "definition": "",
            "advanced_sentence": f"An English term referring to {line_clean}.",
            "basic_sentence": f"Example for {line_clean}.",
            "collocations": f"Collocation for {line_clean}"
        }]

    word_end_idx = match_split.start()
    word = line_clean[:word_end_idx].strip()
    rest = line_clean[word_end_idx:].strip()

    if not word:
        parts = line_clean.split(maxsplit=1)
        word = parts[0] if len(parts) > 0 else line_clean
        rest = parts[1] if len(parts) > 1 else ""

    return parse_mixed_vocab_input(word, raw_def=rest)


# =====================================================================
# 自動補齊：免費字典 → Gemini 備援
# =====================================================================
DICT_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/"
AI_BATCH_SIZE = 15

POS_MAP = {
    "noun": "n.", "verb": "v.", "adjective": "adj.", "adverb": "adv.",
    "preposition": "prep.", "conjunction": "conj.", "pronoun": "pron.",
    "interjection": "interj.", "determiner": "det.", "exclamation": "interj.",
}

LEVEL_HINT = {
    "國中部": "台灣國中生（CEFR A2 以下），英文釋義與例句請用最簡單的字彙與短句",
    "高中部": "台灣高中生（CEFR B1–B2），例句約 10–15 個字",
    "TOEIC": "TOEIC 考生，例句請用職場／商務情境",
}

# 上面 parse 函式塞的「假資料」，一律視為空白，才能被真資料取代
_PLACEHOLDER_PATTERNS = [
    r"^An English term ",
    r"^A standard English expression referring to ",
    r"^Example (sentence )?for ",
    r"^Collocation for ",
    r"^Common collocation with ",
]


def is_blank_or_placeholder(text, word):
    t = (text or "").strip()
    if not t:
        return True
    w = (word or "").strip().lower()
    if t.lower() in (f"{w} collocation", f"{w} related expression"):
        return True
    return any(re.match(p, t) for p in _PLACEHOLDER_PATTERNS)


def strip_placeholders(records):
    for r in records:
        w = r.get("word", "")
        for k in ("advanced_sentence", "basic_sentence", "collocations"):
            if is_blank_or_placeholder(r.get(k), w):
                r[k] = ""
        if (r.get("phonetic") or "").strip().lower() == f"/{w.strip().lower()}/":
            r["phonetic"] = ""
    return records


def _norm_phonetic(p):
    p = (p or "").strip().strip("/[] ")
    return f"/{p}/" if p else ""


def _pick_phonetic(entries):
    fallback = ""
    for e in entries:
        for p in e.get("phonetics", []):
            text = p.get("text") or ""
            if not text:
                continue
            if "-us" in (p.get("audio") or ""):      # 優先美式
                return _norm_phonetic(text)
            fallback = fallback or text
        fallback = fallback or (e.get("phonetic") or "")
    return _norm_phonetic(fallback)


def _parse_entries(entries):
    meanings = {}   # 詞性 -> 第一個義項（例句才會跟釋義對得上）
    for e in entries:
        for m in e.get("meanings", []):
            raw = (m.get("partOfSpeech") or "").lower()
            pos = POS_MAP.get(raw, raw)
            defs = m.get("definitions") or []
            if pos and pos not in meanings and defs:
                meanings[pos] = {
                    "definition": (defs[0].get("definition") or "").strip(),
                    "example": (defs[0].get("example") or "").strip(),
                }
    return {"phonetic": _pick_phonetic(entries), "meanings": meanings}


@st.cache_data(ttl=86400, show_spinner=False)
def _fetch_dictionary_cached(word):
    # 查不到(404)回傳 None 會被快取；網路錯誤會丟例外，不會被快取
    r = requests.get(DICT_URL + urllib.parse.quote(word), timeout=8)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return _parse_entries(r.json())


def lookup_dictionary(word):
    try:
        return _fetch_dictionary_cached(word)
    except Exception:
        return None


AI_TIMEOUT_SEC = 45   # AI 最久等幾秒，超過就放棄（不會再無限卡住）


class AITimeout(RuntimeError):
    pass


def _gemini_call(key, prompt):
    cfg = {"response_mime_type": "application/json", "temperature": 0.3}
    if HAS_GENAI_NEW:
        client = genai_new.Client(api_key=key)
        return client.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=cfg).text
    genai_old.configure(api_key=key)
    model = genai_old.GenerativeModel(GEMINI_MODEL, generation_config=cfg)
    return model.generate_content(prompt).text


def _gemini_generate_json(prompt):
    key = st.session_state.get("gemini_api_key", "")
    if not key:
        raise RuntimeError("尚未在 secrets 設定 gemini_api_key")
    if not (HAS_GENAI_NEW or HAS_GENAI_OLD):
        raise RuntimeError("沒有安裝 google-genai（或 google-generativeai）套件")
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(_gemini_call, key, prompt)
    try:
        return fut.result(timeout=AI_TIMEOUT_SEC)
    except concurrent.futures.TimeoutError:
        raise AITimeout(f"AI 超過 {AI_TIMEOUT_SEC} 秒沒有回應，已放棄（可稍後再試，或換模型）")
    finally:
        ex.shutdown(wait=False)


def ai_fill(items, level):
    """items: [{"i","word","pos","chinese","need":[...]}] → ({i: {欄位: 值}}, 錯誤訊息)"""
    results, first_err = {}, ""
    if not items:
        return results, first_err
    hint = LEVEL_HINT.get(level, "英語學習者")
    for start in range(0, len(items), AI_BATCH_SIZE):
        chunk = items[start:start + AI_BATCH_SIZE]
        prompt = f"""你是台灣的英語教材編輯。學習者：{hint}。
下面是 JSON 陣列，每筆有 i、word、pos（詞性）、chinese（使用者提供的中文，可能為空）、need（需要你補的欄位）。
請回傳 JSON 陣列，每筆包含 i，以及 need 裡列出的欄位（不要多給）：
- phonetic：IPA 音標，用斜線包住，例如 /rɪˈzɪliənt/
- definition_zh：繁體中文（台灣用語），簡短，不含詞性縮寫
- definition_en：一句話的英文釋義
- example：一個英文例句，符合指定詞性與 chinese 的意思，句中要包含該單字（可變化詞形）
- collocations：3 個常見搭配詞或片語（陣列），須包含該單字
只輸出 JSON。
資料：{json.dumps(chunk, ensure_ascii=False)}"""
        try:
            text = _gemini_generate_json(prompt).strip()
            text = re.sub(r"^```(?:json)?|```$", "", text).strip()
            for obj in json.loads(text):
                results[int(obj["i"])] = obj
        except AITimeout as e:
            first_err = first_err or str(e)
            break                      # 逾時就不要再等下一批
        except Exception as e:
            first_err = first_err or str(e)
    return results, first_err


_FIELD_MAP = {
    "phonetic": "phonetic",
    "definition_zh": "definition",
    "definition_en": "advanced_sentence",
    "example": "basic_sentence",
    "collocations": "collocations",
}


def enrich_records(records, level, enabled=True, progress=None):
    """回傳 (records, stats)。使用者自己填的欄位絕不覆蓋，只補空白的。"""
    strip_placeholders(records)
    stats = {"dict": 0, "ai": 0, "missing": 0, "ai_error": ""}
    if not enabled or not records:
        return records, stats

    got_dict, got_ai, pending = set(), set(), []
    n = len(records)

    for i, r in enumerate(records):
        if progress:
            progress(0.85 * (i / n), f"查字典：{r.get('word', '')}")
        word = (r.get("word") or "").strip()
        is_phrase = " " in word
        info = None if is_phrase else lookup_dictionary(word.lower())

        if info:
            meanings = info["meanings"]
            # 只貼單字沒給釋義時，詞性是程式猜的 → 改用字典的第一個詞性
            if r.get("part_of_speech") not in meanings and not r.get("definition") and meanings:
                r["part_of_speech"] = next(iter(meanings))
            if not r.get("phonetic") and info["phonetic"]:
                r["phonetic"] = info["phonetic"]
                got_dict.add(i)
            m = meanings.get(r.get("part_of_speech"))
            if m:
                if not r.get("advanced_sentence") and m["definition"]:
                    r["advanced_sentence"] = m["definition"]
                    got_dict.add(i)
                if not r.get("basic_sentence") and m["example"]:
                    r["basic_sentence"] = m["example"]
                    got_dict.add(i)

        need = []
        if not is_phrase and not r.get("phonetic"):
            need.append("phonetic")
        if not r.get("definition"):
            need.append("definition_zh")
        if not r.get("advanced_sentence"):
            need.append("definition_en")
        if not r.get("basic_sentence"):
            need.append("example")
        if not r.get("collocations"):          # 免費字典沒有搭配詞，這項一定靠 AI
            need.append("collocations")
        if need:
            pending.append({"i": i, "word": word, "pos": r.get("part_of_speech", ""),
                            "chinese": r.get("definition", ""), "need": need})

    if progress and pending:
        progress(0.9, f"字典查不到的部分，請 AI 補齊中…（單字少約 5～15 秒，最久等 {AI_TIMEOUT_SEC} 秒）")
    results, err = ai_fill(pending, level)
    stats["ai_error"] = err

    for it in pending:
        res = results.get(it["i"])
        if not res:
            continue
        r = records[it["i"]]
        for src in it["need"]:
            val = res.get(src)
            if isinstance(val, list):
                val = " / ".join(str(v).strip() for v in val if str(v).strip())
            val = str(val or "").strip()
            if not val:
                continue
            if src == "phonetic":
                val = _norm_phonetic(val)
            elif src == "definition_zh":
                val = simple_s2t_convert(val)
            r[_FIELD_MAP[src]] = val
            got_ai.add(it["i"])

    stats["dict"] = len(got_dict)
    stats["ai"] = len(got_ai)
    stats["missing"] = sum(
        1 for r in records
        if not (r.get("definition") and r.get("advanced_sentence") and r.get("basic_sentence"))
    )
    return records, stats


# =====================================================================
# 存檔
# =====================================================================
def save_all_vocab_to_sheet(_worksheet, df):
    """整張覆寫（只有「修改舊資料」或「刪除」才會用到）。
    先寫新內容，再清掉多出來的尾巴，中途出錯也不會變成空表。"""
    try:
        out = df.reindex(columns=HEADERS).fillna("").astype(str)
        rows = [HEADERS] + out.values.tolist()
        if len(rows) > _worksheet.row_count:
            _worksheet.resize(rows=len(rows) + 200)
        _worksheet.update(values=rows, range_name="A1", value_input_option="RAW")
        _worksheet.batch_clear([f"A{len(rows) + 1}:J"])
        load_vocab_dataframe.clear()
        st.session_state["srs_local"] = {}   # 整張重寫後 id 可能變動，本機熟練度快取作廢
        return True, "成功"
    except Exception as e:
        return False, str(e)


def get_next_id(df):
    """取目前最大編號 + 1"""
    ids = pd.to_numeric(df['id'], errors='coerce').dropna()
    return int(ids.max()) + 1 if not ids.empty else 1


def persist_changes(_worksheet, df_after, new_rows, updated, was_empty):
    """只有新增 → 只在表格最後面補幾列（快）；
    有修改舊資料，或原本是空表（要補標題列）→ 整張覆寫。"""
    if updated or was_empty:
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
    """把 records 併進 df_current：同單字+詞性+單元 → 更新（只更新有值的欄位）；否則新增。"""
    new_rows, updated, count = [], False, 0
    for data in records:
        word = str(data.get('word', '')).strip()
        if not word:
            continue
        pos = str(data.get('part_of_speech', '')).strip()
        mask = (
            (df_current['word'].astype(str).str.strip().str.lower() == word.lower()) &
            (df_current['part_of_speech'].astype(str).str.strip().str.lower() == pos.lower()) &
            (df_current['unit_tag'].astype(str).str.strip() == unit_tag)
        )
        if not df_current.empty and mask.any():
            idx = df_current.index[mask].tolist()[0]
            for col in ('phonetic', 'definition', 'advanced_sentence', 'basic_sentence', 'collocations'):
                val = data.get(col)
                if val:
                    df_current.at[idx, col] = simple_s2t_convert(val) if col == 'definition' else val
            updated = True
        else:
            new_row = {
                'id': get_next_id(df_current),
                'word': word,
                'phonetic': data.get('phonetic', ''),
                'part_of_speech': pos,
                'definition': simple_s2t_convert(data.get('definition', '')),
                'advanced_sentence': data.get('advanced_sentence', ''),
                'basic_sentence': data.get('basic_sentence', ''),
                'collocations': data.get('collocations', ''),
                'unit_tag': unit_tag,
                'srs_stage': 0
            }
            new_rows.append(new_row)
            df_current = pd.concat([df_current, pd.DataFrame([new_row])], ignore_index=True)
        count += 1
    return df_current, new_rows, updated, count


def import_records(records, unit_tag, auto_fill, clear_paste=False):
    """補齊 → 合併 → 存檔 → 顯示結果（含 AI 失敗原因）"""
    bar = st.progress(0.0, text="準備中…")
    records, stats = enrich_records(
        records, selected_level, enabled=auto_fill,
        progress=lambda p, t: bar.progress(min(max(p, 0.0), 1.0), text=t)
    )
    bar.progress(0.95, text="寫入雲端中…")
    load_vocab_dataframe.clear()   # 寫入前重讀最新資料，避免蓋掉別處的修改
    df_current = load_vocab_dataframe(active_worksheet, current_sheet_name).copy()
    was_empty = df_current.empty
    df_current, new_rows, updated, count = merge_records(df_current, records, unit_tag)
    ok, msg = persist_changes(active_worksheet, df_current, new_rows, updated, was_empty)
    bar.empty()
    if not ok:
        st.error(f"寫入失敗：{msg}")
        st.stop()

    flash = []
    text = f"🎉 成功處理 {count} 個項目"
    if auto_fill:
        text += f"（字典補齊 {stats['dict']} 筆、AI 補齊 {stats['ai']} 筆）"
    flash.append(("success", text))
    if auto_fill and stats["ai_error"]:
        flash.append(("warning", f"⚠️ AI 補齊失敗，已略過：{stats['ai_error']}"))
    if auto_fill and stats["missing"]:
        flash.append(("warning", f"有 {stats['missing']} 筆資料仍不完整（中文釋義／英文釋義／例句缺漏），可到「字彙管理」確認。"))
    st.session_state.flash = flash
    if clear_paste:
        st.session_state.clear_paste = True
    st.rerun()


# =====================================================================
# 熟練度（srs_stage 0~5）
# =====================================================================
def parse_stage(v):
    try:
        return max(0, min(5, int(float(str(v).strip()))))
    except Exception:
        return 0


def save_srs_stage(row, new_stage):
    """只更新試算表的一個儲存格。寫入前先確認該列的 id 與單字沒變，避免寫錯列。"""
    rid, word = str(row.get('id', '')), str(row.get('word', ''))
    try:
        rn = row['_row']
        check = active_worksheet.get(f"A{rn}:B{rn}")
        same = (bool(check) and len(check[0]) >= 2
                and str(check[0][0]).strip() == rid.strip()
                and str(check[0][1]).strip().lower() == word.strip().lower())
        if not same:
            load_vocab_dataframe.clear()
            return False
        active_worksheet.update_cell(rn, HEADERS.index('srs_stage') + 1, new_stage)
        st.session_state.setdefault("srs_local", {})[(current_sheet_name, rid, word)] = new_stage
        row['_stage'] = new_stage
        return True
    except Exception:
        return False


def build_flash_queue(df, order_mode):
    items = []
    for idx, r in df.iterrows():
        d = r.to_dict()
        d['_row'] = int(idx) + 2
        d['_stage'] = parse_stage(d.get('srs_stage'))
        items.append(d)
    if order_mode == "依編號順序":
        items.sort(key=lambda d: float(pd.to_numeric(d.get('id'), errors='coerce') or 0))
    else:
        random.shuffle(items)
        if order_mode == "不熟的優先":
            items.sort(key=lambda d: d['_stage'])     # 穩定排序：同熟練度內維持隨機
    return items


# =====================================================================
# 單元階層
# =====================================================================
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


def get_hierarchical_units(df):
    semesters = []
    semester_to_units = {}
    if 'unit_tag' in df.columns:
        for ut in df['unit_tag'].dropna().unique():
            ut_str = str(ut).strip()
            if not ut_str:
                continue
            if '>' in ut_str:
                sem, un = ut_str.split('>', 1)
                sem = sem.strip()
                un = un.strip()
                if sem not in semesters:
                    semesters.append(sem)
                if sem not in semester_to_units:
                    semester_to_units[sem] = []
                if un not in semester_to_units[sem]:
                    semester_to_units[sem].append(un)

    for sem in semester_to_units:
        semester_to_units[sem].sort(key=parse_lesson_number)

    return sorted(semesters), semester_to_units


# =====================================================================
# 發音：瀏覽器內建語音
# =====================================================================
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


# =====================================================================
# ✨ 新增單字
# =====================================================================
if main_menu == "✨ 新增單字":
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

    auto_fill = st.checkbox("🤖 自動補齊音標／詞性／英文釋義／例句／搭配詞（先查免費字典，查不到再用 AI）", value=True)
    if auto_fill and not HAS_AI:
        st.caption("⚠️ 偵測不到可用的 Gemini 金鑰或套件：只會用免費字典補，搭配詞與中文釋義無法補。")

    # 匯入成功後清空貼上框（必須在 text_area 建立之前處理）
    if st.session_state.pop("clear_paste", False):
        st.session_state["paste_box"] = ""

    col_input1, col_input2 = st.columns(2, gap="large")
    with col_input1:
        st.subheader("📝 單筆快速建檔")
        with st.form("single_add_form", clear_on_submit=True):
            single_word = st.text_input("輸入想要學習的英文單字：", placeholder="例如：resilient")
            single_def = st.text_input("中文釋義（選填）：", placeholder="例如：v.張貼；n.職位")
            single_sent = st.text_input("真實例句（選填）：", placeholder="例如：Sentence here")
            single_colloc = st.text_input("搭配詞（選填）：", placeholder="例如：Collocation here")
            submitted_single = st.form_submit_button("🚀 瞬間寫入雲端", type="primary", use_container_width=True)

        if submitted_single:
            if single_word.strip():
                records = parse_mixed_vocab_input(single_word, raw_def=single_def, pasted_sent=single_sent, pasted_colloc=single_colloc)
                import_records(records, current_unit_tag, auto_fill)
            else:
                st.warning("請先輸入英文單字")

    with col_input2:
        st.subheader("📋 智慧多格式快速貼上匯入")
        st.markdown(f"📍 **[狀態欄] 目前目標分類：** `{selected_level} ({current_unit_tag})`")

        pasted_text = st.text_area("貼上完整單字清單", key="paste_box",
                                   placeholder="source | 來源 | n. | A place... | Sentence | Collocation\n或只貼：resilient 有彈性的\n或只貼單字：resilient",
                                   height=140, label_visibility="collapsed")

        valid_lines = [l for l in pasted_text.strip().split('\n') if l.strip()] if pasted_text else []
        total_preview_count = len(valid_lines)
        if total_preview_count > 0:
            st.info(f"📊 **狀態預覽：** 偵測到 **{total_preview_count}** 個項目準備匯入至「{current_unit_tag}」")
        else:
            st.caption(f"📊 **狀態預覽：** 尚未貼上資料（目標：{current_unit_tag}）")

        if st.button("📥 批次秒速匯入", use_container_width=True):
            if valid_lines:
                records = []
                for line in valid_lines:
                    records.extend(parse_raw_vocab_line_advanced(line))
                if records:
                    import_records(records, current_unit_tag, auto_fill, clear_paste=True)
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
            sem_options = ["全部單字"] + semesters
            selected_sem = st.selectbox("1️⃣ 選擇學期/篇章：", sem_options)
        with col_sel2:
            if selected_sem == "全部單字":
                selected_unit_filter = "全部單字"
                st.selectbox("2️⃣ 選擇單元/課次：", ["全部單元"], disabled=True)
            else:
                unit_options = ["全部單元"] + sem_to_units.get(selected_sem, [])
                selected_unit = st.selectbox("2️⃣ 選擇單元/課次：", unit_options)
                if selected_unit == "全部單元":
                    selected_unit_filter = selected_sem
                else:
                    selected_unit_filter = f"{selected_sem} > {selected_unit}"

        if selected_unit_filter == "全部單字":
            filtered_df = df_vocab
        elif " > " not in selected_unit_filter:
            filtered_df = df_vocab[df_vocab['unit_tag'].astype(str).str.startswith(selected_unit_filter)]
        else:
            filtered_df = df_vocab[df_vocab['unit_tag'] == selected_unit_filter]

        col_f1, col_f2 = st.columns(2, gap="medium")
        with col_f1:
            search_query = st.text_input("🔍 搜尋單字或釋義：")
            if search_query:
                filtered_df = filtered_df[filtered_df['word'].str.contains(search_query, case=False, na=False) | filtered_df['definition'].str.contains(search_query, case=False, na=False)]
        with col_f2:
            sub_col1, sub_col2 = st.columns([3, 1], gap="small")
            with sub_col1:
                delete_choices = list(dict.fromkeys(filtered_df['word'].tolist())) if not filtered_df.empty else []
                word_to_delete = st.selectbox("🗑️ 快速刪除單字：", ["--請選擇要刪除的單字--"] + delete_choices)
                if word_to_delete != "--請選擇要刪除的單字--":
                    if st.button(f"確認刪除：{word_to_delete}", type="primary", use_container_width=True):
                        load_vocab_dataframe.clear()   # 刪除前先重讀最新資料
                        df_current = load_vocab_dataframe(active_worksheet, current_sheet_name).copy()
                        if selected_unit_filter == "全部單字":
                            df_current = df_current[df_current['word'].astype(str).str.strip().str.lower() != word_to_delete.strip().lower()]
                        elif " > " not in selected_unit_filter:
                            df_current = df_current[~((df_current['word'].astype(str).str.strip().str.lower() == word_to_delete.strip().lower()) & (df_current['unit_tag'].astype(str).str.startswith(selected_unit_filter)))]
                        else:
                            df_current = df_current[~((df_current['word'].astype(str).str.strip().str.lower() == word_to_delete.strip().lower()) & (df_current['unit_tag'] == selected_unit_filter))]

                        if not df_current.empty:
                            df_current['id'] = range(1, len(df_current) + 1)
                        ok, msg = save_all_vocab_to_sheet(active_worksheet, df_current)
                        if not ok:
                            st.error(f"刪除失敗：{msg}")
                            st.stop()
                        st.session_state.flash = [("success", f"已刪除：{word_to_delete}")]
                        st.rerun()
            with sub_col2:
                st.write("")
                st.write("")
                if st.button("🗑️ 刪除該單元", type="secondary", use_container_width=True):
                    if selected_unit_filter == "全部單字" or " > " not in selected_unit_filter:
                        st.warning("⚠️ 請先在上方選單選擇到具體某個單元，才能執行刪除！")
                    else:
                        load_vocab_dataframe.clear()
                        df_current = load_vocab_dataframe(active_worksheet, current_sheet_name).copy()
                        df_current = df_current[df_current['unit_tag'] != selected_unit_filter]
                        if not df_current.empty:
                            df_current['id'] = range(1, len(df_current) + 1)
                        ok, msg = save_all_vocab_to_sheet(active_worksheet, df_current)
                        if not ok:
                            st.error(f"刪除失敗：{msg}")
                            st.stop()
                        st.session_state.flash = [("success", f"🗑️ 已成功刪除「{selected_unit_filter}」整單元單字！")]
                        st.rerun()

        st.markdown("---")
        with st.expander("📋 單字總表", expanded=True):
            show_df = filtered_df[['id', 'word', 'phonetic', 'part_of_speech', 'definition', 'advanced_sentence', 'basic_sentence', 'collocations', 'srs_stage']].copy()
            show_df['srs_stage'] = show_df['srs_stage'].apply(parse_stage)
            st.dataframe(
                show_df,
                use_container_width=False,
                hide_index=True,
                column_config={
                    "id": st.column_config.NumberColumn("編號", width="small"),
                    "word": st.column_config.TextColumn("單字", width="medium"),
                    "phonetic": st.column_config.TextColumn("音標", width="small"),
                    "part_of_speech": st.column_config.TextColumn("詞性", width="small"),
                    "definition": st.column_config.TextColumn("中文釋義", width="medium"),
                    "advanced_sentence": st.column_config.TextColumn("英文釋義", width="large"),
                    "basic_sentence": st.column_config.TextColumn("真實例句", width="large"),
                    "collocations": st.column_config.TextColumn("搭配詞", width="medium"),
                    "srs_stage": st.column_config.NumberColumn("熟練度(0-5)", width="small"),
                }
            )


# =====================================================================
# 🎯 背誦單字（含熟練度）
# =====================================================================
elif main_menu == "🎯 背誦單字":
    if df_vocab.empty:
        st.warning("📭 目前雲端沒有單字！")
    else:
        semesters, sem_to_units = get_hierarchical_units(df_vocab)
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            sel_sem_flash = st.selectbox("🎯 選擇學期/篇章：", ["全部單字"] + semesters, key="flash_sem_select")
        with col_f2:
            if sel_sem_flash == "全部單字":
                sel_unit_flash = "全部單元"
                st.selectbox("🎯 選擇單元/課次：", ["全部單元"], disabled=True, key="flash_unit_disabled")
            else:
                sel_unit_flash = st.selectbox("🎯 選擇單元/課次：", ["全部單元"] + sem_to_units.get(sel_sem_flash, []), key="flash_unit_select")

        col_o1, col_o2 = st.columns(2)
        with col_o1:
            order_mode = st.radio("出題順序：", ["不熟的優先", "隨機", "依編號順序"], horizontal=True, key="flash_order")
        with col_o2:
            hide_answer = st.checkbox("🙈 先隱藏答案（自我測驗，想完再點「顯示答案」）", value=False, key="flash_hide")

        if sel_sem_flash == "全部單字":
            df_filtered_flash = df_vocab
        elif sel_unit_flash == "全部單元":
            df_filtered_flash = df_vocab[df_vocab['unit_tag'].astype(str).str.startswith(sel_sem_flash)]
        else:
            df_filtered_flash = df_vocab[df_vocab['unit_tag'] == f"{sel_sem_flash} > {sel_unit_flash}"]

        if df_filtered_flash.empty:
            st.info("這個範圍沒有單字。")
        else:
            sig = f"{current_sheet_name}|{sel_sem_flash}|{sel_unit_flash}|{order_mode}|{len(df_filtered_flash)}"
            if st.session_state.get("flash_sig") != sig:
                st.session_state.flash_sig = sig
                st.session_state.flash_queue = build_flash_queue(df_filtered_flash, order_mode)
                st.session_state.flashcard_index = 0
                st.session_state.flash_revealed = False

            queue = st.session_state.flash_queue
            total_count = len(queue)
            st.session_state.flashcard_index = st.session_state.flashcard_index % total_count
            row = queue[st.session_state.flashcard_index]
            stage = row['_stage']
            show_answer = (not hide_answer) or st.session_state.get("flash_revealed", False)

            def flash_move(step):
                st.session_state.flashcard_index = (st.session_state.flashcard_index + step) % total_count
                st.session_state.flash_revealed = False

            def flash_mark(new_stage):
                if not save_srs_stage(row, new_stage):
                    st.session_state.flash = [("warning", "⚠️ 熟練度沒有存進雲端（可能網路問題或試算表內容已變動），請重新整理頁面後再試。")]
                flash_move(1)

            with st.container(border=True):
                st.markdown(f"<div style='text-align:right; color:gray; font-size:14px;'>第 {st.session_state.flashcard_index + 1} / {total_count} 張　熟練度 {'⭐' * stage}{'☆' * (5 - stage)}</div>", unsafe_allow_html=True)
                st.markdown(f"<h1 style='text-align: center; font-size: 54px; margin-bottom: 5px;'>{esc(row['word'])}</h1>", unsafe_allow_html=True)
                components.html(speech_html(row['word'], justify="center"), height=50)
                st.markdown(f"<p style='text-align: center; color: gray; margin-top: 5px;'>{esc(row.get('phonetic', ''))} | {esc(row.get('part_of_speech', ''))}</p>", unsafe_allow_html=True)
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
            st.caption("「不記得」會把熟練度歸零；「記得」熟練度 +1（最高 5）。選「不熟的優先」時，熟練度低的會先出現。")


# =====================================================================
# 🎮 我是拼字王
# =====================================================================
elif main_menu == "🎮 我是拼字王":
    if df_vocab.empty:
        st.warning("📭 目前沒有足夠的單字來進行遊戲！")
    else:
        game_mode = st.radio("選擇遊戲模式：🎮", ["標準模式 (中文提示 + 發音)", "進階挑戰模式 (聽英文解釋拼單字)"], horizontal=True)
        st.markdown("---")
        semesters, sem_to_units = get_hierarchical_units(df_vocab)
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            sel_sem_game = st.selectbox("選擇學期/篇章範圍：", ["全部單字"] + semesters, key="game_sem_select")
        with col_g2:
            if sel_sem_game == "全部單字":
                sel_unit_game = "全部單元"
                st.selectbox("選擇單元/課次範圍：", ["全部單元"], disabled=True, key="game_unit_disabled")
            else:
                sel_unit_game = st.selectbox("選擇單元/課次範圍：", ["全部單元"] + sem_to_units.get(sel_sem_game, []), key="game_unit_select")

        if sel_sem_game == "全部單字":
            df_filtered_game = df_vocab
        elif sel_unit_game == "全部單元":
            df_filtered_game = df_vocab[df_vocab['unit_tag'].astype(str).str.startswith(sel_sem_game)]
        else:
            df_filtered_game = df_vocab[df_vocab['unit_tag'] == f"{sel_sem_game} > {sel_unit_game}"]

        df_game_queue_source = df_filtered_game.drop_duplicates(subset=['word'])

        if not df_filtered_game.empty:
            def reset_game(queue):
                st.session_state.game_queue = queue
                st.session_state.game_index = 0
                st.session_state.wrong_answers = []
                st.session_state.correct_count = 0
                st.session_state.is_finished = False
                st.session_state.last_feedback = None
                st.session_state.balloons_done = False
                st.session_state.game_round = st.session_state.get("game_round", 0) + 1

            # 級別、模式、範圍任何一個改變就重新開局
            sig = f"{current_sheet_name}|{game_mode}|{sel_sem_game}|{sel_unit_game}"
            if st.session_state.get("game_sig") != sig:
                st.session_state.game_sig = sig
                reset_game(df_game_queue_source.sample(frac=1).to_dict('records'))

            if st.session_state.game_index >= len(st.session_state.game_queue):
                st.session_state.is_finished = True

            if st.session_state.get("is_finished", False):
                if not st.session_state.get("balloons_done"):
                    st.balloons()
                    st.session_state.balloons_done = True
                total_q = len(st.session_state.game_queue)
                st.markdown(f"## 🎉 測驗結束！答對 {st.session_state.correct_count} / {total_q}")
                wrong = st.session_state.wrong_answers
                if wrong:
                    st.markdown("### ❌ 需要加強的單字")
                    for w in wrong:
                        st.markdown(f"- **{w['word']}**　{w.get('part_of_speech', '')} {w.get('definition', '')}")
                c_a, c_b = st.columns(2)
                if wrong and c_a.button("🔁 只重考錯題", type="primary", use_container_width=True):
                    retry = list(wrong)
                    random.shuffle(retry)
                    reset_game(retry)
                    st.rerun()
                if c_b.button("🔄 重新挑戰本範圍", use_container_width=True):
                    reset_game(df_game_queue_source.sample(frac=1).to_dict('records'))
                    st.rerun()
            else:
                current_item = st.session_state.game_queue[st.session_state.game_index]
                target_word = str(current_item['word']).strip()
                target_def = str(current_item['definition']).strip() if str(current_item['definition']).strip() else "(尚無中文釋義)"
                target_adv_def = str(current_item.get('advanced_sentence', '')).strip() or f"An English term referring to {target_word}."
                hint_masked = "".join([" _ " if c.isalpha() else "   " for c in target_word])
                hint_html = f"<code style='white-space: pre;'>{esc(hint_masked)}</code>"

                total_q_count = len(st.session_state.game_queue)
                current_q_num = st.session_state.game_index + 1
                remaining_count = total_q_count - current_q_num + 1
                rk = f"{st.session_state.game_round}_{st.session_state.game_index}"

                with st.container(border=True):
                    q_col1, q_col2 = st.columns([5, 1])
                    with q_col2:
                        st.markdown(f"<div style='text-align: right; color: gray; font-size: 15px; font-weight: bold;'>剩餘題數：{remaining_count}</div>", unsafe_allow_html=True)

                    if "標準模式" in game_mode:
                        r_col1, r_col2 = st.columns([2, 3])
                        with r_col1:
                            st.markdown(f"<h3 style='margin: 0; padding-top: 5px;'>中文：{esc(target_def)}</h3>", unsafe_allow_html=True)
                        with r_col2:
                            components.html(speech_html(target_word), height=45)
                    else:
                        st.markdown("<h3 style='margin-bottom: 5px;'>🔊 英文解釋聽力提示：</h3>", unsafe_allow_html=True)
                        st.markdown(f"<p style='font-size: 17px; font-weight: 500; margin-bottom: 10px;'>{esc(target_adv_def)}</p>", unsafe_allow_html=True)
                        components.html(speech_html(target_adv_def), height=45)

                    st.markdown(f"<div style='margin-top: 15px; margin-bottom: 15px;'><b>單字提示：</b> {hint_html}</div>", unsafe_allow_html=True)

                    if st.session_state.get("last_feedback"):
                        fb = st.session_state.last_feedback
                        if fb["type"] == "success":
                            st.success(fb["msg"])
                        else:
                            st.error(fb["msg"])
                        components.html(speech_html(target_word), height=45)   # 答完後可聽正確發音
                        if st.button("➡️ 點擊進入下一題", type="primary", use_container_width=True):
                            st.session_state.last_feedback = None
                            st.session_state.game_index += 1
                            st.rerun()
                    else:
                        with st.form(key=f"quiz_form_{rk}"):
                            f_col1, f_col2 = st.columns([4, 1], gap="small")
                            with f_col1:
                                user_ans = st.text_input("輸入答案", placeholder="在此輸入拼寫答案...", key=f"ans_input_{rk}", label_visibility="collapsed").strip().lower()
                            with f_col2:
                                submitted = st.form_submit_button("🚀 送出", type="primary", use_container_width=True)

                            if submitted:
                                if user_ans == target_word.lower():
                                    st.session_state.correct_count += 1
                                    st.session_state.last_feedback = {"type": "success", "msg": f"🎉 答對了！就是 `{target_word}`"}
                                else:
                                    st.session_state.wrong_answers.append(current_item)
                                    st.session_state.last_feedback = {"type": "error", "msg": f"❌ 答錯囉！正確答案是：`{target_word}`"}
                                st.rerun()
