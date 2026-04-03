import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
from openai import OpenAI
import os
import json
import base64
from datetime import datetime
import urllib.request
import urllib.parse

st.set_page_config(page_title="PickR", page_icon="P", layout="wide")

if "report_count" not in st.session_state:
    st.session_state.report_count = 147
if "recent" not in st.session_state:
    st.session_state.recent = []
if "cached_report" not in st.session_state:
    st.session_state.cached_report = None
if "cached_html" not in st.session_state:
    st.session_state.cached_html = None
if "trigger_ticker" not in st.session_state:
    st.session_state.trigger_ticker = None
if "generate_html" not in st.session_state:
    st.session_state.generate_html = False
if "html_just_generated" not in st.session_state:
    st.session_state.html_just_generated = False

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
    html, body, .stApp { background:#0c0c0c !important; color:#e8e8e8 !important; font-family:'Inter',sans-serif !important; font-size:16px !important; }
    .block-container { padding-top:0 !important; max-width:1200px !important; }
    .stApp > div, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stToolbar"] { background:#0c0c0c !important; }
    #MainMenu, footer, header { visibility:hidden !important; }

    .hero { padding:4rem 2rem 1.5rem; text-align:center; }
    .hero h1 { font-size:4.2rem; font-weight:900; color:#fff; letter-spacing:-0.03em; margin:0; }
    .hero h1 .accent {
        background: linear-gradient(135deg, #a52525 0%, #e04040 30%, #ff8a8a 50%, #e04040 70%, #a52525 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        filter: drop-shadow(0 0 8px rgba(200,50,50,0.3));
    }
    .hero .tag { font-size:1.1rem; color:rgba(255,255,255,0.4); margin-top:0.3rem; }
    .hero .desc { font-size:1rem; color:rgba(255,255,255,0.35); max-width:620px; margin:1rem auto 0; line-height:1.7; }

    .stats-row { display:flex; justify-content:center; gap:3rem; padding:1.3rem 0; margin-top:1.5rem;
        border-top:1px solid rgba(255,255,255,0.05); border-bottom:1px solid rgba(255,255,255,0.05); }
    .sr-item { text-align:center; }
    .sr-num { font-size:1.6rem; font-weight:800; color:#fff; display:block; }
    .sr-lbl { font-size:0.65rem; color:rgba(255,255,255,0.22); text-transform:uppercase; letter-spacing:0.14em; font-weight:600; }

    .hiw { padding:2rem 0 1rem; }
    .hiw-title { text-align:center; font-size:0.7rem; font-weight:700; text-transform:uppercase;
        letter-spacing:0.18em; color:rgba(255,255,255,0.18); margin-bottom:1.2rem; }
    .hiw-grid { display:flex; justify-content:center; gap:1.5rem; }
    .hiw-card { background:#141414; border:1px solid rgba(255,255,255,0.05); border-radius:8px;
        padding:1.3rem; text-align:center; flex:1; max-width:260px; }
    .hiw-step { font-size:0.6rem; font-weight:800; color:#8b1a1a; text-transform:uppercase;
        letter-spacing:0.16em; margin-bottom:0.4rem; }
    .hiw-title2 { font-size:1.1rem; font-weight:700; color:#fff; margin-bottom:0.3rem; }
    .hiw-desc { font-size:0.88rem; color:rgba(255,255,255,0.35); line-height:1.55; }

    .thesis-section { background:#141414; border:1px solid rgba(255,255,255,0.05); border-radius:8px;
        padding:2rem; margin:1.5rem 0; }
    .thesis-title { font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.16em;
        color:rgba(255,255,255,0.2); margin-bottom:1rem; }
    .thesis-grid { display:grid; grid-template-columns:1fr 1fr; gap:1.2rem; }
    .thesis-card { background:#1a1a1a; border-radius:6px; padding:1rem 1.2rem; }
    .thesis-card-letter { font-size:1.4rem; font-weight:800; color:#8b1a1a; margin-bottom:0.2rem; }
    .thesis-card-name { font-size:0.95rem; font-weight:700; color:#e0e0e0; margin-bottom:0.3rem; }
    .thesis-card-desc { font-size:0.88rem; color:rgba(255,255,255,0.4); line-height:1.55; }
    .thesis-scoring { margin-top:1.2rem; padding-top:1rem; border-top:1px solid rgba(255,255,255,0.05); }
    .thesis-scoring-title { font-size:0.72rem; font-weight:700; color:rgba(255,255,255,0.3); margin-bottom:0.6rem; }
    .scoring-row { display:flex; gap:1.5rem; }
    .scoring-item { text-align:center; flex:1; }
    .scoring-range { font-size:1.15rem; font-weight:700; }
    .scoring-range.buy { color:#22c55e; }
    .scoring-range.watch { color:#f5c542; }
    .scoring-range.pass { color:#ff4d4d; }
    .scoring-label { font-size:0.62rem; color:rgba(255,255,255,0.3); text-transform:uppercase; letter-spacing:0.1em; font-weight:600; }

    .params-card { background:#141414; border:1px solid rgba(255,255,255,0.05); border-radius:8px;
        padding:1.2rem 1.5rem; margin-bottom:1.5rem; }
    .params-row { display:flex; justify-content:space-between; padding:0.5rem 0;
        border-bottom:1px solid rgba(255,255,255,0.03); font-size:0.9rem; }
    .params-row:last-child { border-bottom:none; }
    .params-key { color:rgba(255,255,255,0.35); }
    .params-val { color:rgba(255,255,255,0.7); font-weight:500; }

    .rpt-card { background:#151515; border:1px solid #222; border-radius:10px; padding:2rem 2.5rem; margin-top:1rem; }
    .rpt-head h2 { font-size:2.4rem; font-weight:800; color:#fff; margin:0; letter-spacing:-0.02em; }
    .rpt-head .meta { color:rgba(255,255,255,0.3); font-size:0.85rem; letter-spacing:0.05em; margin-top:0.3rem; }

    .rec-bar { display:flex; justify-content:center; gap:3.5rem; padding:1.5rem 0;
        border-bottom:1px solid rgba(255,255,255,0.05); margin-bottom:0.5rem; }
    .rb-item { text-align:center; }
    .rb-label { font-size:0.62rem; font-weight:700; text-transform:uppercase; letter-spacing:0.16em;
        color:rgba(255,255,255,0.22); margin-bottom:0.2rem; }
    .rb-val { font-size:1.6rem; font-weight:800; }
    .rb-val.buy { color:#22c55e; }
    .rb-val.watch { color:#f5c542; }
    .rb-val.pass { color:#ff4d4d; }

    .exec-summary { background:#1a1a1a; border-left:3px solid #8b1a1a; border-radius:0 6px 6px 0;
        padding:1.1rem 1.4rem; margin:1rem 0; font-size:1rem; line-height:1.75; color:rgba(255,255,255,0.6);
        font-style:italic; }

    .rationale-text { text-align:center; font-size:0.95rem; color:rgba(255,255,255,0.38);
        font-style:italic; max-width:650px; margin:0 auto; padding-bottom:1.5rem; line-height:1.7; }

    .sec { font-size:0.85rem; font-weight:700; text-transform:uppercase; letter-spacing:0.14em;
        color:#e0e0e0; margin:1.8rem 0 0.7rem; padding-bottom:0.4rem;
        border-bottom:2px solid #8b1a1a; }

    [data-testid="stMetricLabel"] { font-size:0.72rem !important; color:rgba(255,255,255,0.28) !important;
        text-transform:uppercase !important; letter-spacing:0.04em !important; font-weight:600 !important; }
    [data-testid="stMetricValue"] { font-size:1.2rem !important; font-weight:600 !important; color:#fff !important; }
    [data-testid="stMetricDelta"] { display:none !important; }

    .range-bar-container { margin:0.8rem 0 1.5rem; }
    .range-bar-labels { display:flex; justify-content:space-between; font-size:0.75rem; color:rgba(255,255,255,0.3); margin-bottom:0.3rem; }
    .range-bar { height:6px; background:rgba(255,255,255,0.06); border-radius:3px; position:relative; }
    .range-bar-fill { height:100%; background:linear-gradient(90deg, #8b1a1a, #c03030); border-radius:3px; }
    .range-bar-dot { width:10px; height:10px; background:#fff; border-radius:50%; position:absolute;
        top:-2px; transform:translateX(-50%); box-shadow:0 0 6px rgba(139,26,26,0.5); }

    .qglp-s { background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05);
        border-radius:8px; padding:1.3rem 1.5rem; margin:0.8rem 0; }
    .qg { display:flex; justify-content:space-between; }
    .qc { flex:1; text-align:center; padding:0.5rem 0; }
    .qc .ql { font-size:0.62rem; font-weight:700; text-transform:uppercase; letter-spacing:0.12em;
        color:rgba(255,255,255,0.22); margin-bottom:0.2rem; }
    .qc .qs { font-size:2rem; font-weight:800; color:#fff; }
    .qc .qsub { font-size:0.55rem; color:rgba(255,255,255,0.12); }
    .qc.comp { border-left:1px solid rgba(255,255,255,0.05); }
    .qc.comp .qs { color:#8b1a1a; }

    .prose { font-size:1rem; line-height:1.85; color:#b8b8b8; padding:0.2rem 0 0.6rem; }

    .risk-row { padding:0.6rem 0; border-bottom:1px solid rgba(255,255,255,0.04);
        font-size:0.95rem; line-height:1.65; color:#b8b8b8; }
    .risk-row:last-child { border-bottom:none; }
    .rn { display:inline-block; width:22px; height:22px; line-height:22px; text-align:center;
        background:rgba(139,26,26,0.15); border-radius:3px; color:#8b1a1a; font-weight:700;
        font-size:0.7rem; margin-right:0.6rem; vertical-align:middle; }

    .cb { padding:1.2rem 1.4rem; border-radius:6px; font-size:0.95rem; line-height:1.7; color:#b8b8b8; }
    .cb-bull { background:rgba(34,197,94,0.06); border:1px solid rgba(34,197,94,0.15); }
    .cb-bear { background:rgba(255,77,77,0.06); border:1px solid rgba(255,77,77,0.12); }
    .cb-title { font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.12em; margin-bottom:0.4rem; }
    .cb-bull .cb-title { color:#22c55e; }
    .cb-bear .cb-title { color:#ff4d4d; }

    .sz-box { background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05);
        padding:1rem 1.4rem; border-radius:6px; font-size:0.95rem; line-height:1.7; color:#b8b8b8; }

    .pt { width:100%; border-collapse:collapse; font-size:0.88rem; }
    .pt th { text-align:left; font-size:0.62rem; font-weight:700; text-transform:uppercase;
        letter-spacing:0.07em; color:rgba(255,255,255,0.28); padding:0.55rem 0.7rem;
        border-bottom:1px solid rgba(255,255,255,0.06); }
    .pt td { padding:0.5rem 0.7rem; border-bottom:1px solid rgba(255,255,255,0.03); color:#b8b8b8; }
    .pt tr.hl td { font-weight:600; color:#fff; background:rgba(139,26,26,0.06); }

    .vtag { display:inline-block; font-size:0.52rem; font-weight:700; text-transform:uppercase;
        letter-spacing:0.08em; color:#8b1a1a; border:1px solid rgba(139,26,26,0.3);
        padding:0.06rem 0.3rem; border-radius:2px; margin-left:0.4rem; vertical-align:middle; }

    .tooltip { position:relative; cursor:help; border-bottom:1px dotted rgba(255,255,255,0.2); }
    .tooltip .tiptext { visibility:hidden; background:#1a1a1a; color:#b8b8b8; font-size:0.82rem;
        padding:0.5rem 0.7rem; border-radius:4px; border:1px solid rgba(255,255,255,0.08);
        position:absolute; z-index:10; bottom:125%; left:50%; transform:translateX(-50%);
        width:220px; text-align:center; line-height:1.4; font-weight:400; font-style:normal; }
    .tooltip:hover .tiptext { visibility:visible; }

    .div { border:none; border-top:1px solid rgba(255,255,255,0.04); margin:0.8rem 0; }
    .foot-card { background:#141414; border:1px solid rgba(255,255,255,0.05); border-radius:8px;
        padding:1.5rem 2rem; margin-top:2rem; text-align:center; }
    .foot-name { font-size:1rem; font-weight:600; color:rgba(255,255,255,0.6); }
    .foot-email { font-size:0.85rem; color:rgba(255,255,255,0.3); margin-top:0.2rem; }
    .foot-disclaimer { font-size:0.78rem; color:rgba(255,255,255,0.2); margin-top:1rem;
        line-height:1.55; max-width:700px; margin-left:auto; margin-right:auto; }
    .foot-copy { font-size:0.68rem; color:rgba(255,255,255,0.12); margin-top:0.8rem; }

    .stTextInput > div > div > input { background:#1a1a1a !important; border:1px solid rgba(255,255,255,0.1) !important;
        border-radius:6px !important; color:#fff !important; font-size:1rem !important;
        padding:0.6rem 1rem !important; caret-color:#fff !important; }
    .stTextInput > div > div > input:focus { border-color:#8b1a1a !important; box-shadow:0 0 0 2px rgba(139,26,26,0.15) !important; }
    .stTextInput > div > div > input::placeholder { color:rgba(255,255,255,0.25) !important; }
    .stSelectbox > div > div { background:#1a1a1a !important; border:1px solid rgba(255,255,255,0.1) !important;
        border-radius:6px !important; color:#fff !important; }
    .stSelectbox > div > div > div { color:#fff !important; }
    .stSelectbox svg { fill:rgba(255,255,255,0.4) !important; }
    [data-testid="stStatusWidget"], .stAlert, .stStatus { background:#141414 !important;
        border:1px solid rgba(255,255,255,0.06) !important; color:#e8e8e8 !important; border-radius:6px !important; }
    [data-testid="stStatusWidget"] p, [data-testid="stStatusWidget"] span,
    [data-testid="stStatusWidget"] div { color:#e8e8e8 !important; }

    .stButton > button { background:linear-gradient(160deg,#7a1818,#a52525 30%,#c03030 50%,#a52525 70%,#7a1818) !important;
        color:#fff !important; border:none !important; border-radius:6px !important; font-size:0.9rem !important;
        font-weight:700 !important; letter-spacing:0.08em !important; text-transform:uppercase !important;
        padding:0.7rem 2rem !important; transition:all 0.2s ease !important;
        box-shadow:0 2px 8px rgba(139,26,26,0.2), inset 0 1px 0 rgba(255,255,255,0.1) !important; }
    .stButton > button:hover { background:linear-gradient(160deg,#8b1a1a,#c03030 30%,#d44040 50%,#c03030 70%,#8b1a1a) !important;
        transform:translateY(-1px) !important; box-shadow:0 6px 20px rgba(139,26,26,0.4), inset 0 1px 0 rgba(255,255,255,0.15) !important; }
    .stDownloadButton > button { background:transparent !important; color:rgba(255,255,255,0.5) !important;
        border:1px solid rgba(139,26,26,0.35) !important; border-radius:6px !important;
        font-size:0.78rem !important; font-weight:600 !important; letter-spacing:0.08em !important;
        text-transform:uppercase !important; box-shadow:none !important; }
    .stDownloadButton > button:hover { border-color:#8b1a1a !important; color:#fff !important; box-shadow:none !important; }

    .stTabs [data-baseweb="tab-list"] { gap:0; background:#141414; border-radius:6px; padding:3px;
        border:1px solid rgba(255,255,255,0.05); }
    .stTabs [data-baseweb="tab"] { font-size:0.85rem !important; font-weight:500 !important;
        color:rgba(255,255,255,0.35) !important; border-radius:4px !important;
        padding:0.4rem 1rem !important; background:transparent !important; }
    .stTabs [aria-selected="true"] { background:linear-gradient(160deg,#7a1818,#a52525 40%,#b52d2d 60%,#7a1818) !important;
        color:#fff !important; font-weight:600 !important;
        box-shadow:inset 0 1px 0 rgba(255,255,255,0.1) !important; }
    .stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display:none !important; }
    [data-testid="stVegaLiteChart"] { background:rgba(255,255,255,0.02) !important;
        border:1px solid rgba(255,255,255,0.04) !important; border-radius:6px !important; }
    .stWarning, .stError, .stInfo { background:#1a1a1a !important; color:#e8e8e8 !important; }
</style>
""", unsafe_allow_html=True)

OPENROUTER_API_KEY = st.secrets.get("OPENROUTER_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
if not OPENROUTER_API_KEY or "your" in OPENROUTER_API_KEY:
    st.error("Add your OpenRouter API key to .streamlit/secrets.toml"); st.stop()

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
FREE_MODELS = [
    "z-ai/glm-4.5-air:free", "nvidia/nemotron-3-super-120b-a12b:free",
    "meta-llama/llama-3.3-70b-instruct:free", "nousresearch/hermes-3-llama-3.1-405b:free",
    "mistralai/mistral-small-3.1-24b-instruct:free", "openai/gpt-oss-120b:free",
    "qwen/qwen3-coder:free", "google/gemma-3-27b-it:free",
]

@st.cache_data
def load_text_file(fp):
    try:
        with open(fp, "r", encoding="utf-8") as f: return f.read()
    except FileNotFoundError: return ""

FUND_THESIS = load_text_file("fund_thesis.md")
REPORT_PROMPT = load_text_file("report_prompt.txt")

POPULAR = {
    "":"", "Apple (AAPL)":"AAPL", "Microsoft (MSFT)":"MSFT", "Nvidia (NVDA)":"NVDA",
    "Broadcom (AVGO)":"AVGO", "Alphabet (GOOGL)":"GOOGL", "Amazon (AMZN)":"AMZN",
    "Meta (META)":"META", "Tesla (TSLA)":"TSLA", "Netflix (NFLX)":"NFLX",
    "AMD (AMD)":"AMD", "ASML (ASML)":"ASML", "Visa (V)":"V", "Mastercard (MA)":"MA",
    "Costco (COST)":"COST", "Adobe (ADBE)":"ADBE", "Salesforce (CRM)":"CRM",
    "Taiwan Semi (TSM)":"TSM", "Reliance (RELIANCE.NS)":"RELIANCE.NS",
    "HDFC Bank (HDFCBANK.NS)":"HDFCBANK.NS", "TCS (TCS.NS)":"TCS.NS", "Infosys (INFY.NS)":"INFY.NS",
}
SECTOR_PEERS = {
    "Technology":["AAPL","MSFT","GOOGL","META","NVDA","AVGO","ADBE","CRM","AMD","INTC","TSM","ASML","ORCL","NOW"],
    "Communication Services":["GOOGL","META","NFLX","DIS","CMCSA","TMUS"],
    "Consumer Cyclical":["AMZN","TSLA","HD","MCD","NKE","SBUX","BKNG"],
    "Consumer Defensive":["COST","WMT","PG","KO","PEP","CL"],
    "Financial Services":["V","MA","JPM","BAC","GS","BLK","AXP","SPGI"],
    "Healthcare":["UNH","JNJ","LLY","ABBV","MRK","TMO","ABT","ISRG"],
    "Industrials":["CAT","HON","UNP","RTX","DE","LMT","GE"],
    "Energy":["XOM","CVX","COP","SLB","EOG"],
}
CURRENCY_SYMBOLS = {
    "USD":"$","INR":"₹","EUR":"€","GBP":"£","JPY":"¥","CNY":"¥","KRW":"₩",
    "HKD":"HK$","SGD":"S$","AUD":"A$","CAD":"C$","BRL":"R$","TWD":"NT$","PKR":"₨",
}
def get_sym(c):
    if not c or c=="N/A": return "$"
    return CURRENCY_SYMBOLS.get(c, f"{c} ")
def fmt_n(v,p="",s="",d=2):
    if v is None or v=="N/A" or v=="": return "-"
    try:
        n=float(v)
        if abs(n)>=1e12: return f"{p}{n/1e12:.{d}f}T{s}"
        if abs(n)>=1e9: return f"{p}{n/1e9:.{d}f}B{s}"
        if abs(n)>=1e6: return f"{p}{n/1e6:.{d}f}M{s}"
        if abs(n)>=1e3: return f"{p}{n/1e3:.{d}f}K{s}"
        return f"{p}{n:.{d}f}{s}"
    except: return "-"
def fmt_p(v,d=1):
    if v is None or v=="N/A" or v=="": return "-"
    try:
        n=float(v); return f"{n*100:.{d}f}%" if abs(n)<1 else f"{n:.{d}f}%"
    except: return "-"
def fmt_r(v,d=2):
    if v is None or v=="N/A" or v=="": return "-"
    try: return f"{float(v):.{d}f}"
    except: return "-"
def fmt_c(v,cur="USD",d=2): return fmt_n(v,p=get_sym(cur),d=d)


@st.cache_data(ttl=86400, show_spinner=False)
def search_ticker(query):
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(query)}&quotesCount=6&newsCount=0"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return [{"symbol":q["symbol"],"name":q.get("shortname",q["symbol"]),"exchange":q.get("exchange","")}
                    for q in data.get("quotes",[]) if q.get("quoteType") in ("EQUITY","ETF")]
    except: return []


@st.cache_data(ttl=3600, show_spinner=False)
def fetch(ticker):
    s = yf.Ticker(ticker)
    d = {}
    try: d["info"] = s.info
    except Exception as e: d["info"] = {"error": str(e)}
    for attr, key in [("income_stmt","inc"),("quarterly_income_stmt","qinc"),("balance_sheet","bs"),("cashflow","cf")]:
        try:
            df = getattr(s, attr)
            d[key] = df if df is not None and not df.empty else None
        except: d[key] = None
    try:
        h = s.history(period="5y", interval="1wk")
        d["hist"] = h if h is not None and not h.empty else None
    except: d["hist"] = None
    try: d["news"] = s.news[:8] if s.news else []
    except: d["news"] = []
    return d

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_peers(ticker, sector):
    pl = [p for p in SECTOR_PEERS.get(sector,[]) if p.upper()!=ticker.upper()][:4]
    out = []
    for pt in pl:
        try:
            i = yf.Ticker(pt).info; c = i.get("currency","USD")
            out.append({"Ticker":pt,"Company":i.get("shortName",pt),"Mkt Cap":fmt_c(i.get("marketCap"),c),
                "P/E":fmt_r(i.get("trailingPE")),"Fwd P/E":fmt_r(i.get("forwardPE")),
                "PEG":fmt_r(i.get("pegRatio")),"Margin":fmt_p(i.get("operatingMargins")),
                "ROE":fmt_p(i.get("returnOnEquity")),"Rev Gr.":fmt_p(i.get("revenueGrowth"))})
        except: continue
    return out


def calc(data):
    info = data.get("info",{})
    if isinstance(info,dict) and "error" in info: return {"error":info["error"]}
    g = lambda k,d=None: info.get(k,d)
    m = {
        "company_name":g("shortName",g("longName","Unknown")),
        "sector":g("sector","N/A"),"industry":g("industry","N/A"),
        "country":g("country","N/A"),"currency":g("currency","USD"),
        "description":g("longBusinessSummary","N/A"),
        "current_price":g("currentPrice",g("regularMarketPrice")),
        "market_cap":g("marketCap"),"enterprise_value":g("enterpriseValue"),
        "trailing_pe":g("trailingPE"),"forward_pe":g("forwardPE"),
        "peg_ratio":g("pegRatio"),"price_to_book":g("priceToBook"),
        "price_to_sales":g("priceToSalesTrailing12Months"),
        "ev_to_ebitda":g("enterpriseToEbitda"),
        "gross_margin":g("grossMargins"),"operating_margin":g("operatingMargins"),
        "profit_margin":g("profitMargins"),"roe":g("returnOnEquity"),"roa":g("returnOnAssets"),
        "trailing_eps":g("trailingEps"),"forward_eps":g("forwardEps"),
        "earnings_growth":g("earningsGrowth"),
        "total_revenue":g("totalRevenue"),"revenue_growth":g("revenueGrowth"),
        "free_cashflow":g("freeCashflow"),"operating_cashflow":g("operatingCashflow"),
        "total_cash":g("totalCash"),"total_debt":g("totalDebt"),
        "debt_to_equity":g("debtToEquity"),"current_ratio":g("currentRatio"),
        "dividend_yield":g("dividendYield"),"payout_ratio":g("payoutRatio"),
        "beta":g("beta"),"week_52_high":g("fiftyTwoWeekHigh"),"week_52_low":g("fiftyTwoWeekLow"),
        "ma_50":g("fiftyDayAverage"),"ma_200":g("twoHundredDayAverage"),
        "insider_pct":g("heldPercentInsiders"),"institution_pct":g("heldPercentInstitutions"),
        "shares_outstanding":g("sharesOutstanding"),
    }
    try: m["fcf_yield"]=float(m["free_cashflow"])/float(m["market_cap"]) if m["free_cashflow"] and m["market_cap"] else None
    except: m["fcf_yield"]=None

    inc=data.get("inc"); m["revenue_history"]={}; m["net_income_history"]={}
    def cagr_from(df,labels):
        if df is None: return None,{}
        for lb in labels:
            if lb in df.index:
                row=df.loc[lb].dropna().sort_index()
                if len(row)>=2:
                    n,o,y=float(row.iloc[-1]),float(row.iloc[0]),len(row)-1
                    hist={str(d.year):round(float(v)/1e9,2) for d,v in row.items()}
                    return ((n/o)**(1/y)-1 if o>0 and y>0 else None),hist
        return None,{}
    m["revenue_cagr"],m["revenue_history"]=cagr_from(inc,["Total Revenue","TotalRevenue"])
    m["net_income_cagr"],m["net_income_history"]=cagr_from(inc,["Net Income","NetIncome"])
    m["eps_cagr"],_=cagr_from(inc,["Basic EPS","Diluted EPS","BasicEPS","DilutedEPS"])

    h=data.get("hist")
    if h is not None and not h.empty:
        try:
            c=h["Close"]
            m["price_5y_return"]=round(((c.iloc[-1]/c.iloc[0])-1)*100,2)
            m["price_5y_high"]=round(float(c.max()),2); m["price_5y_low"]=round(float(c.min()),2)
        except: m["price_5y_return"]=m["price_5y_high"]=m["price_5y_low"]=None
    else: m["price_5y_return"]=m["price_5y_high"]=m["price_5y_low"]=None
    m["news"]=[{"title":n.get("title",""),"publisher":n.get("publisher","")} for n in data.get("news",[])]
    return m


def ai_prompt_ui(ticker, m):
    ms = json.dumps({k:v for k,v in m.items() if k not in ["description","news","revenue_history","net_income_history"]}, indent=2, default=str)
    sample = FUND_THESIS[:3000] if FUND_THESIS else ""
    return [
        {"role":"system","content":f"""You are the senior equity research analyst for PickR. Write institutional-grade research using the QGLP framework.

STYLE: 4-5 substantial paragraphs per QGLP section. Specific numbers. Professional prose. Strengths and weaknesses.

THESIS: {sample}

RULES: Use ONLY provided numbers. Never invent. Respond with ONLY valid JSON, no fences, no extra text.

JSON structure:
{{"executive_summary":"3 sentences. TL;DR of the entire investment case - what the company does, why it matters, and what to do about it.",
"business_overview":"4-5 paragraphs",
"quality_score":8,"quality_analysis":"4-5 paragraphs analyzing moats, margins, ROE, cash flow quality, capital allocation, balance sheet",
"growth_score":8,"growth_analysis":"4-5 paragraphs analyzing revenue/EPS growth, organic vs acquired, forward estimates, peer comparison",
"longevity_score":8,"longevity_analysis":"4-5 paragraphs analyzing secular tailwinds, TAM, management, reinvestment runway, 10-year durability",
"price_score":8,"price_analysis":"4-5 paragraphs analyzing PE, PEG, EV/EBITDA, FCF yield, historical context, margin of safety",
"recommendation":"BUY","conviction":"High",
"recommendation_rationale":"3-4 sentences",
"risks":["Detailed risk 1 in 2-3 sentences","Risk 2","Risk 3","Risk 4","Risk 5"],
"bull_case":"3-4 sentences with specific catalysts",
"bear_case":"3-4 sentences with specific downside scenarios",
"position_sizing":"2-3 sentences on allocation and entry strategy"}}

Scores: integers 1-10. Recommendation: exactly BUY, WATCH, or PASS."""},
        {"role":"user","content":f"""Analyze {ticker} ({m.get('company_name',ticker)}).

VERIFIED METRICS: {ms}

Business: {m.get('description','N/A')[:500]}

Generate comprehensive QGLP analysis with executive summary. JSON only."""}
    ]


def ai_prompt_report(ticker, m):
    ms = json.dumps({k:v for k,v in m.items() if k not in ["news"]}, indent=2, default=str)
    return [
        {"role":"system","content":f"""You are a senior equity research analyst producing a comprehensive investment research report.

{REPORT_PROMPT}

CRITICAL: Use ONLY the financial data provided below. Do not invent any figures. If data is missing, state so explicitly.
All probability assignments in the scenario framework should be clearly labeled as analytical estimates.

Output clean HTML with inline CSS. White background (#ffffff), dark text (#1a1a2e), professional sans-serif font.
Use proper HTML tables with borders for all data presentations.
Include a research masthead at the top with company name, ticker, date, price, and market cap."""},
        {"role":"user","content":f"""Produce the full institutional research report for {ticker} ({m.get('company_name',ticker)}).

VERIFIED FINANCIAL DATA:
{ms}

Generate the complete HTML report now. Sections 1-9 plus Annexure. Be as comprehensive as possible."""}
    ]

def run_ai(msgs):
    errors = []
    for model in FREE_MODELS:
        try:
            r = client.chat.completions.create(
                model=model, messages=msgs, max_tokens=7000, temperature=0.3,
                extra_headers={"HTTP-Referer":"https://pickr.streamlit.app","X-Title":"PickR"},
            )
            raw = r.choices[0].message.content.strip()
            return raw, model, None
        except Exception as e:
            errors.append(f"{model}: {str(e)[:120]}")
    return None, None, errors


def run_ai_json(ticker, m):
    msgs = ai_prompt_ui(ticker, m)
    raw, model, errors = run_ai(msgs)
    if raw is None: return {"error":True,"details":errors}
    try:
        if raw.startswith("```"): raw=raw.split("\n",1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"): raw=raw[:-3]
        if raw.startswith("json"): raw=raw[4:]
        raw=raw.strip()

        try:
            a = json.loads(raw)
        except json.JSONDecodeError:
            last_brace = raw.rfind("}")
            if last_brace == -1:
                raw = raw.rstrip().rstrip(",").rstrip('"')
                if raw.count('"') % 2 != 0: raw += '"'
                open_brackets = raw.count("[") - raw.count("]")
                open_braces = raw.count("{") - raw.count("}")
                raw += "]" * open_brackets + "}" * open_braces
            else:
                raw = raw[:last_brace+1]
                open_braces = raw.count("{") - raw.count("}")
                open_brackets = raw.count("[") - raw.count("]")
                if raw.count('"') % 2 != 0: raw += '"'
                raw += "]" * open_brackets + "}" * open_braces
            a = json.loads(raw)

        a["model_used"] = model
        defaults = {
            "business_overview": "Analysis not available.",
            "quality_score": 5, "quality_analysis": "Analysis not available.",
            "growth_score": 5, "growth_analysis": "Analysis not available.",
            "longevity_score": 5, "longevity_analysis": "Analysis not available.",
            "price_score": 5, "price_analysis": "Analysis not available.",
            "recommendation": "WATCH", "conviction": "Medium",
            "recommendation_rationale": "Insufficient data for full analysis.",
            "executive_summary": "Report generated with partial data.",
            "risks": ["Data limitations prevent full risk assessment."],
            "bull_case": "Not available.", "bear_case": "Not available.",
            "position_sizing": "Not available.",
        }
        for k, v in defaults.items():
            if k not in a: a[k] = v
        return a

    except json.JSONDecodeError as e:
        return {"error":True,"details":[f"{model}: Bad JSON - {str(e)[:100]}","Raw output: "+raw[:300]]}


def run_ai_html(ticker, m):
    msgs = ai_prompt_report(ticker, m)
    raw, model, errors = run_ai(msgs)
    if raw is None: return None, errors
    if raw.startswith("```"): raw=raw.split("\n",1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"): raw=raw[:-3]
    if raw.startswith("html"): raw=raw[4:]
    return raw.strip(), None


def render(ticker, m, a, data):
    company = m.get("company_name",ticker)
    date = datetime.now().strftime("%B %d, %Y")
    cur = m.get("currency","USD")
    sym = get_sym(cur)

    st.markdown('<div class="rpt-card">', unsafe_allow_html=True)

    st.markdown(f'''<div class="rpt-head">
        <h2>{company}</h2>
        <div class="meta">{ticker} &nbsp;/&nbsp; {m.get("sector","")} &nbsp;/&nbsp; {m.get("industry","")} &nbsp;/&nbsp; {cur} &nbsp;/&nbsp; {date}</div>
    </div>''', unsafe_allow_html=True)

    rec=a.get("recommendation","WATCH").upper(); conv=a.get("conviction","Medium")
    rc="buy" if rec=="BUY" else ("pass" if rec=="PASS" else "watch")
    try: comp=round((int(a.get("quality_score",0))+int(a.get("growth_score",0))+int(a.get("longevity_score",0))+int(a.get("price_score",0)))/4,1)
    except: comp=0

    st.markdown(f'''<div class="rec-bar">
        <div class="rb-item"><div class="rb-label">Recommendation</div><div class="rb-val {rc}">{rec}</div></div>
        <div class="rb-item"><div class="rb-label">Conviction</div><div class="rb-val {rc}">{conv}</div></div>
        <div class="rb-item"><div class="rb-label">QGLP Composite</div><div class="rb-val {rc}">{comp}</div></div>
    </div>''', unsafe_allow_html=True)

    es = a.get("executive_summary","")
    if es:
        st.markdown(f'<div class="exec-summary">{es}</div>', unsafe_allow_html=True)

    st.markdown(f'<div class="rationale-text">{a.get("recommendation_rationale","")}</div>', unsafe_allow_html=True)

    w52h = m.get("week_52_high"); w52l = m.get("week_52_low"); cp = m.get("current_price")
    if w52h and w52l and cp:
        try:
            w52h=float(w52h); w52l=float(w52l); cpf=float(cp)
            if w52h > w52l:
                pct = max(0, min(100, ((cpf - w52l) / (w52h - w52l)) * 100))
                st.markdown(f'''<div class="sec">52-Week Range</div>
                <div class="range-bar-container">
                    <div class="range-bar-labels">
                        <span>{sym}{w52l:,.2f}</span>
                        <span style="color:rgba(255,255,255,0.6);font-weight:600;">Current: {sym}{cpf:,.2f}</span>
                        <span>{sym}{w52h:,.2f}</span>
                    </div>
                    <div class="range-bar">
                        <div class="range-bar-fill" style="width:{pct}%"></div>
                        <div class="range-bar-dot" style="left:{pct}%"></div>
                    </div>
                </div>''', unsafe_allow_html=True)
        except: pass

    h = data.get("hist")
    if h is not None and not h.empty:
        st.markdown('<div class="sec">5-Year Price History</div>', unsafe_allow_html=True)
        cd = h[["Close"]].copy(); cd.columns = ["Price"]
        st.line_chart(cd, use_container_width=True, height=250, color="#8b1a1a")

    st.markdown('<div class="sec">Valuation <span class="vtag">Verified</span></div>', unsafe_allow_html=True)
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    with c1: st.metric("Market Cap", fmt_c(m.get("market_cap"),cur))
    with c2: st.metric("Price", fmt_c(m.get("current_price"),cur))
    with c3: st.metric("Trailing P/E", fmt_r(m.get("trailing_pe")))
    with c4: st.metric("Forward P/E", fmt_r(m.get("forward_pe")))
    with c5: st.metric("PEG", fmt_r(m.get("peg_ratio")))
    with c6: st.metric("EV/EBITDA", fmt_r(m.get("ev_to_ebitda")))

    st.markdown('''<div style="display:flex;gap:1.5rem;flex-wrap:wrap;margin:0.3rem 0 0.8rem;">
        <span class="tooltip" style="font-size:0.75rem;color:rgba(255,255,255,0.25);">P/E: Price to Earnings<span class="tiptext">Share price divided by earnings per share. Lower may indicate undervaluation relative to earnings.</span></span>
        <span class="tooltip" style="font-size:0.75rem;color:rgba(255,255,255,0.25);">PEG: Price/Earnings to Growth<span class="tiptext">P/E ratio divided by earnings growth rate. PEG of 1.0 suggests fair value for the growth rate.</span></span>
        <span class="tooltip" style="font-size:0.75rem;color:rgba(255,255,255,0.25);">EV/EBITDA<span class="tiptext">Enterprise value divided by EBITDA. Useful for comparing companies with different capital structures.</span></span>
    </div>''', unsafe_allow_html=True)

    st.markdown('<div class="sec">Profitability</div>', unsafe_allow_html=True)
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    with c1: st.metric("Revenue", fmt_c(m.get("total_revenue"),cur))
    with c2: st.metric("Gross Margin", fmt_p(m.get("gross_margin")))
    with c3: st.metric("Op. Margin", fmt_p(m.get("operating_margin")))
    with c4: st.metric("Net Margin", fmt_p(m.get("profit_margin")))
    with c5: st.metric("ROE", fmt_p(m.get("roe")))
    with c6: st.metric("ROA", fmt_p(m.get("roa")))

    st.markdown('''<div style="display:flex;gap:1.5rem;flex-wrap:wrap;margin:0.3rem 0 0.8rem;">
        <span class="tooltip" style="font-size:0.75rem;color:rgba(255,255,255,0.25);">ROE: Return on Equity<span class="tiptext">Net income divided by shareholders' equity. Measures how efficiently the company generates profit from equity.</span></span>
        <span class="tooltip" style="font-size:0.75rem;color:rgba(255,255,255,0.25);">FCF Yield<span class="tiptext">Free cash flow divided by market cap. Higher yield suggests the company generates more cash relative to its valuation.</span></span>
    </div>''', unsafe_allow_html=True)

    st.markdown('<div class="sec">Growth</div>', unsafe_allow_html=True)
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    with c1: st.metric("Rev Growth", fmt_p(m.get("revenue_growth")))
    with c2: st.metric("Rev CAGR", fmt_p(m.get("revenue_cagr")))
    with c3: st.metric("NI CAGR", fmt_p(m.get("net_income_cagr")))
    with c4: st.metric("EPS CAGR", fmt_p(m.get("eps_cagr")))
    with c5: st.metric("Fwd EPS", fmt_r(m.get("forward_eps")))
    with c6:
        r5=m.get("price_5y_return")
        st.metric("5Y Return", f"{r5}%" if r5 else "-")

    rh,nh = m.get("revenue_history",{}), m.get("net_income_history",{})
    if rh or nh:
        st.markdown('<div class="sec">Revenue & Earnings Trend (Billions)</div>', unsafe_allow_html=True)
        cc1,cc2 = st.columns(2)
        with cc1:
            if rh: st.bar_chart(pd.DataFrame({"Revenue":rh}), use_container_width=True, height=200, color="#8b1a1a")
        with cc2:
            if nh: st.bar_chart(pd.DataFrame({"Net Income":nh}), use_container_width=True, height=200, color="#d4443a")

    st.markdown('<div class="sec">Financial Health</div>', unsafe_allow_html=True)
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    with c1: st.metric("FCF", fmt_c(m.get("free_cashflow"),cur))
    with c2: st.metric("FCF Yield", fmt_p(m.get("fcf_yield")))
    with c3: st.metric("Debt/Equity", fmt_r(m.get("debt_to_equity")))
    with c4: st.metric("Current Ratio", fmt_r(m.get("current_ratio")))
    with c5: st.metric("Div Yield", fmt_p(m.get("dividend_yield")))
    with c6: st.metric("Beta", fmt_r(m.get("beta")))

    q,g,l,p = a.get("quality_score",0),a.get("growth_score",0),a.get("longevity_score",0),a.get("price_score",0)
    st.markdown(f'''<div class="qglp-s">
        <div class="sec" style="margin-top:0;border-color:rgba(255,255,255,0.05);">QGLP Scorecard</div>
        <div class="qg">
            <div class="qc"><div class="ql">Quality</div><div class="qs">{q}</div><div class="qsub">Moats & Margins</div></div>
            <div class="qc"><div class="ql">Growth</div><div class="qs">{g}</div><div class="qsub">Revenue & Earnings</div></div>
            <div class="qc"><div class="ql">Longevity</div><div class="qs">{l}</div><div class="qsub">Durability</div></div>
            <div class="qc"><div class="ql">Price</div><div class="qs">{p}</div><div class="qsub">Valuation</div></div>
            <div class="qc comp"><div class="ql">Composite</div><div class="qs">{comp}</div><div class="qsub">Overall</div></div>
        </div>
    </div>''', unsafe_allow_html=True)

    for key,title in [("business_overview","Business Overview"),("quality_analysis","Quality Analysis"),
                       ("growth_analysis","Growth Analysis"),("longevity_analysis","Longevity Analysis"),
                       ("price_analysis","Price Analysis")]:
        st.markdown(f'<div class="sec">{title}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="prose">{a.get(key,"Not available.")}</div>', unsafe_allow_html=True)

    sector=m.get("sector","")
    if sector in SECTOR_PEERS:
        st.markdown('<div class="sec">Peer Comparison</div>', unsafe_allow_html=True)
        with st.spinner("Loading peers..."):
            peers=fetch_peers(ticker,sector)
        if peers:
            cur_row={"Ticker":ticker,"Company":m.get("company_name",ticker),"Mkt Cap":fmt_c(m.get("market_cap"),cur),
                "P/E":fmt_r(m.get("trailing_pe")),"Fwd P/E":fmt_r(m.get("forward_pe")),
                "PEG":fmt_r(m.get("peg_ratio")),"Margin":fmt_p(m.get("operating_margin")),
                "ROE":fmt_p(m.get("roe")),"Rev Gr.":fmt_p(m.get("revenue_growth"))}
            hds=list(cur_row.keys())
            th="".join(f"<th>{h}</th>" for h in hds)
            tr_c="<tr class='hl'>"+"".join(f"<td>{cur_row[h]}</td>" for h in hds)+"</tr>"
            tr_p="".join("<tr>"+"".join(f"<td>{pr.get(h,'-')}</td>" for h in hds)+"</tr>" for pr in peers)
            st.markdown(f'<table class="pt"><thead><tr>{th}</tr></thead><tbody>{tr_c}{tr_p}</tbody></table>', unsafe_allow_html=True)

    st.markdown('<div class="sec">Key Risks</div>', unsafe_allow_html=True)
    risks=a.get("risks",[])
    if isinstance(risks,list):
        st.markdown("".join(f'<div class="risk-row"><span class="rn">{str(i).zfill(2)}</span>{r}</div>' for i,r in enumerate(risks,1)), unsafe_allow_html=True)

    st.markdown('<hr class="div">', unsafe_allow_html=True)
    bc_col,br_col = st.columns(2)
    with bc_col:
        st.markdown(f'<div class="cb cb-bull"><div class="cb-title">Bull Case</div>{a.get("bull_case","N/A")}</div>', unsafe_allow_html=True)
    with br_col:
        st.markdown(f'<div class="cb cb-bear"><div class="cb-title">Bear Case</div>{a.get("bear_case","N/A")}</div>', unsafe_allow_html=True)

    st.markdown('<hr class="div">', unsafe_allow_html=True)
    st.markdown('<div class="sec">Position Sizing</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sz-box">{a.get("position_sizing","N/A")}</div>', unsafe_allow_html=True)

    st.markdown(f'''<div style="text-align:center;padding:1rem 0 0.5rem;font-size:0.7rem;color:rgba(255,255,255,0.18);">
        Data as of {date} &nbsp;/&nbsp; Analysis by {a.get("model_used","")} &nbsp;/&nbsp; Report #{st.session_state.report_count}
    </div>''', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# MAIN UI LAYOUT
# ══════════════════════════════════════════════════════════════

# Hero
st.markdown('''<div class="hero">
    <h1>Pick<span class="accent">R</span></h1>
    <div class="tag">Intelligent Equity Research</div>
    <div class="desc">Institutional-quality research reports powered by the QGLP framework. Verified financials, scenario analysis, peer comparisons, and AI-driven insights.</div>
</div>''', unsafe_allow_html=True)

# Stats
rc = st.session_state.report_count
st.markdown(f'''<div class="stats-row">
    <div class="sr-item"><span class="sr-num">24</span><span class="sr-lbl">Verified Metrics</span></div>
    <div class="sr-item"><span class="sr-num">4</span><span class="sr-lbl">QGLP Dimensions</span></div>
    <div class="sr-item"><span class="sr-num">5Y</span><span class="sr-lbl">Price History</span></div>
    <div class="sr-item"><span class="sr-num">{rc}+</span><span class="sr-lbl">Reports Generated</span></div>
</div>''', unsafe_allow_html=True)

# ── SINGLE SEARCH SECTION ────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
cl,cm,cr = st.columns([1,2.5,1])
with cm:
    recent_list = st.session_state.recent[-6:]
    tab_names = ["Search by Name","Popular Stocks","Enter Ticker"]
    if recent_list:
        tab_names.append("Recent")

    tabs = st.tabs(tab_names)
    resolved = None

    with tabs[0]:
        sq = st.text_input("Search", placeholder="Type a company name... e.g. Broadcom, Apple, Reliance", label_visibility="collapsed", key="s1")
        if sq and len(sq)>=2:
            res = search_ticker(sq)
            if res:
                opts = {f"{r['name']} ({r['symbol']})":r['symbol'] for r in res}
                sel = st.selectbox("Pick", opts.keys(), label_visibility="collapsed", key="s2")
                if sel: resolved = opts[sel]
            else: st.caption("No results found. Try the ticker tab.")

    with tabs[1]:
        sp = st.selectbox("Pick", POPULAR.keys(), label_visibility="collapsed", key="s3")
        if sp and POPULAR[sp]: resolved = POPULAR[sp]

    with tabs[2]:
        td = st.text_input("Ticker", placeholder="e.g. AVGO, AAPL, RELIANCE.NS", label_visibility="collapsed", key="s4")
        if td: resolved = td.strip().upper()

    if recent_list:
        with tabs[3]:
            sr = st.selectbox("Select a recent search", [""] + list(reversed(recent_list)), label_visibility="collapsed", key="s_recent")
            if sr: resolved = sr

    st.markdown("<div style='height:0.4rem'></div>", unsafe_allow_html=True)
    go = st.button("Generate Report", use_container_width=True, type="primary")


# ── REPORT CONTAINER: above info sections ─────────────────────
report_area = st.container()

# ── Info sections (always visible, below report) ─────────────
st.markdown('''<div class="hiw">
    <div class="hiw-title">How It Works</div>
    <div class="hiw-grid">
        <div class="hiw-card">
            <div class="hiw-step">Step 1</div>
            <div class="hiw-title2">Search</div>
            <div class="hiw-desc">Enter a company name or ticker. We support US, Indian, European, and Asian markets.</div>
        </div>
        <div class="hiw-card">
            <div class="hiw-step">Step 2</div>
            <div class="hiw-title2">Analyze</div>
            <div class="hiw-desc">We fetch real-time data, compute 24 financial metrics in Python, and run QGLP scoring via AI.</div>
        </div>
        <div class="hiw-card">
            <div class="hiw-step">Step 3</div>
            <div class="hiw-title2">Report</div>
            <div class="hiw-desc">Get a full research report with scores, charts, peer comparison, and a downloadable institutional analysis.</div>
        </div>
    </div>
</div>''', unsafe_allow_html=True)

st.markdown('''<div class="thesis-section">
    <div class="thesis-title">The QGLP Framework</div>
    <div class="thesis-grid">
        <div class="thesis-card">
            <div class="thesis-card-letter">Q</div>
            <div class="thesis-card-name">Quality</div>
            <div class="thesis-card-desc">Competitive moats, margin durability, return on capital, free cash flow quality, and management's capital allocation track record.</div>
        </div>
        <div class="thesis-card">
            <div class="thesis-card-letter">G</div>
            <div class="thesis-card-name">Growth</div>
            <div class="thesis-card-desc">Revenue and EPS trajectory, organic vs. acquired growth, forward estimates, and whether growth is accelerating or decelerating.</div>
        </div>
        <div class="thesis-card">
            <div class="thesis-card-letter">L</div>
            <div class="thesis-card-name">Longevity</div>
            <div class="thesis-card-desc">Secular tailwinds, total addressable market, management quality, reinvestment runway, and 10-year business durability.</div>
        </div>
        <div class="thesis-card">
            <div class="thesis-card-letter">P</div>
            <div class="thesis-card-name">Price</div>
            <div class="thesis-card-desc">Valuation through multiple lenses: P/E, PEG, EV/EBITDA, FCF yield, historical context, and margin of safety analysis.</div>
        </div>
    </div>
    <div class="thesis-scoring">
        <div class="thesis-scoring-title">Scoring Thresholds</div>
        <div class="scoring-row">
            <div class="scoring-item"><div class="scoring-range buy">7.5 - 10</div><div class="scoring-label">Buy</div></div>
            <div class="scoring-item"><div class="scoring-range watch">5.0 - 7.4</div><div class="scoring-label">Watch</div></div>
            <div class="scoring-item"><div class="scoring-range pass">0 - 4.9</div><div class="scoring-label">Pass</div></div>
        </div>
    </div>
</div>''', unsafe_allow_html=True)

st.markdown('''<div class="params-card">
    <div class="thesis-title">Research Parameters</div>
    <div class="params-row"><span class="params-key">Financial Data</span><span class="params-val">Yahoo Finance (real-time)</span></div>
    <div class="params-row"><span class="params-key">AI Analysis</span><span class="params-val">Multi-model via OpenRouter (best available)</span></div>
    <div class="params-row"><span class="params-key">Metrics Calculation</span><span class="params-val">Python (verified, not AI-generated)</span></div>
    <div class="params-row"><span class="params-key">CAGR Period</span><span class="params-val">Based on available annual data (typically 3-4 years)</span></div>
    <div class="params-row"><span class="params-key">Peer Selection</span><span class="params-val">Top 4 sector peers by market relevance</span></div>
    <div class="params-row"><span class="params-key">Download Report</span><span class="params-val">Full institutional HTML report with scenario analysis</span></div>
</div>''', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
# GENERATION LOGIC
# ══════════════════════════════════════════════════════════════

should_generate = False
ticker = None

if go and resolved:
    ticker = resolved.strip().upper()
    should_generate = True
elif go and not resolved:
    with report_area:
        st.warning("Select or enter a company first.")

# ── Step 1: Generate main report if needed ────────────────────
if should_generate and ticker:
    if ticker not in st.session_state.recent:
        st.session_state.recent.append(ticker)
    st.session_state.report_count += 1
    st.session_state.cached_html = None
    st.session_state.generate_html = False
    st.session_state.html_just_generated = False

    with report_area:
        with st.status(f"Analyzing {ticker}...", expanded=True) as status:
            st.write(f"Connecting to Yahoo Finance for **{ticker}**...")
            st.caption("Pulling real-time price, fundamentals, financials, and 5-year history")
            try: sd = fetch(ticker)
            except Exception as e: st.error(f"Failed to fetch data: {e}"); st.stop()
            info = sd.get("info",{})
            if isinstance(info,dict) and info.get("error"): st.error(f"Ticker '{ticker}' not found or unavailable."); st.stop()

            company_name = info.get("shortName", info.get("longName", ticker))
            st.write(f"Successfully loaded **{company_name}**")

            st.write("Computing 24 verified financial metrics...")
            st.caption("Revenue CAGR, margins, ROE/ROA, FCF yield, valuation ratios, debt metrics")
            m = calc(sd)
            if "error" in m: st.error(m["error"]); st.stop()

            st.write("Running QGLP analysis via AI...")
            st.caption("Scoring Quality, Growth, Longevity, and Price dimensions with institutional-grade prose")
            a = run_ai_json(ticker, m)
            if isinstance(a,dict) and a.get("error"):
                status.update(label="Analysis failed", state="error")
                for d in a.get("details",[]): st.code(d)
                st.stop()

            rec = a.get("recommendation","WATCH")
            status.update(label=f"Analysis complete: {company_name} / {rec}", state="complete")

    st.session_state.cached_report = {"ticker":ticker, "metrics":m, "analysis":a, "data":sd}

# ── Step 2: Handle HTML report generation (flag-based) ────────
if st.session_state.generate_html and st.session_state.cached_report:
    cached = st.session_state.cached_report
    with report_area:
        with st.status("Generating institutional HTML report...", expanded=True) as html_status:
            st.write(f"Building comprehensive report for **{cached['metrics'].get('company_name', cached['ticker'])}**...")
            st.caption("This includes scenario analysis, probability-weighted valuations, catalyst calendars, and risk frameworks")
            st.write("Calling AI model for full institutional report generation...")
            st.caption("Typically takes 30-90 seconds depending on model availability")
            html_report, html_errors = run_ai_html(cached["ticker"], cached["metrics"])
            if html_report:
                st.session_state.cached_html = html_report
                st.session_state.html_just_generated = True
                html_status.update(label="HTML report ready!", state="complete")
            else:
                html_status.update(label="HTML generation failed", state="error")
                if html_errors:
                    for e in html_errors: st.code(e)
    st.session_state.generate_html = False
    st.rerun()


# ══════════════════════════════════════════════════════════════
# RENDER FROM CACHE
# ══════════════════════════════════════════════════════════════

if st.session_state.cached_report:
    cached = st.session_state.cached_report
    c_ticker = cached["ticker"]
    c_m = cached["metrics"]
    c_a = cached["analysis"]
    c_data = cached["data"]

    with report_area:
        render(c_ticker, c_m, c_a, c_data)

        # ── Download section (single, clean) ──────────────────
        st.markdown('<hr class="div">', unsafe_allow_html=True)
        st.markdown('''<div style="text-align:center;padding:1rem 0 0.5rem;">
            <div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.16em;color:rgba(255,255,255,0.2);margin-bottom:0.8rem;">Download Options</div>
        </div>''', unsafe_allow_html=True)

        dl1, dl2, dl3 = st.columns([1,1,1])

        with dl1:
            md_lines = [
                f"# {c_m.get('company_name',c_ticker)} ({c_ticker})",
                f"PickR Research Report / {datetime.now().strftime('%B %d, %Y')}",
                f"{c_m.get('sector','')} / {c_m.get('industry','')} / {c_m.get('currency','USD')}","",
                f"## {c_a.get('recommendation','N/A')} | Conviction: {c_a.get('conviction','N/A')}","",
                c_a.get("executive_summary",""),"","---","",
                c_a.get("recommendation_rationale",""),"","---","",
            ]
            for k,t in [("business_overview","Business Overview"),("quality_analysis","Quality"),
                         ("growth_analysis","Growth"),("longevity_analysis","Longevity"),("price_analysis","Price")]:
                md_lines += [f"## {t}","",c_a.get(k,""),"","---",""]
            md_lines += ["## Risks",""]
            for i,r in enumerate(c_a.get("risks",[]),1): md_lines.append(f"{i}. {r}")
            md_lines += ["","## Bull Case","",c_a.get("bull_case",""),"","## Bear Case","",c_a.get("bear_case",""),
                         "","## Position Sizing","",c_a.get("position_sizing",""),
                         "",f"*PickR / {datetime.now().strftime('%B %d, %Y')}*"]
            st.download_button("Summary (Markdown)", "\n".join(md_lines),
                              f"PickR_{c_ticker}_{datetime.now().strftime('%Y%m%d')}.md","text/markdown",
                              use_container_width=True)

        with dl2:
            if st.session_state.cached_html:
                # Show download button
                st.download_button("Download Full Report (HTML)", st.session_state.cached_html,
                                  f"PickR_{c_ticker}_Full_{datetime.now().strftime('%Y%m%d')}.html","text/html",
                                  use_container_width=True, key="dl_html")
                # Auto-open in new tab if just generated
                if st.session_state.html_just_generated:
                    b64 = base64.b64encode(st.session_state.cached_html.encode()).decode()
                    components.html(f"""
                        <script>
                            var newTab = window.open();
                            if (newTab) {{
                                newTab.document.write(atob("{b64}"));
                                newTab.document.close();
                            }}
                        </script>
                    """, height=0)
                    st.session_state.html_just_generated = False
            else:
                # Button sets flag, rerun handles generation
                if st.button("Generate Full Report (HTML)", use_container_width=True, type="primary", key="gen_html"):
                    st.session_state.generate_html = True
                    st.rerun()

        with dl3:
            try:
                comp = round((int(c_a.get("quality_score",5))+int(c_a.get("growth_score",5))+int(c_a.get("longevity_score",5))+int(c_a.get("price_score",5)))/4,1)
            except:
                comp = 0
            export_data = {
                "ticker": c_ticker,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "currency": c_m.get("currency","USD"),
                "metrics": {k:v for k,v in c_m.items() if k not in ["description","news","revenue_history","net_income_history"]},
                "scores": {
                    "quality": c_a.get("quality_score"), "growth": c_a.get("growth_score"),
                    "longevity": c_a.get("longevity_score"), "price": c_a.get("price_score"),
                    "composite": comp,
                },
                "recommendation": c_a.get("recommendation"),
                "conviction": c_a.get("conviction"),
            }
            st.download_button("Raw Data (JSON)", json.dumps(export_data, indent=2, default=str),
                              f"PickR_{c_ticker}_{datetime.now().strftime('%Y%m%d')}.json","application/json",
                              use_container_width=True)


# ── Footer ───────────────────────────────────────────────────
st.markdown(f'''<div class="foot-card">
    <div class="foot-name">Built by Mayukh Kondepudi</div>
    <div class="foot-email">mayukhkondepudi@gmail.com</div>
    <div class="foot-disclaimer">
        PickR is an AI-powered equity research tool for educational and informational purposes only.
        It does not constitute financial advice, investment recommendations, or an offer to buy or sell securities.
        All financial data is sourced from Yahoo Finance and may be delayed. AI-generated analysis is based on
        publicly available information and should not be relied upon as the sole basis for investment decisions.
        Past performance does not guarantee future results. Always consult a qualified financial advisor
        before making investment decisions.
    </div>
    <div class="foot-copy">&copy; {datetime.now().year} PickR. All rights reserved.</div>
</div>''', unsafe_allow_html=True)
