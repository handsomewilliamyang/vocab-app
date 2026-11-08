# =====================================================================
# 專家模式補丁 2：自動組好「出文章」的提示詞（共 2 處貼上）
#
# 【貼上 1】把「函數」貼在上次貼的 def expert_mode(): 的正上方。
#
# 【貼上 2】找到 expert_mode() 裡這一行：
#         with st.expander("➕ 新增文章"):
#     在它的「下一行」（t = st.text_input("標題"... 的上面），
#     貼入「插入的程式碼」，縮排要和 t = st.text_input 對齊（都是 8 個空格）。
# =====================================================================


# ---------------- 【貼上 1】函數 ----------------
def article_prompt_text(level, words, n_blank, n_chars):
    return f"""請幫我寫一篇英文短文，給台灣「{level}」程度的學生做「文意選填」和「克漏字」練習。

要求：
1. 長度約 {n_chars} 字，內容自然、通順、像母語者寫的，主題日常或貼近生活。
2. 從下方單字清單中選 {n_blank} 個放進文章，每個單字只用一次，用法必須符合清單上的詞性與中文意思。
3. 被選中的單字，在文章裡要用兩層中括號包起來，例如：I [[decided]] to visit her.
4. 括號裡必須是單字「在文章中實際出現的樣子」（含 -ed、-ing、複數等變化），括號外不要再重複這個字。
5. 挖空的位置要有足夠的上下文線索，讓答案是唯一合理的；不要把兩個空格放得太近。
6. 只輸出文章本身：不要標題、不要編號、不要粗體、不要說明、不要程式碼區塊，也不要在文章後面附答案。
7. 除了 [[ ]] 之外，不要使用其他括號標記。

單字清單（單字 | 詞性 | 中文意思）：
{words}"""


# ---------------- 【貼上 2】插入的程式碼 ----------------
        _sem, _unit = scope_picker(df_vocab, "exp", "選擇學期/篇章：", "選擇單元/課次：")
        _sub = scoped(df_vocab, _sem, _unit)
        _n1, _n2 = st.columns(2)
        _nb = _n1.number_input("挖空數量", min_value=5, max_value=20, value=10, key="ex_nb")
        _nc = _n2.number_input("文章字數", min_value=80, max_value=400, value=150, step=10, key="ex_nc")
        if _sub.empty:
            st.caption("這個範圍沒有單字。")
        else:
            _lines = list(dict.fromkeys(
                f"{w} | {p} | {d}" for w, p, d in zip(_sub['word'], _sub['part_of_speech'], _sub['definition'])))
            if len(_lines) > 80:
                st.caption(f"目前範圍有 {len(_lines)} 筆，清單偏長，建議選到單一課次。")
            st.caption("點程式碼框右上角複製 → 貼給 AI → 把 AI 的文章貼到下面的「文章」框。")
            st.code(article_prompt_text(selected_level, "\n".join(_lines), _nb, _nc), language=None)
        st.markdown("---")
