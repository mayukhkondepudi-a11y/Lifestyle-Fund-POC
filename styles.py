"""Global CSS for the PickR Streamlit app.

Single source of truth for all app styling. Inject via:
    from styles import APP_CSS
    st.markdown(APP_CSS, unsafe_allow_html=True)
"""

APP_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');

    html, body, .stApp {
        background: linear-gradient(180deg, #0f0f13 0%, #14141a 100%) !important;
        color: rgba(255,255,255,0.92) !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 17px !important;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }
    .block-container {
        padding-top: 0 !important;
        max-width: 1400px !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        background: transparent !important;
    }
    .stApp > div,
    [data-testid="stAppViewContainer"] {
        background: transparent !important;
    }

    [data-testid="stToolbar"],
    [data-testid="stToolbarActions"],
    [data-testid="stToolbarActionButtonContainer"],
    [data-testid="stDecoration"],
    [data-testid="stStatusWidget"],
    [data-testid="stAppDeployButton"],
    button[data-testid="baseButton-header"],
    button[data-testid="baseButton-minimal"],
    #MainMenu, #MainMenu > ul, footer,
    .reportview-container .main footer {
        display:    none       !important;
        visibility: hidden     !important;
        height:     0px        !important;
        max-height: 0px        !important;
        overflow:   hidden     !important;
        padding:    0          !important;
        margin:     0          !important;
    }

    header, .stAppHeader, [data-testid="stHeader"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }

    .params-card { background: #111118; border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 1.2rem 1.5rem; margin-bottom: 1.5rem; }
    .params-row { display: flex; justify-content: space-between; padding: 0.5rem 0; border-bottom: 1px solid rgba(255,255,255,0.04); font-size: 0.9rem; }
    .params-row:last-child { border-bottom: none; }
    .params-key { color: rgba(255,255,255,0.6); font-weight: 500; }
    .params-val { color: rgba(255,255,255,0.95); font-weight: 600; }

    .rpt-card {
        background: #16161e;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        border-top: 1px solid rgba(74,222,128,0.12);
        padding: 2rem 2.5rem;
        margin-top: 1rem;
        animation: fadeInUp 0.4s ease-out;
    }
    .rpt-head h2 { font-size: 2.4rem; font-weight: 800; color: #ffffff; margin: 0; letter-spacing: -0.02em; }
    .rpt-head .meta { color: rgba(255,255,255,0.55); font-size: 0.97rem; letter-spacing: 0.04em; margin-top: 0.4rem; font-weight: 500; }

    .rec-bar {
        display: flex;
        justify-content: center;
        gap: 3.5rem;
        padding: 1.5rem 0;
        border-bottom: 1px solid rgba(255,255,255,0.1);
        margin-bottom: 0.5rem;
        background: linear-gradient(180deg, rgba(255,255,255,0.02) 0%, transparent 100%);
        border-radius: 8px;
        animation: fadeInUp 0.5s ease-out;
        flex-wrap: wrap;
    }
    .rb-item { text-align: center; min-width: 80px; }
    .rb-label { font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.14em; color: rgba(255,255,255,0.72); margin-bottom: 0.3rem; white-space: nowrap; }
    .rb-val { font-size: 1.8rem; font-weight: 800; }
    .rb-val.buy   { color: #4ade80; }
    .rb-val.watch { color: #fbbf24; }
    .rb-val.pass  { color: #f87171; }

    .exec-summary {
        background: linear-gradient(135deg, rgba(35,50,45,0.3) 0%, rgba(25,28,37,1) 100%);
        border-left: 3px solid rgba(74,222,128,0.4);
        border-radius: 0 8px 8px 0;
        padding: 1.4rem 1.8rem;
        margin: 1.2rem 0;
        font-size: 1.05rem;
        line-height: 2;
        color: rgba(255,255,255,0.82);
        font-style: italic;
    }

    .sec {
        font-size: 0.86rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.16em;
        color: rgba(255,255,255,0.85);
        margin: 3rem 0 1.2rem;
        padding-bottom: 0.6rem;
        border-bottom: 2px solid rgba(255,255,255,0.12);
        display: block;
    }

    [data-testid="stMetricLabel"] {
        color: rgba(255,255,255,0.75) !important;
        text-transform: uppercase !important;
        letter-spacing: 0.06em !important;
        font-weight: 700 !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.3rem !important;
        font-weight: 700 !important;
        color: rgba(255,255,255,0.95) !important;
        font-feature-settings: "tnum","ss01" !important;
        letter-spacing: 0.01em !important;
    }
    [data-testid="stMetricDelta"] { display: none !important; }

    .range-bar-container { margin: 0.8rem 0 1.5rem; }
    .range-bar-labels { display: flex; justify-content: space-between; font-size: 0.82rem; color: rgba(255,255,255,0.7); margin-bottom: 0.4rem; font-weight: 600; }
    .range-bar { height: 7px; background: rgba(255,255,255,0.1); border-radius: 4px; position: relative; }
    .range-bar-fill { height: 100%; background: linear-gradient(90deg,#8b1a1a,#e03030); border-radius: 4px; }
    .range-bar-dot { width: 12px; height: 12px; background: #fff; border-radius: 50%; position: absolute; top: -2.5px; transform: translateX(-50%); box-shadow: 0 0 8px rgba(224,48,48,0.8); }

    .prose { color: rgba(255,255,255,0.90); line-height: 1.85; }

    /* Tables wrapped in .pt-wrap for horizontal scroll instead of squashing */
    .pt-wrap { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 6px; margin-bottom: 0.5rem; }
    .pt { width: 100%; border-collapse: collapse; font-size: 0.97rem; min-width: 520px; }
    .pt th {
        text-align: left;
        font-size: 0.67rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        padding: 0.7rem 0.85rem;
        border-bottom: 2px solid rgba(74,222,128,0.25);
        background: linear-gradient(135deg, rgba(100,20,20,0.4) 0%, rgba(25,20,35,0.95) 100%);
        color: rgba(255,255,255,0.85) !important;
        white-space: nowrap;
    }
    .pt td { color: rgba(255,255,255,0.85); padding: 0.6rem 0.85rem; vertical-align: middle; }
    .pt td.nowrap { white-space: nowrap; }
    .pt td:first-child { white-space: nowrap; }
    .pt tr.hl td { font-weight: 700; color: #ffffff; background: rgba(224,48,48,0.12); }
    .pt tbody tr:nth-child(even) td { background: rgba(255,255,255,0.025); }
    .pt tbody tr:nth-child(odd)  td { background: transparent; }
    .pt tbody tr:hover td { background: rgba(255,255,255,0.05); transition: background 0.15s ease; }

    .vtag { display: inline-block; font-size: 0.52rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #e03030; border: 1px solid rgba(224,48,48,0.4); padding: 0.06rem 0.3rem; border-radius: 2px; margin-left: 0.4rem; vertical-align: middle; }

    .div { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 1rem 0; }

    .track-box { background: #16161e; border: 1px solid rgba(224,48,48,0.3); border-radius: 8px; padding: 1.5rem 2rem; margin-top: 1.5rem; }
    .track-box-title { font-size: 0.7rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.16em; color: #e03030; margin-bottom: 0.6rem; }
    .track-success { background: rgba(74,222,128,0.1); border: 1px solid rgba(74,222,128,0.3); border-radius: 6px; padding: 0.8rem 1.2rem; font-size: 0.9rem; color: #4ade80; margin-top: 0.8rem; }
    .track-note { font-size: 0.85rem; color: rgba(255,255,255,0.55); margin-top: 0.6rem; line-height: 1.6; }

    .driver-card { background: #111118; border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 1rem 1.2rem; margin: 0.5rem 0; transition: all 0.2s ease; }
    .driver-card:hover { border-color: rgba(255,255,255,0.12); box-shadow: 0 4px 20px rgba(0,0,0,0.3); }
    .driver-card-name { font-weight: 700; color: #fff; font-size: 0.98rem; margin-bottom: 0.3rem; }
    .driver-card-desc { font-size: 0.92rem; color: rgba(255,255,255,0.70); margin-bottom: 0.8rem; line-height: 1.7; }

    .ev-bar {
        display: flex;
        justify-content: center;
        gap: 2.5rem;
        background: linear-gradient(180deg, rgba(14,14,20,1) 0%, rgba(18,18,26,1) 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 8px;
        padding: 1.2rem 1.5rem;
        margin: 1rem 0;
        flex-wrap: wrap;
        animation: fadeInUp 0.5s ease-out;
    }
    .ev-item { text-align: center; min-width: 90px; }
    .ev-label { font-size: 0.68rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em; color: rgba(255,255,255,0.62); margin-bottom: 0.3rem; white-space: nowrap; }
    .ev-val { font-size: 1.3rem; font-weight: 800; color: #fff; }
    .ev-val.positive { color: #4ade80; }
    .ev-val.negative { color: #f87171; }
    .ev-val.neutral  { color: #fbbf24; }

    .plain-callout { background: rgba(139,26,26,0.14); border-left: 3px solid #8b1a1a; border-radius: 0 6px 6px 0; padding: 1rem 1.4rem; margin: 0.8rem 0; font-size: 0.92rem; color: rgba(255,255,255,0.7); line-height: 1.8; }
    .plain-callout-label { font-size: 0.64rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.14em; color: #d44040; margin-bottom: 0.4rem; }

    .stTextInput > div > div > input {
        background: #0e0e14 !important;
        border: 1px solid rgba(255,255,255,0.18) !important;
        border-radius: 6px !important;
        color: #fff !important;
        font-size: 1rem !important;
        font-family: 'Inter', sans-serif !important;
        padding: 0.6rem 1rem !important;
        caret-color: #fff !important;
    }
    .stTextInput > div > div > input:focus { border-color: #8b1a1a !important; box-shadow: 0 0 0 2px rgba(139,26,26,0.2) !important; }
    .stTextInput > div > div > input::placeholder { color: rgba(255,255,255,0.4) !important; }
    .stSelectbox > div > div { background: #0e0e14 !important; border: 1px solid rgba(255,255,255,0.12) !important; border-radius: 6px !important; color: #fff !important; font-family: 'Inter', sans-serif !important; }
    .stSelectbox > div > div > div { color: #fff !important; font-family: 'Inter', sans-serif !important; }
    .stSelectbox svg { fill: rgba(255,255,255,0.5) !important; }
    [data-baseweb="select"] *, [data-baseweb="menu"] *, [role="option"] { font-family: 'Inter', sans-serif !important; }
    .stNumberInput > div > div > input { background: #0e0e14 !important; border: 1px solid rgba(255,255,255,0.12) !important; border-radius: 6px !important; color: #fff !important; font-family: 'Inter', sans-serif !important; }

    [data-testid="stStatusWidget"], .stAlert, .stStatus { background: #12121a !important; border: 1px solid rgba(255,255,255,0.08) !important; color: #e8e8e8 !important; border-radius: 6px !important; }
    [data-testid="stStatusWidget"] p, [data-testid="stStatusWidget"] span, [data-testid="stStatusWidget"] div { color: #e8e8e8 !important; }
    .stWarning, .stError, .stInfo { background: #0e0e14 !important; color: #e8e8e8 !important; }

    .stButton > button,
    [data-testid="stBaseButton-primary"],
    [data-testid="stBaseButton-secondary"],
    [data-testid="stDownloadButton"] > button {
        font-family: 'Inter', sans-serif !important;
        font-size: 0.9rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.04em !important;
        border-radius: 8px !important;
        padding: 0.58rem 1.4rem !important;
        min-height: 38px !important;
        cursor: pointer !important;
        transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1) !important;
        position: relative !important;
        overflow: hidden !important;
        white-space: nowrap !important;
    }

    .stButton > button::before,
    [data-testid="stDownloadButton"] > button::before {
        content: '' !important;
        position: absolute !important;
        top: 0 !important; left: -100% !important;
        width: 60% !important; height: 100% !important;
        background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.07) 50%, transparent 100%) !important;
        transition: left 0.55s ease !important;
        pointer-events: none !important;
    }
    .stButton > button:hover::before,
    [data-testid="stDownloadButton"] > button:hover::before {
        left: 160% !important;
    }

    .stButton > button[kind="primary"],
    [data-testid="stBaseButton-primary"] {
        background: linear-gradient(145deg, #7a1515 0%, #b02828 55%, #c93535 100%) !important;
        border: 1px solid rgba(180,40,40,0.55) !important;
        color: #fff !important;
        text-shadow: 0 1px 3px rgba(0,0,0,0.35) !important;
        box-shadow: 0 2px 8px rgba(139,26,26,0.45), 0 1px 2px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.10) !important;
    }
    .stButton > button[kind="primary"]:hover,
    [data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(145deg, #921a1a 0%, #cc2e2e 55%, #e03a3a 100%) !important;
        border-color: rgba(210,55,55,0.65) !important;
        box-shadow: 0 4px 18px rgba(160,30,30,0.55), 0 2px 4px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.12) !important;
        transform: translateY(-1px) !important;
        color: #fff !important;
    }
    .stButton > button[kind="primary"]:active,
    [data-testid="stBaseButton-primary"]:active {
        transform: translateY(0) scale(0.98) !important;
        box-shadow: 0 1px 4px rgba(139,26,26,0.4), inset 0 1px 3px rgba(0,0,0,0.2) !important;
    }
    .stButton > button[kind="primary"]:disabled,
    [data-testid="stBaseButton-primary"]:disabled {
        background: rgba(120,20,20,0.35) !important;
        border-color: rgba(140,30,30,0.25) !important;
        color: rgba(255,255,255,0.4) !important;
        box-shadow: none !important;
        cursor: not-allowed !important;
        transform: none !important;
        text-shadow: none !important;
    }

    .stButton > button[kind="secondary"],
    [data-testid="stBaseButton-secondary"],
    .stButton > button:not([kind]) {
        background: rgba(255,255,255,0.05) !important;
        border: 1px solid rgba(255,255,255,0.14) !important;
        color: rgba(255,255,255,0.78) !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.04) !important;
    }
    .stButton > button[kind="secondary"]:hover,
    [data-testid="stBaseButton-secondary"]:hover,
    .stButton > button:not([kind]):hover {
        background: rgba(255,255,255,0.09) !important;
        border-color: rgba(255,255,255,0.26) !important;
        color: #fff !important;
        box-shadow: 0 3px 10px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.06) !important;
        transform: translateY(-1px) !important;
    }
    .stButton > button[kind="secondary"]:active,
    [data-testid="stBaseButton-secondary"]:active {
        transform: translateY(0) scale(0.98) !important;
        background: rgba(255,255,255,0.07) !important;
        box-shadow: inset 0 1px 3px rgba(0,0,0,0.2) !important;
    }

    [data-testid="stDownloadButton"] > button {
        background: rgba(45,55,72,0.55) !important;
        border: 1px solid rgba(100,130,160,0.28) !important;
        color: rgba(180,210,240,0.88) !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.04) !important;
    }
    [data-testid="stDownloadButton"] > button:hover {
        background: rgba(55,70,95,0.70) !important;
        border-color: rgba(120,160,200,0.40) !important;
        color: rgba(210,230,255,0.95) !important;
        box-shadow: 0 3px 12px rgba(30,60,100,0.35), inset 0 1px 0 rgba(255,255,255,0.06) !important;
        transform: translateY(-1px) !important;
    }

    [data-testid="stVegaLiteChart"] { background: rgba(255,255,255,0.02) !important; border: 1px solid rgba(255,255,255,0.04) !important; border-radius: 6px !important; }

    .stTabs [data-baseweb="tab-list"] { background: transparent !important; gap: 0 !important; border-bottom: 1px solid rgba(255,255,255,0.06) !important; }
    .stTabs [data-baseweb="tab"] { color: rgba(255,255,255,0.45) !important; font-size: 0.82rem !important; font-weight: 600 !important; padding: 0.6rem 1.2rem !important; border-bottom: 2px solid transparent !important; transition: all 0.2s ease !important; white-space: nowrap !important; }
    .stTabs [data-baseweb="tab"]:hover { color: rgba(255,255,255,0.7) !important; }
    .stTabs [aria-selected="true"] { color: #fff !important; border-bottom-color: #e03030 !important; }
    .stTabs [data-baseweb="tab-panel"] { padding-top: 1rem !important; }

    @keyframes fadeInUp { from { opacity:0; transform:translateY(20px); } to { opacity:1; transform:translateY(0); } }

    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #080810; }
    ::-webkit-scrollbar-thumb { background: #2a2a35; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #44445a; }

    @media (max-width: 768px) {
        .block-container { padding-left: 0.8rem !important; padding-right: 0.8rem !important; }
        .rpt-card { padding: 1.2rem 1rem !important; }
        .rec-bar { gap: 1.2rem !important; flex-wrap: wrap !important; padding: 1rem 0.5rem !important; }
        .rb-val  { font-size: 1.2rem !important; }
        .rb-label { font-size: 0.58rem !important; }
        .ev-bar  { gap: 1.2rem !important; flex-wrap: wrap !important; padding: 1rem !important; }
        .ev-val  { font-size: 1rem !important; }
        .pt-wrap { border-radius: 4px; }
        .pt { font-size: 0.78rem !important; }
        .pt th { font-size: 0.55rem !important; padding: 0.5rem 0.5rem !important; }
        .pt td { padding: 0.5rem 0.5rem !important; }
        .prose { font-size: 0.9rem !important; }
        .exec-summary { padding: 1rem !important; font-size: 0.9rem !important; }
        .rpt-head h2 { font-size: 1.6rem !important; }
        .rpt-head .meta { font-size: 0.72rem !important; }
        div[style*="grid-template-columns:1fr 1fr"] { grid-template-columns: 1fr !important; }
    }
    @media (max-width: 480px) {
        .rb-val  { font-size: 1rem !important; }
        .ev-val  { font-size: 0.9rem !important; }
        .rpt-head h2 { font-size: 1.3rem !important; }
    }

    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stSidebarCollapseButton"],
    [data-testid="collapsedControl"],
    button[aria-label="Open sidebar"],
    button[aria-label="Close sidebar"] {
        display: none !important;
        width: 0 !important;
        min-width: 0 !important;
        max-width: 0 !important;
        overflow: hidden !important;
    }

    /* Picks table */
    .picks-table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
    .picks-table th { text-align: left; font-size: 0.67rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.08em; padding: 0.55rem 0.7rem; border-bottom: 2px solid rgba(255,255,255,0.08); color: rgba(255,255,255,0.4) !important; white-space: nowrap; }
    .picks-table th.right { text-align: center; }
    .picks-table td { padding: 0.65rem 0.7rem; vertical-align: middle; }
    .picks-table td.right { text-align: center; }
    .picks-table tbody tr { border-bottom: 1px solid rgba(255,255,255,0.045); transition: background 0.12s; }
    .picks-table tbody tr:hover td { background: rgba(255,255,255,0.03); }
    .picks-table .co-name { font-size: 0.78rem; color: rgba(255,255,255,0.4); overflow: hidden; text-overflow: ellipsis; max-width: 160px; display: inline-block; vertical-align: middle; white-space: nowrap; }

    /* Sign-out button */
    .pickr-signout-col .stButton > button {
        background: transparent !important;
        border: 1px solid rgba(255,255,255,0.10) !important;
        color: rgba(255,255,255,0.45) !important;
        font-size: 0.72rem !important;
        font-weight: 600 !important;
        padding: 0.3rem 0.7rem !important;
        min-height: 28px !important;
        border-radius: 5px !important;
        box-shadow: none !important;
        transform: none !important;
        text-shadow: none !important;
    }
    .pickr-signout-col .stButton > button:hover {
        border-color: rgba(192,48,48,0.4) !important;
        color: rgba(255,100,100,0.9) !important;
        background: rgba(139,26,26,0.10) !important;
        transform: none !important;
        box-shadow: none !important;
    }
    .pickr-signout-col .stButton > button::before { display: none !important; }

    /* History buttons */
    .pickr-history-btn .stButton > button {
        font-size: 0.68rem !important;
        font-weight: 700 !important;
        padding: 0.2rem 0.5rem !important;
        min-height: 24px !important;
        border-radius: 4px !important;
        background: rgba(255,255,255,0.04) !important;
        border: 1px solid rgba(255,255,255,0.09) !important;
        color: rgba(255,255,255,0.55) !important;
        box-shadow: none !important;
        transform: none !important;
        text-shadow: none !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
    }
    .pickr-history-btn .stButton > button:hover {
        background: rgba(139,26,26,0.18) !important;
        border-color: rgba(192,48,48,0.4) !important;
        color: #fff !important;
        transform: none !important;
        box-shadow: none !important;
    }
    .pickr-history-btn .stButton > button::before { display: none !important; }
</style>
"""
