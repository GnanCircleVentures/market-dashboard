#!/usr/bin/env python3
"""
Daily Market Dashboard
======================
Fetches market data (free, via Yahoo Finance) and builds a one-page HTML dashboard.

WHAT IS AUTOMATIC  : equity indices, US 10Y yield, FX, commodities, crypto, VIX.
WHAT YOU EDIT BY HAND: the CONFIG section below (policy rates, FD rates, etc.).
                       These change rarely, so update them every few weeks.

Run it:  python dashboard.py
Output:  output/dashboard.html  (open in any browser)
         output/history/YYYY-MM-DD.csv  (a daily snapshot, so you build history)
"""

import os
import sys
import datetime as dt

try:
    import yfinance as yf
except ImportError:
    sys.exit("Missing library. Run:  pip install -r requirements.txt")

# Optional: US macro from FRED. Leave key as "" to skip it.
# Get a free key in 1 minute: https://fredaccount.stlouisfed.org/apikeys
FRED_API_KEY = ""

# ----------------------------------------------------------------------------
# 1. CONFIG  --  EDIT THE THINGS IN THIS BLOCK BY HAND
# ----------------------------------------------------------------------------
# These have no reliable free API, so type the current value and the date you
# checked it. They change rarely (policy rates, FD rates, etc.).

MANUAL_LAST_UPDATED = "2026-06-04"  # change when you refresh the numbers below

CENTRAL_BANK_RATES = {
    "RBI Repo Rate":     "6.50%",
    "US Fed Funds Rate": "4.25-4.50%",
    "ECB Deposit Rate":  "2.00%",
    "BoE Base Rate":     "4.25%",
}

FD_RATES_1YR = {   # 1-year fixed deposit, general public
    "SBI":        "6.80%",
    "HDFC Bank":  "6.60%",
    "ICICI Bank": "6.70%",
    "Axis Bank":  "6.70%",
    "Kotak":      "7.10%",
}

BORROWING_RATES = {
    "SBI MCLR (1Y)":           "9.00%",
    "Home Loan Benchmark":     "8.50%",
    "Corporate Loan Benchmark":"9.25%",
}

# India bond yields + India macro: no clean free daily API. Update manually,
# or pull from investing.com / tradingeconomics when you refresh.
INDIA_BOND_YIELDS = {        # leave as "—" if you don't track it
    "India 2Y G-Sec":  "—",
    "India 10Y G-Sec": "6.90%",
}

INDIA_MACRO = {
    "India CPI (YoY)":      "—",
    "India WPI (YoY)":      "—",
    "India GDP Growth":     "—",
    "India Forex Reserves": "—",
}

KEY_EVENTS_TODAY = [         # type today's calendar items, or leave empty
    # "RBI Policy Meeting",
    # "US Non-Farm Payrolls",
]

# Alert thresholds for the summary (tweak to your taste)
THRESHOLDS = {
    "India VIX high": 20.0,     # flag if India VIX above this
    "CBOE VIX high":  25.0,
    "USD/INR high":   86.0,     # flag if rupee weaker than this
}

# ----------------------------------------------------------------------------
# 2. TICKERS  --  pulled automatically from Yahoo Finance
# ----------------------------------------------------------------------------
EQUITY_INDICES = [
    ("India",     "Nifty 50",           "^NSEI"),
    ("India",     "Sensex",             "^BSESN"),
    ("US",        "S&P 500",            "^GSPC"),
    ("US",        "Nasdaq",             "^IXIC"),
    ("US",        "Dow Jones",          "^DJI"),
    ("Europe",    "Euro Stoxx 50",      "^STOXX50E"),
    ("UK",        "FTSE 100",           "^FTSE"),
    ("China",     "Shanghai Composite", "000001.SS"),
    ("Hong Kong", "Hang Seng",          "^HSI"),
    ("Japan",     "Nikkei 225",         "^N225"),
]

CURRENCIES = [
    ("USD/INR", "INR=X"),
    ("EUR/INR", "EURINR=X"),
    ("GBP/INR", "GBPINR=X"),
    ("JPY/INR", "JPYINR=X"),
    ("USD/CNY", "CNY=X"),
]

COMMODITIES = [   # all in USD except gold-in-rupees which we compute
    ("Gold (USD/oz)", "GC=F"),
    ("Silver (USD/oz)","SI=F"),
    ("Brent Crude",   "BZ=F"),
    ("WTI Crude",     "CL=F"),
    ("Natural Gas",   "NG=F"),
    ("Copper (USD/lb)","HG=F"),
]

CRYPTO = [
    ("Bitcoin",  "BTC-USD"),
    ("Ethereum", "ETH-USD"),
]

VOLATILITY = [
    ("India VIX", "^INDIAVIX"),
    ("CBOE VIX",  "^VIX"),
]

US_10Y_TICKER = "^TNX"   # CBOE 10-Year Treasury Note Yield


# ----------------------------------------------------------------------------
# 3. FETCH HELPERS
# ----------------------------------------------------------------------------
def fetch_one(ticker):
    """Return dict(price, prev, year_start) or None on failure.
    Wrapped so one bad ticker never crashes the whole run."""
    try:
        hist = yf.Ticker(ticker).history(period="ytd")
        closes = hist["Close"].dropna()
        if len(closes) < 2:
            # fall back to a 5-day window if YTD came back too short
            hist = yf.Ticker(ticker).history(period="5d")
            closes = hist["Close"].dropna()
        if len(closes) < 2:
            return None
        return {
            "price":      float(closes.iloc[-1]),
            "prev":       float(closes.iloc[-2]),
            "year_start": float(closes.iloc[0]),
        }
    except Exception as e:
        print(f"  ! {ticker}: {e}")
        return None


def pct(new, old):
    if old in (None, 0):
        return None
    return (new / old - 1.0) * 100.0


def fmt_num(x, decimals=2):
    if x is None:
        return "—"
    return f"{x:,.{decimals}f}"


def fmt_pct(x):
    if x is None:
        return "—"
    arrow = "\u25B2" if x >= 0 else "\u25BC"   # ▲ ▼
    return f"{arrow}{abs(x):.2f}%"


def fetch_fred(series_id):
    """Optional US macro via FRED. Returns latest value string or None."""
    if not FRED_API_KEY:
        return None
    try:
        import urllib.request, json
        url = (f"https://api.stlouisfed.org/fred/series/observations?"
               f"series_id={series_id}&api_key={FRED_API_KEY}&file_type=json"
               f"&sort_order=desc&limit=1")
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.load(r)
        return data["observations"][0]["value"]
    except Exception as e:
        print(f"  ! FRED {series_id}: {e}")
        return None


# ----------------------------------------------------------------------------
# 4. HTML BUILDING
# ----------------------------------------------------------------------------
def color_cell(pct_val):
    if pct_val is None:
        return ""
    return "pos" if pct_val >= 0 else "neg"


def row(cols, classes=None):
    classes = classes or [""] * len(cols)
    tds = "".join(f'<td class="{c}">{v}</td>' for v, c in zip(cols, classes))
    return f"<tr>{tds}</tr>"


def table(headers, rows_html, title=None):
    head = "".join(f"<th>{h}</th>" for h in headers)
    t = f'<table><thead><tr>{head}</tr></thead><tbody>{rows_html}</tbody></table>'
    if title:
        t = f"<h2>{title}</h2>" + t
    return t


def build_html(data):
    now = dt.datetime.now().strftime("%A, %d %B %Y  %H:%M")

    # ---- Section 1: Equities ----
    eq_rows = ""
    eq_perf = []  # (name, 1d) for best/worst insight
    for region, name, tk in EQUITY_INDICES:
        d = data["equity"].get(tk)
        if d:
            c1 = pct(d["price"], d["prev"])
            cy = pct(d["price"], d["year_start"])
            eq_perf.append((name, c1))
            eq_rows += row(
                [region, name, fmt_num(d["price"]), fmt_pct(c1), fmt_pct(cy)],
                ["", "", "", color_cell(c1), color_cell(cy)],
            )
        else:
            eq_rows += row([region, name, "—", "—", "—"])
    equities = table(["Region", "Index", "Current", "1D", "YTD"], eq_rows,
                     "1 &middot; Global Equity Markets")

    # ---- Section 4: Currencies ----
    fx_rows = ""
    for name, tk in CURRENCIES:
        d = data["fx"].get(tk)
        if d:
            c1 = pct(d["price"], d["prev"])
            fx_rows += row([name, fmt_num(d["price"], 4), fmt_pct(c1)],
                           ["", "", color_cell(c1)])
        else:
            fx_rows += row([name, "—", "—"])
    currencies = table(["Pair", "Current", "1D"], fx_rows,
                       "4 &middot; Currencies")

    # ---- Section 5: Commodities (+ gold in rupees) ----
    cm_rows = ""
    gold_usd = data["commodity"].get("GC=F")
    usdinr   = data["fx"].get("INR=X")
    if gold_usd and usdinr:
        # 1 troy oz = 31.1035 g  ->  price per 10g in INR
        gold_inr_10g = gold_usd["price"] * usdinr["price"] / 31.1035 * 10
        prev_inr_10g = gold_usd["prev"] * usdinr["prev"] / 31.1035 * 10
        c1 = pct(gold_inr_10g, prev_inr_10g)
        cm_rows += row(["Gold (INR/10g, approx)", fmt_num(gold_inr_10g, 0), fmt_pct(c1)],
                       ["", "", color_cell(c1)])
    for name, tk in COMMODITIES:
        d = data["commodity"].get(tk)
        if d:
            c1 = pct(d["price"], d["prev"])
            cm_rows += row([name, fmt_num(d["price"]), fmt_pct(c1)],
                           ["", "", color_cell(c1)])
        else:
            cm_rows += row([name, "—", "—"])
    commodities = table(["Commodity", "Current", "1D"], cm_rows,
                        "5 &middot; Commodities")

    # ---- Section 6: Crypto ----
    cr_rows = ""
    for name, tk in CRYPTO:
        d = data["crypto"].get(tk)
        if d:
            c1 = pct(d["price"], d["prev"])
            cr_rows += row([name, fmt_num(d["price"]), fmt_pct(c1)],
                           ["", "", color_cell(c1)])
        else:
            cr_rows += row([name, "—", "—"])
    crypto = table(["Asset", "Current (USD)", "1D"], cr_rows,
                   "6 &middot; Alternative Assets (Crypto)")

    # ---- Section 7: Volatility & US 10Y ----
    vol_rows = ""
    for name, tk in VOLATILITY:
        d = data["vol"].get(tk)
        if d:
            chg = d["price"] - d["prev"]
            cls = "pos" if chg <= 0 else "neg"   # falling vol = green
            vol_rows += row([name, fmt_num(d["price"]), f"{chg:+.2f}"], ["", "", cls])
        else:
            vol_rows += row([name, "—", "—"])
    us10 = data["vol"].get(US_10Y_TICKER)
    if us10:
        chg_bps = (us10["price"] - us10["prev"]) * 100  # percentage-points -> bps
        cls = "neg" if chg_bps > 0 else "pos"            # rising yields flagged
        vol_rows += row(["US 10Y Yield (%)", fmt_num(us10["price"]),
                         f"{chg_bps:+.0f} bps"], ["", "", cls])
    volatility = table(["Indicator", "Current", "1D Change"], vol_rows,
                       "7 &middot; Volatility &amp; Rates")

    # ---- Manual sections ----
    cb_rows = "".join(row([k, v]) for k, v in CENTRAL_BANK_RATES.items())
    central = table(["Central Bank", "Policy Rate"], cb_rows,
                    "2 &middot; Central Bank Rates")

    yld_rows = "".join(row([k, v]) for k, v in INDIA_BOND_YIELDS.items())
    ind_yields = table(["Instrument", "Yield"], yld_rows,
                       "2b &middot; India Bond Yields")

    fd_rows = "".join(row([k, v]) for k, v in FD_RATES_1YR.items())
    fd = table(["Bank", "1Y FD Rate"], fd_rows,
               "3 &middot; Bank FD Rates (1Y)")

    bo_rows = "".join(row([k, v]) for k, v in BORROWING_RATES.items())
    borrow = table(["Metric", "Rate"], bo_rows, "3b &middot; Borrowing Rates")

    # ---- Section 8: Macro ----
    macro = dict(INDIA_MACRO)
    if FRED_API_KEY:
        us_cpi = fetch_fred("CPIAUCSL")
        us_unemp = fetch_fred("UNRATE")
        macro["US CPI Index (FRED)"] = us_cpi or "—"
        macro["US Unemployment % (FRED)"] = us_unemp or "—"
    else:
        macro["US CPI"] = "— (add FRED key)"
        macro["US Unemployment"] = "— (add FRED key)"
    mc_rows = "".join(row([k, v]) for k, v in macro.items())
    macro_tbl = table(["Indicator", "Latest"], mc_rows,
                      "8 &middot; Macro Indicators")

    # ---- Section 9: Summary cards + alerts (TOP of page) ----
    def summary_card(label, ticker_dict, tk, fx=False):
        d = ticker_dict.get(tk)
        if not d:
            return f'<div class="card"><div class="lbl">{label}</div><div class="val">—</div></div>'
        c1 = pct(d["price"], d["prev"])
        cls = color_cell(c1)
        dec = 4 if fx else 2
        return (f'<div class="card"><div class="lbl">{label}</div>'
                f'<div class="val">{fmt_num(d["price"], dec)}</div>'
                f'<div class="chg {cls}">{fmt_pct(c1)}</div></div>')

    cards = (
        summary_card("Nifty 50", data["equity"], "^NSEI")
        + summary_card("S&P 500", data["equity"], "^GSPC")
        + summary_card("USD/INR", data["fx"], "INR=X", fx=True)
        + summary_card("Gold USD/oz", data["commodity"], "GC=F")
        + summary_card("Brent", data["commodity"], "BZ=F")
        + summary_card("Bitcoin", data["crypto"], "BTC-USD")
        + summary_card("India VIX", data["vol"], "^INDIAVIX")
    )

    # alerts
    alerts = []
    iv = data["vol"].get("^INDIAVIX")
    if iv and iv["price"] > THRESHOLDS["India VIX high"]:
        alerts.append(f"India VIX elevated at {iv['price']:.1f}")
    cv = data["vol"].get("^VIX")
    if cv and cv["price"] > THRESHOLDS["CBOE VIX high"]:
        alerts.append(f"CBOE VIX elevated at {cv['price']:.1f}")
    fx_inr = data["fx"].get("INR=X")
    if fx_inr and fx_inr["price"] > THRESHOLDS["USD/INR high"]:
        alerts.append(f"USD/INR weak at {fx_inr['price']:.2f}")
    if us10:
        bps = (us10["price"] - us10["prev"]) * 100
        if abs(bps) >= 5:
            alerts.append(f"US 10Y moved {bps:+.0f} bps")
    # best / worst equity
    valid = [(n, c) for n, c in eq_perf if c is not None]
    if valid:
        best = max(valid, key=lambda x: x[1])
        worst = min(valid, key=lambda x: x[1])
        alerts.append(f"Best: {best[0]} {fmt_pct(best[1])}")
        alerts.append(f"Worst: {worst[0]} {fmt_pct(worst[1])}")

    alert_html = "".join(f"<li>{a}</li>" for a in alerts) or "<li>No threshold breaches today.</li>"
    events_html = "".join(f"<li>{e}</li>" for e in KEY_EVENTS_TODAY) or "<li>None entered.</li>"

    # ---- assemble ----
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Daily Market Dashboard</title>
<style>
:root {{ --bg:#0f1419; --panel:#1a2230; --line:#2a3548; --txt:#e6edf3;
        --muted:#8b98a9; --pos:#2ea043; --neg:#f85149; --accent:#4493f8; }}
* {{ box-sizing:border-box; }}
body {{ background:var(--bg); color:var(--txt); margin:0;
        font:14px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif; }}
.wrap {{ max-width:1100px; margin:0 auto; padding:24px; }}
header {{ display:flex; justify-content:space-between; align-items:baseline;
          border-bottom:2px solid var(--accent); padding-bottom:10px; margin-bottom:18px; }}
h1 {{ font-size:22px; margin:0; }}
.ts {{ color:var(--muted); font-size:12px; }}
h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.06em;
      color:var(--accent); margin:22px 0 8px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
          gap:10px; margin-bottom:6px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px;
         padding:12px; }}
.card .lbl {{ color:var(--muted); font-size:11px; text-transform:uppercase; }}
.card .val {{ font-size:20px; font-weight:600; margin:4px 0; }}
.card .chg {{ font-size:13px; font-weight:600; }}
.grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
.box {{ background:var(--panel); border:1px solid var(--line); border-radius:8px;
        padding:12px 16px; }}
.box h3 {{ margin:0 0 6px; font-size:13px; color:var(--accent); }}
ul {{ margin:4px 0; padding-left:18px; }}
table {{ width:100%; border-collapse:collapse; margin-bottom:8px; }}
th, td {{ text-align:right; padding:6px 10px; border-bottom:1px solid var(--line); }}
th:first-child, td:first-child,
th:nth-child(2), td:nth-child(2) {{ text-align:left; }}
th {{ color:var(--muted); font-weight:500; font-size:12px; }}
.pos {{ color:var(--pos); }}
.neg {{ color:var(--neg); }}
.cols {{ columns:2; column-gap:18px; }}
.cols > div {{ break-inside:avoid; }}
footer {{ color:var(--muted); font-size:11px; margin-top:24px;
          border-top:1px solid var(--line); padding-top:10px; }}
@media (max-width:720px) {{ .grid2,.cols {{ grid-template-columns:1fr; columns:1; }} }}
</style></head>
<body><div class="wrap">
<header>
  <h1>Daily Market Dashboard</h1>
  <span class="ts">Generated {now}</span>
</header>

<h2>9 &middot; Management Summary</h2>
<div class="cards">{cards}</div>
<div class="grid2" style="margin-top:12px;">
  <div class="box"><h3>Alerts &amp; Highlights</h3><ul>{alert_html}</ul></div>
  <div class="box"><h3>Key Events Today</h3><ul>{events_html}</ul></div>
</div>

{equities}

<div class="cols">
  <div>{central}</div>
  <div>{ind_yields}</div>
  <div>{fd}</div>
  <div>{borrow}</div>
  <div>{currencies}</div>
  <div>{volatility}</div>
</div>

{commodities}
{crypto}
{macro_tbl}

<footer>
Auto data via Yahoo Finance (delayed). Manual rates last updated {MANUAL_LAST_UPDATED}.
Gold INR/10g is a spot approximation and excludes import duty &amp; GST, so it differs
from MCX. Yields/VIX changes shown in absolute terms. Not investment advice.
</footer>
</div></body></html>"""


# ----------------------------------------------------------------------------
# 5. MAIN
# ----------------------------------------------------------------------------
def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(here, "output")
    hist_dir = os.path.join(out_dir, "history")
    os.makedirs(hist_dir, exist_ok=True)

    print("Fetching market data (this takes ~30-60s)...")
    data = {"equity": {}, "fx": {}, "commodity": {}, "crypto": {}, "vol": {}}

    for _, _, tk in EQUITY_INDICES:
        data["equity"][tk] = fetch_one(tk)
    for _, tk in CURRENCIES:
        data["fx"][tk] = fetch_one(tk)
    for _, tk in COMMODITIES:
        data["commodity"][tk] = fetch_one(tk)
    for _, tk in CRYPTO:
        data["crypto"][tk] = fetch_one(tk)
    for _, tk in VOLATILITY:
        data["vol"][tk] = fetch_one(tk)
    data["vol"][US_10Y_TICKER] = fetch_one(US_10Y_TICKER)

    html = build_html(data)
    out_path = os.path.join(out_dir, "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard written to: {out_path}")

    # Save a CSV snapshot so you build a daily history
    today = dt.date.today().isoformat()
    csv_path = os.path.join(hist_dir, f"{today}.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("ticker,price,prev,year_start\n")
        for group in data.values():
            for tk, d in group.items():
                if d:
                    f.write(f"{tk},{d['price']},{d['prev']},{d['year_start']}\n")
    print(f"Snapshot saved to:    {csv_path}")


if __name__ == "__main__":
    main()
