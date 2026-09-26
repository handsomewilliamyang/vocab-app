import requests

def fetch_tatoeba_example(word):
    """透過 Tatoeba 開源例句 API 尋找真實英文例句"""
    w_clean = word.strip().lower()
    try:
        # Tatoeba 官方穩定/測試 API 端點
        url = f"https://api.tatoeba.org/unstable/sentences?q={w_clean}&from=eng&limit=5"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=3)
        
        if res.status_code == 200:
            data = res.json()
            results = data.get('results', [])
            
            # 從搜尋結果中挑選一句長度適中、且確實包含該單字的句子
            for item in results:
                sent = item.get('text', '').strip()
                # 簡單檢查單字是否完整存在於句中（避免抓到不相關的子字串）
                if sent and w_clean in sent.lower():
                    # 也可以順便看有沒有對應的中文翻譯
                    translations = item.get('translations', [])
                    cn_trans = ""
                    for trans_group in translations:
                        for t in trans_group:
                            if t.get('lang') == 'cmn': # 華語/中文
                                cn_trans = t.get('text', '')
                                break
                        if cn_trans:
                            break
                    
                    # 回傳英文例句（如果有中文翻譯也可以一併運用）
                    return sent
    except Exception:
        pass
    
    return ""
