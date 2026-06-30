#!/usr/bin/env python3
"""
send_report.py — Generate the daily market PDF and email it.
Runs standalone (no Streamlit) so it works in GitHub Actions.

Required env vars (set as GitHub Secrets):
    GMAIL_USER, GMAIL_APP_PWD, MAIL_TO, FRED_KEY
"""

import datetime as dt
import io
import os
import re
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import yfinance as yf
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

# ---- CONFIG ----
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PWD = os.environ.get("GMAIL_APP_PWD", "")
MAIL_TO = [x.strip() for x in os.environ.get("MAIL_TO", "").split(",") if x.strip()]
FRED_KEY = os.environ.get("FRED_KEY", "")

H = {"User-Agent": "Mozilla/5.0 (market-dashboard-report/1.0)"}

EQUITIES = [
    ("India", "Nifty 50", "^NSEI"), ("India", "Sensex", "^BSESN"),
    ("US", "S&P 500", "^GSPC"), ("US", "Nasdaq", "^IXIC"),
    ("US", "Dow Jones", "^DJI"), ("Germany", "DAX", "^GDAXI"),
    ("UK", "FTSE 100", "^FTSE"), ("China", "Shanghai Composite", "000001.SS"),
    ("Hong Kong", "Hang Seng", "^HSI"), ("Japan", "Nikkei 225", "^N225"),
]
FX_PAIRS = [("USD/INR", "INR=X"), ("EUR/INR", "EURINR=X"),
            ("GBP/INR", "GBPINR=X"), ("JPY/INR", "JPYINR=X")]
COMMODITIES = [("Gold", "GC=F"), ("Silver", "SI=F"),
               ("Brent Crude", "BZ=F"), ("WTI Crude", "CL=F"),
               ("Copper", "HG=F"), ("Aluminum", "ALI=F")]


# ---- DATA FETCHERS ----
def yahoo_price(ticker):
    try:
        t = yf.Ticker(ticker)
        h = t.history(period="5d")
        if h.empty:
            return None, None
        price = float(h["Close"].iloc[-1])
        prev = float(h["Close"].iloc[-2]) if len(h) >= 2 else price
        chg = round((price / prev - 1) * 100, 2) if prev else 0
        return round(price, 2), chg
    except Exception:
        return None, None


def fred_val(series):
    if not FRED_KEY:
        return None
    try:
        url = (f"https://api.stlouisfed.org/fred/series/observations?"
               f"series_id={series}&api_key={FRED_KEY}&file_type=json"
               f"&sort_order=desc&limit=5")
        obs = requests.get(url, headers=H, timeout=20).json().get("observations", [])
        for o in obs:
            v = o.get("value")
            if v not in (".", "", None):
                return float(v)
    except Exception:
        pass
    return None


def gold_india():
    import html as _html
    _TAGS = re.compile(r"<[^>]+>")
    _STRIP = re.compile(r"<script.*?</script>|<style.*?</style>", re.S | re.I)
    try:
        r = requests.get("https://www.goodreturns.in/gold-rates/", headers=H, timeout=15)
        if r.status_code == 200:
            txt = re.sub(r"\s+", " ", _html.unescape(_TAGS.sub(" ", _STRIP.sub(" ", r.text))))
            m = re.search(r"([\d,]{3,})\s*per\s*gram\s*for\s*24", txt, re.I)
            if m:
                v = float(m.group(1).replace(",", ""))
                if 1000 <= v <= 100000:
                    return v
    except Exception:
        pass
    return None


# ---- SUMMARY ----
def build_summary(eq_data, fx_data, gold_price):
    lines = []
    np, nc = eq_data.get("^NSEI", (None, None))
    sp, sc = eq_data.get("^BSESN", (None, None))
    if np and nc is not None:
        s = f"Nifty 50 at {np:,.0f} ({nc:+.2f}%)"
        if sc is not None:
            s += f", Sensex {sc:+.2f}%"
        lines.append(s)

    moves = []
    for region, name, tk in EQUITIES:
        p, c = eq_data.get(tk, (None, None))
        if c is not None:
            moves.append((name, region, c))
    if moves:
        best = max(moves, key=lambda x: x[2])
        worst = min(moves, key=lambda x: x[2])
        lines.append(f"{best[0]} ({best[1]}) led ({best[2]:+.2f}%); "
                     f"{worst[0]} ({worst[1]}) lagged ({worst[2]:+.2f}%)")

    fp, fc = fx_data.get("INR=X", (None, None))
    if fp:
        lines.append(f"USD/INR {fp:.2f}" + (f" ({fc:+.2f}%)" if fc else ""))

    if gold_price:
        lines.append(f"Gold 24K Rs {gold_price * 10:,.0f}/10g")

    if moves:
        big = max(moves, key=lambda x: abs(x[2]))
        verb = "rose" if big[2] >= 0 else "fell"
        if abs(big[2]) < 0.5:
            lines.append("Quiet session with small moves across the board.")
        else:
            lines.append(f"What matters: {big[0]} ({big[1]}) {verb} {abs(big[2]):.2f}%, the day's biggest move.")

    return lines


# ---- PDF BUILDER ----
def build_pdf(eq_data, fx_data, cmd_data, gold_price, summary):
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=A4, topMargin=12*mm, bottomMargin=12*mm,
                            leftMargin=10*mm, rightMargin=10*mm)
    ss = getSampleStyleSheet()
    el = []

    stamp = dt.datetime.now().strftime("%a %d %b %Y  %H:%M IST")
    el.append(Paragraph("Daily Market Dashboard", ss["Title"]))
    el.append(Paragraph(stamp, ss["Normal"]))
    el.append(Spacer(1, 8))

    if summary:
        el.append(Paragraph("Today's Summary", ss["Heading2"]))
        bst = ParagraphStyle("b", fontName="Helvetica", fontSize=9, leading=13,
                             leftIndent=8, spaceAfter=2)
        for s in summary:
            el.append(Paragraph("&bull; " + s, bst))
        el.append(Spacer(1, 10))

    cell_st = ParagraphStyle("c", fontName="Helvetica", fontSize=7, leading=8)
    head_st = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=7, leading=8)

    def _tbl(title, headers, rows):
        el.append(Paragraph(title, ss["Heading2"]))
        data = [[Paragraph(h, head_st) for h in headers]]
        for row in rows:
            data.append([Paragraph(str(c), cell_st) for c in row])
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(.15, .15, .22)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), .4, colors.Color(.3, .3, .4)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.Color(.95, .95, .97), colors.Color(1, 1, 1)]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        el.append(t)
        el.append(Spacer(1, 10))

    def _fmt(price, chg_pct):
        if price is None:
            return "N/A", ""
        p = f"{price:,.2f}"
        c = ""
        if chg_pct is not None:
            c = f"{'+' if chg_pct >= 0 else ''}{chg_pct:.2f}%"
        return p, c

    def _color_chg(chg_str):
        if not chg_str:
            return chg_str
        if chg_str.startswith("+"):
            return f'<font color="#0a8f3c">{chg_str}</font>'
        elif chg_str.startswith("-"):
            return f'<font color="#c0392b">{chg_str}</font>'
        return chg_str

    # Equities
    eq_rows = []
    for region, name, tk in EQUITIES:
        p, c = eq_data.get(tk, (None, None))
        ps, cs = _fmt(p, c)
        eq_rows.append([region, name, ps, _color_chg(cs)])
    _tbl("1. Global Equity Markets", ["Region", "Index", "Price", "1D Change"], eq_rows)

    # FX
    fx_rows = []
    for name, tk in FX_PAIRS:
        p, c = fx_data.get(tk, (None, None))
        ps, cs = _fmt(p, c)
        fx_rows.append([name, ps, _color_chg(cs)])
    _tbl("2. Currency Markets", ["Pair", "Rate", "1D Change"], fx_rows)

    # Commodities
    cm_rows = []
    for name, tk in COMMODITIES:
        p, c = cmd_data.get(tk, (None, None))
        ps, cs = _fmt(p, c)
        cm_rows.append([name, f"${ps}", _color_chg(cs)])
    if gold_price:
        cm_rows.insert(0, ["Gold 24K (India)", f"Rs {gold_price * 10:,.0f}/10g", ""])
    _tbl("3. Commodities", ["Commodity", "Price", "1D Change"], cm_rows)

    # Macro
    macro_rows = []
    us_10y = fred_val("DGS10")
    if us_10y:
        macro_rows.append(["US 10Y Yield", f"{us_10y:.2f}%"])
    us_cpi = fred_val("CPIAUCSL")
    if us_cpi:
        macro_rows.append(["US CPI Index", f"{us_cpi:.2f}"])
    us_un = fred_val("UNRATE")
    if us_un:
        macro_rows.append(["US Unemployment", f"{us_un:.2f}%"])
    if macro_rows:
        _tbl("4. Macro Indicators", ["Indicator", "Latest"], macro_rows)

    doc.build(el)
    return bio.getvalue()


# ---- EMAIL SENDER ----
def send_email(pdf_bytes, summary_lines):
    if not all([GMAIL_USER, GMAIL_APP_PWD, MAIL_TO]):
        print("Missing email config. Set GMAIL_USER, GMAIL_APP_PWD, MAIL_TO.")
        return False

    today = dt.date.today().strftime("%d %b %Y")
    subject = f"Daily Market Dashboard — {today}"

    msg = MIMEMultipart("alternative")
    msg["From"] = GMAIL_USER
    msg["To"] = ", ".join(MAIL_TO)
    msg["Subject"] = subject

    # Plain text fallback
    plain = f"Market Dashboard — {today}\n\n"
    if summary_lines:
        plain += "\n".join(f"  • {s}" for s in summary_lines)
        plain += "\n\nFull report attached as PDF."
    msg.attach(MIMEText(plain, "plain"))

    # HTML body (looks nicer in Gmail/Outlook)
    bullets = "".join(f"<li style='margin:4px 0'>{s}</li>" for s in summary_lines)
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1E2761;margin-bottom:4px">Daily Market Dashboard</h2>
      <p style="color:#888;font-size:13px;margin-top:0">{today}</p>
      <div style="background:#f4f6f9;border-radius:8px;padding:16px 20px;margin:16px 0">
        <h3 style="margin:0 0 8px;font-size:14px;color:#1E2761">What matters today</h3>
        <ul style="margin:0;padding-left:18px;color:#333;font-size:14px;line-height:1.7">
          {bullets}
        </ul>
      </div>
      <p style="color:#888;font-size:12px">Full report attached as PDF. Data is delayed/representative.</p>
    </div>
    """
    msg.attach(MIMEText(html, "html"))

    # Attach PDF
    part = MIMEBase("application", "octet-stream")
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    fname = f"market-dashboard-{dt.date.today().isoformat()}.pdf"
    part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
    msg.attach(part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PWD)
            server.sendmail(GMAIL_USER, MAIL_TO, msg.as_string())
        print(f"Email sent to {', '.join(MAIL_TO)}")
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        return False


# ---- MAIN ----
if __name__ == "__main__":
    print("Fetching market data...")

    eq_data = {}
    for _, name, tk in EQUITIES:
        eq_data[tk] = yahoo_price(tk)
        print(f"  {name}: {eq_data[tk][0]}")

    fx_data = {}
    for name, tk in FX_PAIRS:
        fx_data[tk] = yahoo_price(tk)

    cmd_data = {}
    for name, tk in COMMODITIES:
        cmd_data[tk] = yahoo_price(tk)

    gold = gold_india()
    print(f"  Gold 24K: Rs {gold:,.0f}/g" if gold else "  Gold: scrape failed")

    summary = build_summary(eq_data, fx_data, gold)
    print("\nSummary:")
    for s in summary:
        print(f"  • {s}")

    pdf = build_pdf(eq_data, fx_data, cmd_data, gold, summary)
    print(f"\nPDF: {len(pdf):,} bytes")

    fname = f"market-dashboard-{dt.date.today().isoformat()}.pdf"
    with open(fname, "wb") as f:
        f.write(pdf)
    print(f"Saved: {fname}")

    if GMAIL_USER:
        send_email(pdf, summary)
    else:
        print("\nNo GMAIL_USER set — skipping email. Set env vars to enable.")
        print("  export GMAIL_USER=your@gmail.com")
        print("  export GMAIL_APP_PWD=xxxx-xxxx-xxxx-xxxx")
        print("  export MAIL_TO=recipient1@gmail.com,recipient2@gmail.com")
