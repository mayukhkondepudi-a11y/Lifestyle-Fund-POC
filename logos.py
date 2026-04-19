"""
logos.py - Stock logo utilities for PickR
Uses Clearbit Logo API (free, no auth) as primary source.
Falls back to a styled SVG monogram using the stock's sector color.

Usage:
    from logos import get_logo_html, get_logo_url, get_logo_and_name_html
"""

import base64

TICKER_DOMAIN = {
    "AAPL":  "apple.com",
    "MSFT":  "microsoft.com",
    "GOOGL": "google.com",
    "GOOG":  "google.com",
    "AMZN":  "amazon.com",
    "META":  "meta.com",
    "NVDA":  "nvidia.com",
    "TSLA":  "tesla.com",
    "NFLX":  "netflix.com",
    "ADBE":  "adobe.com",
    "CRM":   "salesforce.com",
    "ORCL":  "oracle.com",
    "INTC":  "intel.com",
    "AMD":   "amd.com",
    "QCOM":  "qualcomm.com",
    "AVGO":  "broadcom.com",
    "TXN":   "ti.com",
    "AMAT":  "appliedmaterials.com",
    "LRCX":  "lamresearch.com",
    "KLAC":  "kla.com",
    "MU":    "micron.com",
    "TSM":   "tsmc.com",
    "JPM":   "jpmorganchase.com",
    "GS":    "goldmansachs.com",
    "MS":    "morganstanley.com",
    "BAC":   "bankofamerica.com",
    "WFC":   "wellsfargo.com",
    "BLK":   "blackrock.com",
    "V":     "visa.com",
    "MA":    "mastercard.com",
    "AXP":   "americanexpress.com",
    "PYPL":  "paypal.com",
    "JNJ":   "jnj.com",
    "LLY":   "lilly.com",
    "PFE":   "pfizer.com",
    "MRK":   "merck.com",
    "ABBV":  "abbvie.com",
    "UNH":   "unitedhealthgroup.com",
    "ABT":   "abbott.com",
    "TMO":   "thermofisher.com",
    "WMT":   "walmart.com",
    "COST":  "costco.com",
    "HD":    "homedepot.com",
    "NKE":   "nike.com",
    "MCD":   "mcdonalds.com",
    "SBUX":  "starbucks.com",
    "KO":    "coca-cola.com",
    "PEP":   "pepsico.com",
    "PG":    "pg.com",
    "XOM":   "exxonmobil.com",
    "CVX":   "chevron.com",
    "CAT":   "caterpillar.com",
    "BA":    "boeing.com",
    "GE":    "ge.com",
    "MMM":   "3m.com",
    "UPS":   "ups.com",
    "FDX":   "fedex.com",
    "BRK-B": "berkshirehathaway.com",
    "BRK.B": "berkshirehathaway.com",
    "RELIANCE.NS":   "ril.com",
    "TCS.NS":        "tcs.com",
    "INFY.NS":       "infosys.com",
    "HDFCBANK.NS":   "hdfcbank.com",
    "ICICIBANK.NS":  "icicibank.com",
    "SBIN.NS":       "sbi.co.in",
    "WIPRO.NS":      "wipro.com",
    "HCLTECH.NS":    "hcltech.com",
    "BAJFINANCE.NS": "bajajfinserv.in",
    "KOTAKBANK.NS":  "kotak.com",
    "AXISBANK.NS":   "axisbank.com",
    "LT.NS":         "larsentoubro.com",
    "SUNPHARMA.NS":  "sunpharma.com",
    "TITAN.NS":      "titancompany.in",
    "ASIANPAINT.NS": "asianpaints.com",
    "MARUTI.NS":     "marutisuzuki.com",
    "HINDUNILVR.NS": "hul.co.in",
    "NESTLEIND.NS":  "nestle.in",
    "ULTRACEMCO.NS": "ultratechcement.com",
    "ONGC.NS":       "ongcindia.com",
    "NTPC.NS":       "ntpclimited.com",
    "POWERGRID.NS":  "powergridindia.com",
    "BHARTIARTL.NS": "airtel.in",
    "ADANIENT.NS":   "adanienterprises.com",
    "ADANIPORTS.NS": "adaniports.com",
    "CIPLA.NS":      "cipla.com",
    "DRREDDY.NS":    "drreddys.com",
    "DIVISLAB.NS":   "divislab.com",
    "TECHM.NS":      "techmahindra.com",
    "TATAMOTORS.NS": "tatamotors.com",
    "TATASTEEL.NS":  "tatasteel.com",
    "JSWSTEEL.NS":   "jsw.in",
    "HINDALCO.NS":   "hindalco.com",
    "VEDL.NS":       "vedantalimited.com",
    "GRASIM.NS":     "grasim.com",
    "EICHERMOT.NS":  "eichermotors.com",
    "HEROMOTOCO.NS": "heromotocorp.com",
    "BAJAJFINSV.NS": "bajajfinserv.in",
    "BAJAJ-AUTO.NS": "bajajauto.com",
    "INDUSINDBK.NS": "indusind.com",
    "BABA":  "alibaba.com",
    "JD":    "jd.com",
    "SE":    "sea.com",
    "GRAB":  "grab.com",
    "SHOP":  "shopify.com",
    "SQ":    "squareup.com",
    "UBER":  "uber.com",
    "LYFT":  "lyft.com",
    "ABNB":  "airbnb.com",
    "DASH":  "doordash.com",
    "SNOW":  "snowflake.com",
    "PLTR":  "palantir.com",
    "COIN":  "coinbase.com",
    "HOOD":  "robinhood.com",
    "RBLX":  "roblox.com",
    "SPOT":  "spotify.com",
    "TTD":   "thetradedesk.com",
    "ZM":    "zoom.us",
    "OKTA":  "okta.com",
    "CRWD":  "crowdstrike.com",
    "ZS":    "zscaler.com",
    "DDOG":  "datadoghq.com",
    "NET":   "cloudflare.com",
    "MDB":   "mongodb.com",
    "ESTC":  "elastic.co",
}

SECTOR_COLORS = {
    "Technology":              "#4a7fa5",
    "Information Technology":  "#4a7fa5",
    "Financials":              "#5a7d5a",
    "Financial Services":      "#5a7d5a",
    "Healthcare":              "#7a5a8a",
    "Health Care":             "#7a5a8a",
    "Consumer Discretionary":  "#a07040",
    "Consumer Staples":        "#6a8a6a",
    "Energy":                  "#8a6a30",
    "Industrials":             "#5a6a7a",
    "Materials":               "#7a6a5a",
    "Utilities":               "#5a7a8a",
    "Real Estate":             "#7a5a4a",
    "Communication Services":  "#4a5a9a",
    "Telecommunication":       "#4a5a9a",
}
DEFAULT_COLOR = "#555555"


def get_logo_url(ticker):
    """Return a Clearbit logo URL for the ticker, or None if not in map."""
    domain = TICKER_DOMAIN.get(ticker.upper())
    if domain:
        return f"https://logo.clearbit.com/{domain}"
    return None


def _monogram_svg(ticker, size, sector=""):
    """SVG monogram fallback — clean colored circle with 2-letter abbreviation."""
    clean = ticker.split(".")[0]
    letters = clean[:2].upper()
    color = SECTOR_COLORS.get(sector, DEFAULT_COLOR)
    font_size = round(size * 0.38)
    r = size // 2
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'xmlns="http://www.w3.org/2000/svg" style="flex-shrink:0">'
        f'<circle cx="{r}" cy="{r}" r="{r}" fill="{color}"/>'
        f'<text x="{r}" y="{r}" dominant-baseline="central" text-anchor="middle" '
        f'fill="#ffffff" font-size="{font_size}" font-weight="700" '
        f'font-family="Inter,system-ui,sans-serif" letter-spacing="0.03em">'
        f'{letters}</text>'
        f'</svg>'
    )


def get_logo_html(ticker, size=28, sector="", border_radius="6px", extra_style=""):
    """
    Return an HTML snippet for a stock logo, safe to pass to st.markdown.

    - Known tickers  -> Clearbit <img> with SVG monogram onerror fallback.
    - Unknown tickers -> SVG monogram rendered directly (no broken images ever).

    Args:
        ticker        : Stock ticker e.g. "AAPL" or "RELIANCE.NS"
        size          : Width/height in pixels (default 28)
        sector        : Company sector string, used for fallback monogram color
        border_radius : CSS border-radius (default "6px"; use "50%" for circle)
        extra_style   : Additional inline CSS string
    """
    logo_url = get_logo_url(ticker)
    img_style = (
        f"width:{size}px;height:{size}px;border-radius:{border_radius};"
        f"object-fit:contain;background:#1c1c1c;flex-shrink:0;{extra_style}"
    )

    if logo_url:
        fallback_svg = _monogram_svg(ticker, size, sector)
        svg_b64 = base64.b64encode(fallback_svg.encode()).decode()
        svg_data_uri = f"data:image/svg+xml;base64,{svg_b64}"
        return (
            f'<img src="{logo_url}" '
            f'width="{size}" height="{size}" '
            f'alt="{ticker} logo" '
            f'style="{img_style}" '
            f"onerror=\"this.onerror=null;this.src='{svg_data_uri}'\" "
            f'loading="lazy">'
        )
    else:
        return _monogram_svg(ticker, size, sector)


def get_logo_and_name_html(ticker, company_name, size=32, sector="", gap="0.75rem"):
    """
    Logo + company name + ticker in a horizontal flex row.
    Use in report headers and peer comparison tables.
    """
    logo = get_logo_html(ticker, size=size, sector=sector, border_radius="8px")
    display_ticker = ticker.replace(".NS", "").replace(".BO", "")
    return (
        f'<div style="display:flex;align-items:center;gap:{gap};">'
        f'{logo}'
        f'<div>'
        f'<div style="font-weight:700;color:#ffffff;font-size:1rem;line-height:1.2;">'
        f'{company_name}</div>'
        f'<div style="font-size:0.72rem;color:rgba(255,255,255,0.35);'
        f'letter-spacing:0.06em;margin-top:2px;">{display_ticker}</div>'
        f'</div>'
        f'</div>'
    )
