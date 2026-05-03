"""
universe.py — Ticker universes for QGLP screening.

US  : ~480 tickers (full S&P 500 coverage + quality large-caps)
India: ~180 tickers (Nifty 50 + Nifty Next 150 key constituents)

Update quarterly when index composition changes.
Keep tickers that yfinance resolves cleanly; remove persistent 404s.
"""

# ══════════════════════════════════════════════════════════════
# UNITED STATES  — S&P 500 (full coverage)
# ══════════════════════════════════════════════════════════════

SP500_TOP_100 = [
    # ── Technology ──────────────────────────────────────────
    "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "AMD", "QCOM", "TXN",
    "AMAT", "LRCX", "ADI", "MU", "KLAC", "NOW", "SNPS", "CDNS",
    "PANW", "MSI", "CSCO", "IBM", "HPE", "DELL", "STX", "NTAP",
    "JNPR", "TEL", "KEYS", "CDW", "AKAM", "GEN", "GDDY", "FSLR",
    "ENPH", "SWKS", "QRVO", "TER", "MPWR", "ANSS", "PTC", "EPAM",
    "CTSH", "INFY", "WIT", "ACN", "GLOB",

    # ── Communication Services ───────────────────────────────
    "GOOGL", "META", "NFLX", "TMUS", "T", "VZ", "CMCSA", "DIS",
    "TTWO", "EA", "LYV", "MTCH", "ZM", "RBLX",

    # ── Consumer Discretionary ───────────────────────────────
    "AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "BKNG",
    "CMG", "TJX", "ROST", "DHI", "LEN", "PHM", "APTV", "ULTA",
    "DRI", "YUM", "HLT", "MAR", "F", "GM", "NVR", "TOL", "MTH",
    "KBH", "POOL", "W", "ETSY", "EBAY", "AMZN", "EXPE", "MGM",
    "WYNN", "LVS", "HAS", "MHK", "RL", "PVH", "VFC", "ANF",

    # ── Consumer Staples ─────────────────────────────────────
    "WMT", "COST", "PG", "KO", "PEP", "MDLZ", "MO", "PM", "KHC",
    "GIS", "K", "HSY", "SJM", "CAG", "CPB", "CLX", "CHD", "CL",
    "EL", "HRL", "SYY", "KR", "ACI", "COTY", "MNST",

    # ── Energy ───────────────────────────────────────────────
    "XOM", "CVX", "COP", "EOG", "PXD", "MPC", "VLO", "PSX",
    "HAL", "SLB", "BKR", "OKE", "KMI", "WMB", "FANG", "DVN",
    "APA", "HES", "MRO", "EQT", "CTRA", "LNG", "OXY",

    # ── Financials ───────────────────────────────────────────
    "JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "SCHW", "USB",
    "PNC", "TFC", "MTB", "FITB", "KEY", "CFG", "HBAN", "RF",
    "AXP", "COF", "DFS", "SYF", "BRK-B", "MET", "PRU", "AFL",
    "AIG", "ALL", "CB", "SPGI", "MCO", "ICE", "CME", "CBOE",
    "MSCI", "BR", "TROW", "BEN", "IVZ", "AMG", "LPLA", "RJF",
    "CINF", "L", "WRB", "HIG", "TRV", "PGR", "AJG", "MMC",
    "AON", "WTW", "FDS", "NDAQ",

    # ── Healthcare ───────────────────────────────────────────
    "UNH", "LLY", "JNJ", "ABBV", "MRK", "TMO", "ABT", "AMGN",
    "BMY", "GILD", "CI", "CVS", "HUM", "CNC", "ELV", "ISRG",
    "MDT", "BSX", "SYK", "BDX", "ZBH", "EW", "RMD", "BAX",
    "HOLX", "IQV", "VRTX", "REGN", "BIIB", "MRNA", "PFE",
    "ZTS", "IDXX", "MTD", "DHR", "WAT", "A", "TECH", "PODD",
    "ALGN", "DXCM", "GEHC", "MOH", "HCA", "THC", "UHS", "STE",
    "WST", "VTRS", "JAZZ", "INCY",

    # ── Industrials ──────────────────────────────────────────
    "HON", "CAT", "DE", "UNP", "LMT", "RTX", "GD", "NOC", "BA",
    "GE", "ETN", "EMR", "PH", "ROK", "IR", "OTIS", "CARR", "TT",
    "PCAR", "CMI", "ITW", "FAST", "GWW", "AME", "FTV", "VRSK",
    "ROP", "IDEX", "XYL", "DOV", "FLS", "MAS", "ALLE", "GNRC",
    "HUBB", "LII", "AOS", "JCI", "CSGP", "BKI", "TDY", "HWM",
    "AXON", "LDOS", "SAIC", "BAH", "CACI", "MANT", "CSX", "NSC",
    "CNI", "CP", "R", "KNX", "CHRW", "JBHT", "UPS", "FDX",
    "GXO", "EXPD",

    # ── Materials ────────────────────────────────────────────
    "LIN", "APD", "ECL", "DD", "DOW", "NEM", "FCX", "NUE",
    "STLD", "RS", "VMC", "MLM", "BLL", "AVY", "IP", "PKG",
    "WRK", "SEE", "CF", "MOS", "FMC", "ALB", "CTVA", "IFF",
    "CE", "EMN", "HUN", "RPM", "PPG", "SHW",

    # ── Real Estate ──────────────────────────────────────────
    "PLD", "AMT", "EQIX", "CCI", "SPG", "O", "WELL", "DLR",
    "PSA", "EXR", "ARE", "VTR", "PEAK", "AVB", "EQR", "MAA",
    "NNN", "WY", "CBRE", "JLL", "HST", "KIM", "REG",

    # ── Utilities ────────────────────────────────────────────
    "NEE", "SO", "DUK", "AEP", "EXC", "SRE", "D", "XEL",
    "WEC", "ES", "PPL", "CMS", "ETR", "FE", "AES", "NI",
    "PEG", "AWK", "WTRG",
]

# Deduplicate while preserving order (AMZN appears twice above)
_seen: set = set()
_deduped = []
for _t in SP500_TOP_100:
    if _t not in _seen:
        _seen.add(_t)
        _deduped.append(_t)
SP500_TOP_100 = _deduped

# ── Quality growth additions not always in S&P 500 ───────────
QUALITY_EXTRAS_US = [
    "ADBE", "INTU", "CRM", "CRWD", "ZS", "DDOG", "NET", "SNOW",
    "MDB", "VEEV", "HUBS", "TTD", "APP", "BILL", "TOST", "GTLB",
    "PCTY", "PAYC", "PAYLOCITY", "RNG",
]

# Full US screener universe
US_UNIVERSE = SP500_TOP_100 + [t for t in QUALITY_EXTRAS_US if t not in _seen]


# ══════════════════════════════════════════════════════════════
# INDIA  — Nifty 50 + Nifty Next 150 key constituents
# ══════════════════════════════════════════════════════════════

NIFTY_50 = [
    # ── Nifty 50 ─────────────────────────────────────────────
    "RELIANCE.NS",   "TCS.NS",          "HDFCBANK.NS",    "INFY.NS",
    "ICICIBANK.NS",  "HINDUNILVR.NS",   "BHARTIARTL.NS",  "ITC.NS",
    "SBIN.NS",       "LT.NS",           "KOTAKBANK.NS",   "BAJFINANCE.NS",
    "HCLTECH.NS",    "AXISBANK.NS",     "MARUTI.NS",      "ASIANPAINT.NS",
    "TITAN.NS",      "SUNPHARMA.NS",    "DMART.NS",       "TATAMOTORS.NS",
    "NTPC.NS",       "ULTRACEMCO.NS",   "WIPRO.NS",       "ONGC.NS",
    "POWERGRID.NS",  "M&M.NS",          "ADANIENT.NS",    "ADANIPORTS.NS",
    "BAJAJFINSV.NS", "TATASTEEL.NS",    "JSWSTEEL.NS",    "TECHM.NS",
    "NESTLEIND.NS",  "HDFCLIFE.NS",     "INDUSINDBK.NS",  "SBILIFE.NS",
    "COALINDIA.NS",  "GRASIM.NS",       "DIVISLAB.NS",    "BRITANNIA.NS",
    "CIPLA.NS",      "DRREDDY.NS",      "HEROMOTOCO.NS",  "APOLLOHOSP.NS",
    "EICHERMOT.NS",  "TATACONSUM.NS",   "BAJAJ-AUTO.NS",  "HINDALCO.NS",
    "BPCL.NS",       "SHRIRAMFIN.NS",
]

NIFTY_NEXT_150 = [
    # ── IT & Software ─────────────────────────────────────────
    "PERSISTENT.NS", "COFORGE.NS",     "LTIM.NS",        "MPHASIS.NS",
    "LTTS.NS",       "OFSS.NS",        "KPITTECH.NS",    "TATAELXSI.NS",
    "HEXAWARE.NS",   "CYIENT.NS",      "MASTEK.NS",

    # ── Banking & Finance ─────────────────────────────────────
    "BANDHANBNK.NS", "IDFCFIRSTB.NS",  "FEDERALBNK.NS",  "KARURVYSYA.NS",
    "CANBK.NS",      "BANKBARODA.NS",  "UNIONBANK.NS",   "PNB.NS",
    "MUTHOOTFIN.NS", "CHOLAFIN.NS",    "BAJAJHLDNG.NS",  "ICICIGI.NS",
    "ICICIPRULI.NS", "HDFCAMC.NS",     "NAUKRI.NS",      "POLICYBZR.NS",
    "PAYTM.NS",      "ANGELONE.NS",    "BSE.NS",

    # ── Consumer & Retail ─────────────────────────────────────
    "TRENT.NS",      "NYKAA.NS",       "ZOMATO.NS",      "DELHIVERY.NS",
    "PAGEIND.NS",    "MCDOWELL-N.NS",  "RADICO.NS",      "VARUNBEV.NS",
    "COLPAL.NS",     "MARICO.NS",      "GODREJCP.NS",    "DABUR.NS",
    "EMAMILTD.NS",   "JYOTHYLAB.NS",   "VBL.NS",         "BIKAJI.NS",

    # ── Pharma & Healthcare ───────────────────────────────────
    "TORNTPHARM.NS", "LUPIN.NS",       "AUROPHARMA.NS",  "ALKEM.NS",
    "GLENMARK.NS",   "BIOCON.NS",      "IPCA.NS",        "PIIND.NS",
    "ABBOTINDIA.NS", "PFIZER.NS",      "SANOFI.NS",      "AJANTPHARM.NS",
    "MANKIND.NS",    "JBCHEPHARM.NS",

    # ── Auto & Auto Ancillaries ───────────────────────────────
    "MOTHERSON.NS",  "BOSCHLTD.NS",    "BHARATFORG.NS",  "APOLLOTYRE.NS",
    "BALKRISIND.NS", "CEATLTD.NS",     "MRF.NS",         "TIINDIA.NS",
    "ESCORTS.NS",    "MAHINDCIE.NS",   "SUNDRMFAST.NS",

    # ── Capital Goods & Engineering ───────────────────────────
    "SIEMENS.NS",    "ABB.NS",         "HAVELLS.NS",     "POLYCAB.NS",
    "CUMMINSIND.NS", "THERMAX.NS",     "CGPOWER.NS",     "BEL.NS",
    "BHEL.NS",       "RVNL.NS",        "RAILVIKAS.NS",   "IRCON.NS",
    "KEC.NS",        "APLAPOLLO.NS",   "JINDALSAW.NS",

    # ── Cement ────────────────────────────────────────────────
    "SHREECEM.NS",   "AMBUJACEM.NS",   "ACC.NS",         "RAMCOCEM.NS",
    "JKCEMENT.NS",   "HEIDELBERG.NS",

    # ── Power & Utilities ─────────────────────────────────────
    "TATAPOWER.NS",  "ADANIGREEN.NS",  "TORNTPOWER.NS",  "CESC.NS",
    "SJVN.NS",       "NHPC.NS",        "IREDA.NS",

    # ── Real Estate ───────────────────────────────────────────
    "DLF.NS",        "GODREJPROP.NS",  "PRESTIGE.NS",    "OBEROIRLTY.NS",
    "PHOENIXLTD.NS", "SOBHA.NS",

    # ── Oil & Gas ─────────────────────────────────────────────
    "PETRONET.NS",   "IGL.NS",         "MGL.NS",         "GAIL.NS",
    "HINDPETRO.NS",

    # ── Metals ────────────────────────────────────────────────
    "SAIL.NS",       "NMDC.NS",        "VEDL.NS",        "NATIONALUM.NS",
    "HINDCOPPER.NS",

    # ── Diversified / Conglomerates ───────────────────────────
    "ADANIPOWER.NS", "ADANITRANS.NS",  "GMRINFRA.NS",   "IRCTC.NS",
]

# Full India screener universe (deduplicated)
_india_seen: set = set()
_india_deduped = []
for _t in NIFTY_50 + NIFTY_NEXT_150:
    if _t not in _india_seen:
        _india_seen.add(_t)
        _india_deduped.append(_t)
INDIA_UNIVERSE = _india_deduped