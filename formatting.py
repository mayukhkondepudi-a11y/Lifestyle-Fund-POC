"""Pure formatting and display helpers. No side effects, no I/O."""
import re
from config import CURRENCY_SYMBOLS


def safe_float(val, default=0.0):
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def get_sym(c):
    if not c or c == "N/A":
        return "$"
    return CURRENCY_SYMBOLS.get(c, f"{c} ")


def fmt_n(v, p="", s="", d=2):
    if v is None or v == "N/A" or v == "":
        return "-"
    try:
        n = float(v)
        if abs(n) >= 1e12: return f"{p}{n/1e12:.{d}f}T{s}"
        if abs(n) >= 1e9:  return f"{p}{n/1e9:.{d}f}B{s}"
        if abs(n) >= 1e6:  return f"{p}{n/1e6:.{d}f}M{s}"
        if abs(n) >= 1e3:  return f"{p}{n/1e3:.{d}f}K{s}"
        return f"{p}{n:.{d}f}{s}"
    except Exception:
        return "-"


def fmt_p(v, d=1):
    if v is None or v == "N/A" or v == "":
        return "-"
    try:
        n = float(v)
        return f"{n*100:.{d}f}%" if abs(n) < 1 else f"{n:.{d}f}%"
    except Exception:
        return "-"


def fmt_r(v, d=2):
    if v is None or v == "N/A" or v == "":
        return "-"
    try:
        return f"{float(v):.{d}f}"
    except Exception:
        return "-"


def fmt_c(v, cur="USD", d=2):
    return fmt_n(v, p=get_sym(cur), d=d)


def strip_html(text):
    if not text:
        return ""
    s = str(text)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = re.sub(r'<[^>]*$', ' ', s)
    s = re.sub(r'^[^<]*>', ' ', s)
    s = re.sub(r'```[a-z]*\n?', '', s)
    s = re.sub(r'```', '', s)
    s = re.sub(r'`([^`]*)`', r'\1', s)
    s = re.sub(r'\*\*([^*]*)\*\*', r'\1', s)
    s = re.sub(r'\*([^*]*)\*', r'\1', s)
    s = s.replace('<', '&lt;').replace('>', '&gt;')
    s = re.sub(r' {2,}', ' ', s)
    return s.strip()
