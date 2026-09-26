with col_input2:
        st.subheader("📂 Word 檔案智慧匯入")
        uploaded_docxs = st.file_uploader("上傳 Word 講義檔案 (自動查字典與例句)", type=["docx"], accept_multiple_files=True)
        if uploaded_docxs:
            if st.button("📖 批次解析 Word 並匯入", use_container_width=True):
                all_extracted_words = []
                POS_BLACKLIST = {
                    'n', 'v', 'adj', 'adv', 'prep', 'conj', 'pron', 'interj', 'aux', 
                    'n.', 'v.', 'adj.', 'adv.', 'prep.', 'conj.', 'pron.', 'interj.', 'aux.',
                    'v.n.', 'n.v.', 'adj.adv.', 'phr', 'phr.', 'pl', 'pl.', 'sg', 'sg.'
                }
                
                with st.spinner("🔍 正在精準掃描 Word 表格第一欄單字（已自動過濾數字序號與雜訊）..."):
                    for uploaded_docx in uploaded_docxs:
                        temp_path = f"temp_{uploaded_docx.name}"
                        try:
                            with open(temp_path, "wb") as f:
                                f.write(uploaded_docx.getbuffer())
                            doc = docx.Document(temp_path)
                            for table in doc.tables:
                                for row in table.rows:
                                    if row.cells:
                                        cell_text = row.cells[0].text.strip()
                                        for line in cell_text.split('\n'):
                                            cleaned = line.strip().lower()
                                            # 去除結尾的點（例如 "7." 變成 "7"）以方便檢查是否為純數字序號
                                            check_num = cleaned.rstrip('.')
                                            
                                            # 嚴格過濾條件：排除黑名單、空字串、純數字序號、長度限制、中文與特殊符號
                                            if (cleaned and 
                                                cleaned not in POS_BLACKLIST and 
                                                not check_num.isdigit() and 
                                                len(cleaned) < 30 and 
                                                not any(('\u4e00' <= c <= '\u9fff') for c in cleaned) and 
                                                not any(char in cleaned for char in ['/', '[', ']', '(', ')', '=', '：', ':'])):
                                                
                                                original_c = line.strip()
                                                if original_c not in all_extracted_words:
                                                    all_extracted_words.append(original_c)
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                        except Exception:
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                
                total_words_to_process = len(all_extracted_words)
                
                if total_words_to_process > 0:
                    st.info(f"📑 文本精準掃描完畢！共鎖定表格第一欄找到 **{total_words_to_process}** 個有效單字準備匯入。")
                    
                    progress_bar = st.progress(0)
                    status_ui = st.empty()
                    
                    df_current = load_vocab_dataframe(active_worksheet)
                    total_success_count = 0
                    
                    for i, word in enumerate(all_extracted_words):
                        remaining_words = total_words_to_process - (i + 1)
                        
                        status_ui.markdown(
                            f"**⏳ 匯入進度：** `{(i+1)} / {total_words_to_process}`\n\n"
                            f"👉 目前正在處理： **{word}**\n\n"
                            f"🎯 還剩下 **{remaining_words}** 個單字即可完成！"
                        )
                        
                        w_data = get_word_record_data_via_ai(word, level=selected_level)
                        
                        if not df_current.empty and word.lower() in df_current['word'].str.lower().values:
                            idx = df_current.index[df_current['word'].str.lower() == word.lower()].tolist()[0]
                            df_current.at[idx, 'phonetic'] = w_data.get('phonetic', '')
                            df_current.at[idx, 'part_of_speech'] = w_data.get('part_of_speech', '')
                            df_current.at[idx, 'definition'] = simple_s2t_convert(w_data.get('definition', ''))
                            df_current.at[idx, 'basic_sentence'] = w_data.get('basic_sentence', '')
                            if not str(df_current.at[idx, 'unit_tag']).strip():
                                df_current.at[idx, 'unit_tag'] = current_unit_tag
                        else:
                            next_id = len(df_current) + 1
                            new_row = pd.DataFrame([{
                                'id': next_id,
                                'word': word,
                                'phonetic': w_data.get('phonetic', ''),
                                'part_of_speech': w_data.get('part_of_speech', ''),
                                'definition': simple_s2t_convert(w_data.get('definition', '')),
                                'basic_sentence': w_data.get('basic_sentence', ''),
                                'advanced_sentence': '',
                                'collocations': '',
                                'unit_tag': current_unit_tag,
                                'srs_stage': 0
                            }])
                            df_current = pd.concat([df_current, new_row], ignore_index=True)
                            
                        total_success_count += 1
                        progress_bar.progress((i + 1) / total_words_to_process)
                        time.sleep(0.02)
                        
                    status_ui.markdown("🔄 **正在將所有資料同步至 Google Sheets，請稍候...**")
                    save_all_vocab_to_sheet(active_worksheet, df_current)
                    
                    status_ui.success(f"🎊 批次匯入完成！成功解析並匯入 {total_success_count} 個單字。")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.warning("⚠️ 在上傳的 Word 表格第一欄中找不到符合的英文單字。")
