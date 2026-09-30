# 🎨 簡約排版與自動適應亮/暗色主題優化
st.markdown("""
    <style>
    /* 統整卡片容器：將邊框與背景改為中性灰色透明度，確保亮/暗色主題都好看 */
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

    /* 讓表單內的左右欄位垂直置中對齊，按鈕與輸入框保持完美水平線 */
    div[data-testid="stForm"] [data-testid="stHorizontalBlock"] {
        align-items: flex-end !important;
    }

    /* 欄位文字與排版優化 */
    .stDataFrame [data-testid="stTable"] td, .stDataFrame div[data-baseweb="table"] td, div[data-testid="stDataFrame"] div.dvn-scroller td {
        white-space: normal !important;
        word-wrap: break-word !important;
        height: auto !important;
        padding-top: 12px !important;
        padding-bottom: 12px !important;
        font-size: 15px !important;
    }

    /* 側邊欄與輸入框微調 */
    [data-testid="stSidebar"] .stRadio label p {
        font-size: 18px !important;
        font-weight: 500 !important;
    }
    [data-testid="stSidebar"] h5 {
        font-size: 17px !important;
        font-weight: 600;
    }
    .stSelectbox label, .stTextInput label, .stTextArea label, .stRadio label {
        font-size: 16px !important;
        font-weight: 500 !important;
    }

    /* RWD 手機版介面強化：移除強制白色字體，讓系統原生接管顏色 */
    @media (max-width: 768px) {
        [data-testid="stSidebar"] .stRadio label p { font-size: 16px !important; }
        [data-testid="stSidebar"] h5 { font-size: 15px !important; }
    }
    </style>
""", unsafe_allow_html=True)
