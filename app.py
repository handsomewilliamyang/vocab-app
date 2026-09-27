def fetch_all_free_dictionaries(word):
    w_clean = word.strip().lower()
    real_def = ""
    real_example = ""
    phonetic = ""
    pos = ""

    # 1. 第一優先：DictionaryAPI.dev
    try:
        url_fd = f"https://api.dictionaryapi.dev/api/v2/entries/en/{w_clean}"
        res_fd = requests.get(url_fd, timeout=3)
        if res_fd.status_code == 200:
            data = res_fd.json()
            if isinstance(data, list) and len(data) > 0:
                entry = data[0]
                if 'phonetic' in entry:
                    phonetic = entry['phonetic']
                elif 'phonetics' in entry and len(entry['phonetics']) > 0:
                    for p in entry['phonetics']:
                        if p.get('text'):
                            phonetic = p.get('text')
                            break
                
                for meaning in entry.get('meanings', []):
                    if not pos:
                        pos = meaning.get('partOfSpeech', '')
                    for definition_obj in meaning.get('definitions', []):
                        if not real_def:
                            real_def = definition_obj.get('definition', '')
                        ex_candidate = definition_obj.get('example', '')
                        if ex_candidate and not is_bad_example_sentence(ex_candidate, w_clean):
                            real_example = ex_candidate
                        if real_def and real_example:
                            break
                    if real_def and real_example:
                        break
    except Exception:
        pass

    # 2. 第二優先防線：FreeDictionaryAPI.com (Wiktionary 資料源)
    if not real_example or not real_def:
        try:
            url_wiki = f"https://freedictionaryapi.com/api/v1/entries/en/{w_clean}"
            res_wiki = requests.get(url_wiki, timeout=3)
            if res_wiki.status_code == 200:
                w_data = res_wiki.json()
                # 依據其結構解析釋義與例句
                # (可根據回傳欄位調整，若有取得則賦值給 real_def / real_example)
        except Exception:
            pass

    # 3. 第三優先防線：Datamuse API (輔助抓取同義字與簡明定義)
    if not real_def:
        try:
            url_dm = f"https://api.datamuse.com/words?sp={w_clean}&md=dpref&max=1"
            res_dm = requests.get(url_dm, timeout=3)
            if res_dm.status_code == 200:
                data = res_dm.json()
                if isinstance(data, list) and len(data) > 0:
                    item = data[0]
                    if not phonetic and 'ipa' in item:
                        phonetic = f"/{item['ipa']}/"
                    if 'defs' in item:
                        for raw_def in item['defs']:
                            parts = raw_def.split('\t', 1)
                            if not pos and len(parts) > 0:
                                pos = parts[0]
                            clean_d = parts[1] if len(parts) > 1 else raw_def
                            if not real_def:
                                real_def = clean_d.capitalize()
                            if real_def:
                                break
        except Exception:
            pass

    # 4. 第四優先防線：Tatoeba 句库比對
    if not real_example:
        tatoeba_sent = fetch_tatoeba_example(w_clean)
        if tatoeba_sent:
            real_example = tatoeba_sent

    return real_def, real_example, phonetic, pos
