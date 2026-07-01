#!/usr/bin/env python3
"""
send_report.py — Full daily market PDF (2 pages + yield chart) + email.
Runs at 9:20 AM IST via GitHub Actions. Fetches LIVE data at execution time.
"""

import datetime as dt
import io
import os
import re
import smtplib
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import requests
import yfinance as yf
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                Paragraph, Spacer, PageBreak, Image)

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PWD = os.environ.get("GMAIL_APP_PWD", "")
MAIL_TO = [x.strip() for x in os.environ.get("MAIL_TO", "").split(",") if x.strip()]
FRED_KEY = os.environ.get("FRED_KEY", "")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "").strip()
if not DASHBOARD_URL:
    DASHBOARD_URL = "https://dashboard-e6gfggmwdroxjgxjde8azc.streamlit.app"

H = {"User-Agent": "Mozilla/5.0 (market-dashboard-report/1.0)"}

EQUITIES = [
    ("India", "Nifty 50", "^NSEI"), ("India", "Sensex", "^BSESN"),
    ("US", "S&P 500", "^GSPC"), ("US", "Nasdaq", "^IXIC"),
    ("US", "Dow Jones", "^DJI"), ("Germany", "DAX", "^GDAXI"),
    ("UK", "FTSE 100", "^FTSE"), ("China", "Shanghai Composite", "000001.SS"),
    ("Hong Kong", "Hang Seng", "^HSI"), ("Japan", "Nikkei 225", "^N225"),
]
FX_PAIRS = [("USD/INR", "INR=X"), ("EUR/INR", "EURINR=X"),
            ("GBP/INR", "GBPINR=X"), ("JPY/INR", "JPYINR=X"), ("USD/CNY", "CNY=X")]
COMMODITIES_CFG = [
    ("Gold", "GC=F", "USD/oz"), ("Silver", "SI=F", "USD/oz"),
    ("Brent Crude", "BZ=F", "USD/bbl"), ("WTI Crude", "CL=F", "USD/bbl"),
    ("Natural Gas", "NG=F", "USD/MMBtu"), ("Copper", "HG=F", "USD/lb"),
    ("Aluminum", "ALI=F", "USD/t"),
]
CRYPTO = [("Bitcoin", "BTC-USD"), ("Ethereum", "ETH-USD")]
REITS = [("Embassy REIT", "EMBASSY.BO"), ("Mindspace REIT", "MINDSPACE.BO"),
         ("Brookfield REIT", "BIRET.BO"), ("Nexus Select REIT", "NXST.BO")]
INVITS = [("IndiGrid InvIT", "INDIGRID.BO"), ("Powergrid InvIT", "PGINVIT.BO")]
VOL = [("India VIX", "^INDIAVIX"), ("US VIX (CBOE)", "^VIX")]


def yahoo_price(ticker, retries=3):
    for attempt in range(retries):
        try:
            t = yf.Ticker(ticker)
            h = t.history(period="5d")
            if h.empty:
                if attempt < retries - 1:
                    time.sleep(2)
                    continue
                return None, None
            price = float(h["Close"].iloc[-1])
            prev = float(h["Close"].iloc[-2]) if len(h) >= 2 else price
            chg = round((price / prev - 1) * 100, 2) if prev else 0
            return round(price, 2), chg
        except Exception:
            if attempt < retries - 1:
                time.sleep(2)
            else:
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


def fred_history(series, years=5):
    if not FRED_KEY:
        return []
    try:
        start = (dt.date.today() - dt.timedelta(days=years * 365)).isoformat()
        url = (f"https://api.stlouisfed.org/fred/series/observations?"
               f"series_id={series}&api_key={FRED_KEY}&file_type=json"
               f"&observation_start={start}&sort_order=asc")
        obs = requests.get(url, headers=H, timeout=20).json().get("observations", [])
        out = []
        for o in obs:
            v = o.get("value")
            d = o.get("date")
            if v not in (".", "", None) and d:
                out.append((d, float(v)))
        return out
    except Exception:
        return []


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


def ecb_yield():
    base = ("https://data-api.ecb.europa.eu/service/data/YC/"
            "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_{}?lastNObservations=1&format=csvdata")
    out = {}
    for tenor in ("1Y", "2Y", "10Y"):
        try:
            r = requests.get(base.format(tenor), headers=H, timeout=20)
            if r.status_code == 200:
                lines = r.text.strip().splitlines()
                if len(lines) >= 2:
                    cols = lines[0].split(",")
                    vi = cols.index("OBS_VALUE") if "OBS_VALUE" in cols else -1
                    last = lines[-1].split(",")
                    if vi >= 0 and vi < len(last):
                        out[tenor] = round(float(last[vi]), 2)
        except Exception:
            pass
    return out


def japan_jgb():
    try:
        r = requests.get("https://www.mof.go.jp/english/policy/jgbs/reference/"
                         "interest_rate/jgbcme.csv", headers=H, timeout=20)
        if r.status_code != 200:
            return {}
        lines = [ln for ln in r.text.splitlines() if ln.strip()]
        hdr_i = next((i for i, l in enumerate(lines)
                      if l.split(",")[0].strip() == "Date"), None)
        if hdr_i is None:
            return {}
        header = [h.strip() for h in lines[hdr_i].split(",")]
        idx = {n: j for j, n in enumerate(header)}
        rows = [l.split(",") for l in lines[hdr_i + 1:]
                if re.match(r"^\s*\d{4}/\d{1,2}/\d{1,2}", l.split(",")[0])]
        if not rows:
            return {}
        last = rows[-1]
        def val(row, col):
            try: return float(row[idx[col]])
            except: return None
        return {"1Y": val(last, "1Y"), "2Y": val(last, "2Y"), "10Y": val(last, "10Y")}
    except Exception:
        return {}


def build_yield_chart():
    series = [
        ("India", "INDIRLTLT01STM"),
        ("US", "DGS10"),
        ("Japan", "IRLTLT01JPM156N"),
        ("UK", "IRLTLT01GBM156N"),
        ("Germany", "IRLTLT01DEM156N"),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=150)
    colors_map = {"India": "#1f77b4", "US": "#2ca02c", "UK": "#d62728",
                  "Germany": "#ff7f0e", "Japan": "#e377c2"}
    has_data = False
    for name, sid in series:
        data = fred_history(sid)
        if not data:
            continue
        has_data = True
        dates = [dt.datetime.strptime(d, "%Y-%m-%d") for d, _ in data]
        vals = [v for _, v in data]
        line, = ax.plot(dates, vals, label=name, linewidth=1.2,
                        color=colors_map.get(name, "#333"))
        for i in range(0, len(dates), 3):
            if i < len(vals):
                ax.plot(dates[i], vals[i], "o", color=line.get_color(), markersize=2)
                ax.annotate(f"{vals[i]:.2f}", (dates[i], vals[i]),
                            textcoords="offset points", xytext=(0, 4),
                            ha="center", fontsize=3.5, color=line.get_color())
    if not has_data:
        plt.close(fig)
        return None
    ax.set_ylabel("10Y yield (%)", fontsize=7)
    ax.tick_params(labelsize=6)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax.legend(fontsize=6, loc="upper left", framealpha=0.7)
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def build_summary(eq_data, fx_data, gold_price):
    lines = []
    np_, nc = eq_data.get("^NSEI", (None, None))
    sp, sc = eq_data.get("^BSESN", (None, None))
    if np_ and nc is not None:
        s = f"Nifty 50 at {np_:,.0f} ({nc:+.2f}%)"
        if sc is not None: s += f", Sensex {sc:+.2f}%"
        lines.append(s)
    moves = [(n, r, c) for r, n, t in EQUITIES
             for p, c in [eq_data.get(t, (None, None))] if c is not None]
    if moves:
        best = max(moves, key=lambda x: x[2])
        worst = min(moves, key=lambda x: x[2])
        lines.append(f"{best[0]} ({best[1]}) led ({best[2]:+.2f}%); "
                     f"{worst[0]} ({worst[1]}) lagged ({worst[2]:+.2f}%)")
    fp, fc = fx_data.get("INR=X", (None, None))
    if fp: lines.append(f"USD/INR {fp:.2f}" + (f" ({fc:+.2f}%)" if fc else ""))
    if gold_price: lines.append(f"Gold 24K Rs {gold_price * 10:,.0f}/10g")
    if moves:
        big = max(moves, key=lambda x: abs(x[2]))
        verb = "rose" if big[2] >= 0 else "fell"
        if abs(big[2]) >= 0.5:
            lines.append(f"Biggest move: {big[0]} ({big[1]}) {verb} {abs(big[2]):.2f}%")
    return lines


def build_pdf(eq_data, fx_data, cmd_data, vix_data, alt_data, gold_price,
              rates, summary, chart_buf):
    bio = io.BytesIO()
    doc = SimpleDocTemplate(bio, pagesize=A4, topMargin=12*mm, bottomMargin=12*mm,
                            leftMargin=10*mm, rightMargin=10*mm)
    ss = getSampleStyleSheet()
    el = []
    stamp = dt.datetime.now().strftime("%a %d %b %Y  %H:%M IST")
    el.append(Paragraph("Daily Market Dashboard", ss["Title"]))
    el.append(Paragraph(stamp, ss["Normal"]))
    el.append(Paragraph(
        f'<a href="{DASHBOARD_URL}" color="#1E2761">'
        f'<u>{DASHBOARD_URL}</u></a>', ss["Normal"]))
    el.append(Spacer(1, 8))

    cell_st = ParagraphStyle("c", fontName="Helvetica", fontSize=7, leading=8.5)
    head_st = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=7, leading=8.5)

    if summary:
        el.append(Paragraph("Today's summary", ss["Heading2"]))
        bst = ParagraphStyle("b", fontName="Helvetica", fontSize=9, leading=13,
                             leftIndent=8, spaceAfter=2)
        for s in summary:
            el.append(Paragraph("&bull; " + s, bst))
        el.append(Spacer(1, 10))

    def _tbl(title, headers, rows):
        el.append(Paragraph(title, ss["Heading2"]))
        data = [[Paragraph(h, head_st) for h in headers]]
        for row in rows:
            data.append([Paragraph(str(c), cell_st) for c in row])
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(.12, .12, .18)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), .3, colors.Color(.3, .3, .4)),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.Color(.96, .96, .98), colors.white]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
        ]))
        el.append(t)
        el.append(Spacer(1, 8))

    def _c(chg_pct):
        if chg_pct is None: return ""
        s = f"{'+' if chg_pct >= 0 else ''}{chg_pct:.2f}%"
        col = "#0a8f3c" if chg_pct >= 0 else "#c0392b"
        return f'<font color="{col}">{s}</font>'

    # 1. Equities
    eq_rows = []
    for region, name, tk in EQUITIES:
        p, c = eq_data.get(tk, (None, None))
        eq_rows.append([region, name, f"{p:,.2f}" if p else "N/A", _c(c)])
    _tbl("1. Global equity markets", ["Region", "Index", "Price", "1D"], eq_rows)

    # 2. Interest Rates
    rate_rows = []
    for country, data in rates.items():
        def _rv(k):
            v = data.get(k)
            return f"{v:.2f}%" if isinstance(v, (int, float)) else "N/A"
        rate_rows.append([country, _rv("1Y"), _rv("2Y"), _rv("10Y")])
    _tbl("2. Interest rates", ["Country", "1Y", "2Y", "10Y"], rate_rows)

    # Yield chart
    if chart_buf:
        el.append(Paragraph("5-year 10Y government bond yield trend", ss["Heading3"]))
        el.append(Image(chart_buf, width=480, height=200))
        el.append(Spacer(1, 8))

    # 3. Currency
    fx_rows = []
    for name, tk in FX_PAIRS:
        p, c = fx_data.get(tk, (None, None))
        fx_rows.append([name, f"{p:.4f}" if p else "N/A", _c(c)])
    _tbl("3. Currency markets", ["Pair", "Rate", "1D"], fx_rows)

    # 4. Commodities
    cm_rows = []
    if gold_price:
        cm_rows.append(["Gold 24K (India)", f"Rs {gold_price * 10:,.0f}/10g", ""])
    for name, tk, unit in COMMODITIES_CFG:
        p, c = cmd_data.get(tk, (None, None))
        cm_rows.append([name, f"${p:,.2f} {unit}" if p else "N/A", _c(c)])
    _tbl("4. Commodities", ["Commodity", "Price", "1D"], cm_rows)

    el.append(PageBreak())

    # 5. Alt assets
    alt_rows = []
    for name, tk in CRYPTO:
        p, c = alt_data.get(tk, (None, None))
        alt_rows.append([name, f"${p:,.0f}" if p else "N/A", _c(c)])
    for name, tk in REITS + INVITS:
        p, c = alt_data.get(tk, (None, None))
        alt_rows.append([name, f"Rs {p:,.2f}" if p else "N/A", _c(c)])
    _tbl("5. Alternative assets", ["Asset", "Price", "1D"], alt_rows)

    # 6. Volatility
    vix_rows = []
    for name, tk in VOL:
        p, c = vix_data.get(tk, (None, None))
        vix_rows.append([name, f"{p:.2f}" if p else "N/A", _c(c)])
    _tbl("6. Volatility", ["Indicator", "Level", "1D"], vix_rows)

    # 7. Macro
    macro_rows = []
    for sid, label, suffix in [("DGS10", "US 10Y Yield", "%"),
                                ("CPIAUCSL", "US CPI Index", ""),
                                ("UNRATE", "US Unemployment", "%"),
                                ("INDIRLTLT01STM", "India 10Y Yield", "%")]:
        v = fred_val(sid)
        if v: macro_rows.append([label, f"{v:.2f}{suffix}"])
    if macro_rows:
        _tbl("7. Macro indicators", ["Indicator", "Latest"], macro_rows)

    # Footer
    el.append(Spacer(1, 12))
    el.append(Paragraph(
        f'Live dashboard: <a href="{DASHBOARD_URL}" color="blue">'
        f'<u>{DASHBOARD_URL}</u></a>',
        ParagraphStyle("foot", fontName="Helvetica", fontSize=8,
                       textColor=colors.grey)))
    el.append(Paragraph(f"Generated {stamp}", ParagraphStyle(
        "foot2", fontName="Helvetica", fontSize=7, textColor=colors.grey)))

    doc.build(el)
    return bio.getvalue()


def send_email(pdf_bytes, summary_lines):
    if not all([GMAIL_USER, GMAIL_APP_PWD, MAIL_TO]):
        print("Missing email config."); return False

    today = dt.date.today().strftime("%d %b %Y")
    subject = f"Daily Market Dashboard — {today}"

    msg = MIMEMultipart("mixed")
    msg["From"] = GMAIL_USER
    msg["To"] = ", ".join(MAIL_TO)
    msg["Subject"] = subject

    bullets = "".join(f"<li style='margin:4px 0'>{s}</li>" for s in summary_lines)
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1E2761;margin-bottom:4px">Daily Market Dashboard</h2>
      <p style="color:#888;font-size:13px;margin-top:0">{today} &middot; 9:20 AM IST</p>
      <div style="background:#f4f6f9;border-radius:8px;padding:16px 20px;margin:16px 0">
        <h3 style="margin:0 0 8px;font-size:14px;color:#1E2761">What matters today</h3>
        <ul style="margin:0;padding-left:18px;color:#333;font-size:14px;line-height:1.8">
          {bullets}
        </ul>
      </div>
      <a href="{DASHBOARD_URL}"
         style="display:inline-block;background:#1E2761;color:#ffffff;
                padding:10px 24px;border-radius:6px;text-decoration:none;
                font-size:14px;font-weight:600;margin:8px 0">
        Open live dashboard
      </a>
      <br>
      <a href="{DASHBOARD_URL}"
         style="font-size:12px;color:#1E2761;margin-top:4px;display:inline-block">
        {DASHBOARD_URL}
      </a>
      <p style="color:#999;font-size:12px;margin-top:16px">
        Full report with charts attached as PDF.
      </p>
    </div>
    """
    alt = MIMEMultipart("alternative")
    plain = f"Market Dashboard — {today}\n\n"
    plain += "\n".join(f"  * {s}" for s in summary_lines)
    plain += f"\n\nDashboard: {DASHBOARD_URL}\nPDF attached."
    alt.attach(MIMEText(plain, "plain"))
    alt.attach(MIMEText(html, "html"))
    msg.attach(alt)

    part = MIMEBase("application", "octet-stream")
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    fname = f"market-dashboard-{dt.date.today().isoformat()}.pdf"
    part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
    msg.attach(part)

    try:
    print("Connecting to Gmail...")
    print(f"GMAIL_USER: {GMAIL_USER}")
    print(f"MAIL_TO: {MAIL_TO}")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        print("Connected.")
        server.login(GMAIL_USER, GMAIL_APP_PWD)
        print("Login successful.")

        server.sendmail(GMAIL_USER, MAIL_TO, msg.as_string())
        print("Email successfully sent!")

    return True

except Exception as e:
    import traceback
    traceback.print_exc()
    raise


if __name__ == "__main__":
    print(f"=== Market Dashboard Report ===")
    print(f"Time: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Dashboard: {DASHBOARD_URL}\n")

    print("Fetching equities...")
    eq_data = {}
    for _, name, tk in EQUITIES:
        eq_data[tk] = yahoo_price(tk)
        p, c = eq_data[tk]
        if p: print(f"  {name}: {p:,.2f} ({c:+.2f}%)")
        else: print(f"  {name}: FAILED")

    print("\nFetching FX...")
    fx_data = {}
    for name, tk in FX_PAIRS:
        fx_data[tk] = yahoo_price(tk)

    print("Fetching commodities...")
    cmd_data = {}
    for name, tk, _ in COMMODITIES_CFG:
        cmd_data[tk] = yahoo_price(tk)

    print("Fetching alt assets...")
    alt_data = {}
    for name, tk in CRYPTO + REITS + INVITS:
        alt_data[tk] = yahoo_price(tk)

    print("Fetching VIX...")
    vix_data = {}
    for name, tk in VOL:
        vix_data[tk] = yahoo_price(tk)

    gold = gold_india()
    print(f"\nGold 24K: Rs {gold:,.0f}/g" if gold else "\nGold: scrape failed")

    print("\nFetching yields...")
    _ecb = ecb_yield()
    _jgb = japan_jgb()
    us10 = fred_val("DGS10"); us2 = fred_val("DGS2"); us1 = fred_val("DGS1")
    in10 = fred_val("INDIRLTLT01STM")
    uk10 = fred_val("IRLTLT01GBM156N")
    rates = {
        "India": {"1Y": None, "2Y": None, "10Y": in10},
        "US": {"1Y": us1, "2Y": us2, "10Y": us10},
        "UK": {"1Y": None, "2Y": None, "10Y": uk10},
        "Germany": _ecb,
        "Japan": _jgb,
    }

    print("\nBuilding yield chart...")
    chart_buf = build_yield_chart()
    print(f"  Chart: {'OK' if chart_buf else 'SKIPPED (no FRED data)'}")

    summary = build_summary(eq_data, fx_data, gold)
    print("\nSummary:")
    for s in summary: print(f"  * {s}")

    pdf = build_pdf(eq_data, fx_data, cmd_data, vix_data, alt_data,
                    gold, rates, summary, chart_buf)
    print(f"\nPDF: {len(pdf):,} bytes ({len(pdf)//1024} KB)")

    fname = f"market-dashboard-{dt.date.today().isoformat()}.pdf"
    with open(fname, "wb") as f: f.write(pdf)
    print(f"Saved: {fname}")

    if GMAIL_USER:
        send_email(pdf, summary)
    else:
        print("\nNo GMAIL_USER set. To test email, set:")
        print("  export GMAIL_USER=you@gmail.com")
        print("  export GMAIL_APP_PWD=xxxx-xxxx-xxxx-xxxx")
        print("  export MAIL_TO=recipient@gmail.com")
