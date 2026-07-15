#!/usr/bin/env python3
"""
send_report.py — Sends the daily market PDF via email.
Time-gated: only sends between 9:00-10:00 AM IST on scheduled runs.
"""
import datetime as dt, io, os, re, smtplib, sys, time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.dates as mdates
import pandas as pd, requests, yfinance as yf
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import report_pdf as _report_pdf   # the SAME builder the dashboard uses

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
now_ist = dt.datetime.now(IST)
trigger = os.environ.get("GITHUB_EVENT_NAME", "manual")

print(f"=== Daily Market Report ===")
print(f"IST:     {now_ist.strftime('%Y-%m-%d %H:%M:%S IST')}")
print(f"Trigger: {trigger}")

if trigger == "schedule":
    h = now_ist.hour
    if h < 9 or h >= 10:
        print(f"SKIPPED: {now_ist.strftime('%H:%M')} IST outside 9-10 AM window.")
        sys.exit(0)
    print(f"TIME GATE PASSED: {now_ist.strftime('%H:%M')} IST\n")
else:
    print("Manual trigger - sending regardless of time.\n")

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PWD = os.environ.get("GMAIL_APP_PWD", "")
MAIL_TO = [x.strip() for x in os.environ.get("MAIL_TO", "").split(",") if x.strip()]
FRED_KEY = os.environ.get("FRED_KEY", "")
DASH = "https://market-dashboard-7hsncprqzkfytpx7a8ishb.streamlit.app"
LOGO = os.path.join(os.path.dirname(__file__) or ".", "logo.png")
# Latest published India figures (no free live API) — keep in sync with app.py.
# (latest, period, previous) so the table can show the real month-on-month move.
LATEST_INDIA_GDP = ("7.70", "FY26", "6.60")
LATEST_INDIA_WPI = ("9.87", "Jun 2026", "9.68")
LATEST_INDIA_CPI = ("4.38", "Jun 2026", "3.93")
H = {"User-Agent": "Mozilla/5.0"}

EQ = [("India","Nifty 50","^NSEI"),("India","Sensex","^BSESN"),
      ("US","S&P 500","^GSPC"),("US","Nasdaq","^IXIC"),("US","Dow Jones","^DJI"),
      ("Germany","DAX","^GDAXI"),("UK","FTSE 100","^FTSE"),
      ("China","Shanghai Composite","000001.SS"),
      ("Hong Kong","Hang Seng","^HSI"),("Japan","Nikkei 225","^N225")]
FX = [("USD/INR","INR=X"),("EUR/INR","EURINR=X"),("GBP/INR","GBPINR=X"),
      ("JPY/INR","JPYINR=X"),("USD/CNY","CNY=X")]
CM = [("Gold","GC=F","USD/oz"),("Silver","SI=F","USD/oz"),
      ("Brent Crude","BZ=F","USD/bbl"),("WTI Crude","CL=F","USD/bbl"),
      ("Natural Gas","NG=F","USD/MMBtu"),("Copper","HG=F","USD/lb"),
      ("Aluminum","ALI=F","USD/t")]
CR = [("Bitcoin","BTC-USD"),("Ethereum","ETH-USD")]
# REITs and InvITs removed per request
VX = [("India VIX","^INDIAVIX"),("US VIX (CBOE)","^VIX")]
CC = {"India":"#1a73e8","US":"#ff3d00","UK":"#7c4dff","Germany":"#ff9100","Japan":"#00bfa5"}

def yp(tk):
    """Back-compat single-horizon fetch (price, 1D%) used by the summary."""
    r = yq(tk)
    return (r["price"], r["d1"]) if r else (None, None)


def yq(tk):
    """Multi-horizon fetch — identical maths to the dashboard's yahoo():
    price + d1/m1/m3/m6/y1/y5/ytd % and the base price for each horizon."""
    for _ in range(3):
        try:
            h = yf.Ticker(tk).history(period="6y")["Close"].dropna()
            if len(h) < 2:
                h = yf.Ticker(tk).history(period="5d")["Close"].dropna()
            if len(h) < 2:
                time.sleep(2); continue
            p, prev = float(h.iloc[-1]), float(h.iloc[-2])
            rec = {"price": round(p, 2), "d1": round((p/prev-1)*100, 2),
                   "base": {"d1": prev}}
            this_year = h[h.index.year == h.index[-1].year]
            ys = float(this_year.iloc[0]) if len(this_year) else float(h.iloc[0])
            rec["ytd"] = round((p/ys-1)*100, 2); rec["base"]["ytd"] = ys
            last = h.index[-1]
            for lbl, days in (("m1",30),("m3",91),("m6",182),("y1",365),("y5",1826)):
                past = h[h.index <= last - pd.Timedelta(days=days)]
                b = float(past.iloc[-1]) if len(past) else None
                rec[lbl] = round((p/b-1)*100, 2) if b else None
                rec["base"][lbl] = b
            return rec
        except Exception:
            time.sleep(2)
    return None

def fv(s):
    if not FRED_KEY: return None
    try:
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id={s}&api_key={FRED_KEY}&file_type=json&sort_order=desc&limit=5"
        for o in requests.get(url,headers=H,timeout=20).json().get("observations",[]):
            v = o.get("value")
            if v not in (".",""): return float(v)
    except: pass
    return None

def fh(s):
    if not FRED_KEY: return []
    try:
        st = (dt.date.today()-dt.timedelta(days=1825)).isoformat()
        url = f"https://api.stlouisfed.org/fred/series/observations?series_id={s}&api_key={FRED_KEY}&file_type=json&observation_start={st}&sort_order=asc"
        return [(o["date"],float(o["value"])) for o in requests.get(url,headers=H,timeout=20).json().get("observations",[]) if o.get("value") not in (".","")] 
    except: return []

def gold_in():
    import html as _h
    try:
        r = requests.get("https://www.goodreturns.in/gold-rates/",headers=H,timeout=15)
        if r.status_code==200:
            t = re.sub(r"\s+"," ",_h.unescape(re.sub(r"<[^>]+>"," ",re.sub(r"<script.*?</script>|<style.*?</style>"," ",r.text,flags=re.S|re.I))))
            m = re.search(r"([\d,]{3,})\s*per\s*gram\s*for\s*24",t,re.I)
            if m:
                v = float(m.group(1).replace(",",""))
                if 1000<=v<=100000: return v
    except: pass
    return None

def ecb():
    out = {}
    for t in ("1Y","2Y","10Y"):
        try:
            r = requests.get(f"https://data-api.ecb.europa.eu/service/data/YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_{t}?lastNObservations=1&format=csvdata",headers=H,timeout=20)
            if r.status_code==200:
                ls = r.text.strip().splitlines()
                if len(ls)>=2:
                    cs = ls[0].split(","); vi = cs.index("OBS_VALUE") if "OBS_VALUE" in cs else -1
                    la = ls[-1].split(",")
                    if vi>=0 and vi<len(la): out[t] = round(float(la[vi]),2)
        except: pass
    return out

def jgb():
    try:
        r = requests.get("https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv",headers=H,timeout=20)
        if r.status_code!=200: return {}
        ls = [l for l in r.text.splitlines() if l.strip()]
        hi = next((i for i,l in enumerate(ls) if l.split(",")[0].strip()=="Date"),None)
        if hi is None: return {}
        hd = [x.strip() for x in ls[hi].split(",")]; ix = {n:j for j,n in enumerate(hd)}
        rows = [l.split(",") for l in ls[hi+1:] if re.match(r"^\s*\d{4}/",l.split(",")[0])]
        if not rows: return {}
        la = rows[-1]
        def v(c):
            try: return float(la[ix[c]])
            except: return None
        return {"1Y":v("1Y"),"2Y":v("2Y"),"10Y":v("10Y")}
    except: return {}

def fh_series(sid, years=6):
    """FRED history as a pandas Series (date-indexed), for change maths."""
    d = fh(sid) if years == 5 else None
    if d is None:
        if not FRED_KEY:
            return None
        try:
            st_ = (dt.date.today() - dt.timedelta(days=int(years*365))).isoformat()
            url = (f"https://api.stlouisfed.org/fred/series/observations?"
                   f"series_id={sid}&api_key={FRED_KEY}&file_type=json"
                   f"&observation_start={st_}&sort_order=asc")
            d = [(o["date"], float(o["value"]))
                 for o in requests.get(url, headers=H, timeout=20).json().get("observations", [])
                 if o.get("value") not in (".", "")]
        except Exception:
            return None
    if not d:
        return None
    return pd.Series([v for _, v in d],
                     index=pd.to_datetime([x for x, _ in d])).sort_index()


def policy_changes(sid):
    """Policy rate level + bps change over 1M/3M/6M/1Y/5Y (mirrors dashboard)."""
    s = fh_series(sid, years=5)
    if s is None or not len(s):
        return None, {}
    latest = float(s.iloc[-1]); now = s.index[-1]
    out = {}
    for lbl, days in (("m1",30),("m3",91),("m6",182),("y1",365),("y5",1826)):
        prior = s[s.index <= now - pd.Timedelta(days=days)]
        if len(prior):
            out[lbl] = round((latest - float(prior.iloc[-1])) * 100, 0)
    return latest, out


def macro_yoy(sid):
    """Level + YoY % + observation month (mirrors the dashboard)."""
    s = fh_series(sid, years=6)
    if s is None or not len(s):
        return None, None, None
    level = float(s.iloc[-1]); last = s.index[-1]
    prior = s[s.index <= last - pd.Timedelta(days=365)]
    yoy = ((level/float(prior.iloc[-1]) - 1)*100
           if len(prior) and float(prior.iloc[-1]) else None)
    return level, yoy, last.strftime("%b %Y")


def build_chart():
    series = [("India","INDIRLTLT01STM"),("US","IRLTLT01USM156N"),
              ("UK","IRLTLT01GBM156N"),("Germany","IRLTLT01DEM156N"),("Japan","IRLTLT01JPM156N")]
    fig, ax = plt.subplots(figsize=(7.4,3.2),dpi=150)
    wm = {"India":2.0,"US":2.2,"UK":1.4,"Germany":1.4,"Japan":1.4}
    has = False
    for nm,sid in series:
        d = fh(sid)
        if not d: continue
        has = True
        dates = [dt.datetime.strptime(x,"%Y-%m-%d") for x,_ in d]
        vals = [v for _,v in d]
        col = CC.get(nm,"#333")
        ln, = ax.plot(dates,vals,label=nm,linewidth=wm.get(nm,1.5),color=col)
        for i in range(0,len(dates),3):
            if i<len(vals):
                ax.plot(dates[i],vals[i],"o",color=col,markersize=2.8)
                ax.annotate(f"{vals[i]:.2f}",(dates[i],vals[i]),textcoords="offset points",
                            xytext=(0,5),ha="center",fontsize=4,color=col,fontweight="bold")
    if not has: plt.close(fig); return None
    ax.set_title("10Y Government Bond Yield - 5-Year History",fontsize=9,fontweight="bold")
    ax.tick_params(labelsize=6)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax.legend(fontsize=7,loc="upper left",framealpha=0.8); ax.grid(alpha=.2)
    fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf,format="png",bbox_inches="tight"); plt.close(fig); buf.seek(0)
    return buf

def summary(eq,fx,g):
    ls = []
    np_,nc = eq.get("^NSEI",(None,None)); _,sc = eq.get("^BSESN",(None,None))
    if np_ and nc is not None:
        s = f"Nifty 50 at {np_:,.0f} ({nc:+.2f}%)"
        if sc is not None: s += f", Sensex {sc:+.2f}%"
        ls.append(s)
    mv = [(n,r,c) for r,n,t in EQ for p,c in [eq.get(t,(None,None))] if c is not None]
    if mv:
        b = max(mv,key=lambda x:x[2]); w = min(mv,key=lambda x:x[2])
        ls.append(f"{b[0]} ({b[1]}) led ({b[2]:+.2f}%); {w[0]} ({w[1]}) lagged ({w[2]:+.2f}%)")
    fp,fc = fx.get("INR=X",(None,None))
    if fp: ls.append(f"USD/INR {fp:.2f}" + (f" ({fc:+.2f}%)" if fc else ""))
    if g: ls.append(f"Gold 24K Rs {g*10:,.0f}/10g")
    return ls

def send_email(pdf,summ):
    if not GMAIL_USER: print("ERROR: GMAIL_USER not set"); sys.exit(1)
    if not GMAIL_APP_PWD: print("ERROR: GMAIL_APP_PWD not set"); sys.exit(1)
    if not MAIL_TO: print("ERROR: MAIL_TO not set"); sys.exit(1)
    print(f"\nFrom: {GMAIL_USER}\nTo: {MAIL_TO}")
    today = dt.date.today().strftime("%d %b %Y")
    msg = MIMEMultipart("mixed")
    msg["From"]=GMAIL_USER; msg["To"]=", ".join(MAIL_TO)
    msg["Subject"]=f"Daily Market Dashboard - {today}"
    bullets = "".join(f"<li style='margin:4px 0'>{s}</li>" for s in summ)
    html = f"""<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1E2761;margin-bottom:4px">Daily Market Dashboard</h2>
      <p style="color:#888;font-size:13px;margin-top:0">{today} - 9:30 AM IST</p>
      <div style="background:#f4f6f9;border-radius:8px;padding:16px 20px;margin:16px 0">
        <h3 style="margin:0 0 8px;font-size:14px;color:#1E2761">Biggest move</h3>
        <ul style="margin:0;padding-left:18px;color:#333;font-size:14px;line-height:1.8">{bullets}</ul>
      </div>
      <a href="{DASH}" style="display:inline-block;background:#1E2761;color:#fff;padding:10px 24px;border-radius:6px;text-decoration:none;font-size:14px;font-weight:600">Open live dashboard</a>
      <br><a href="{DASH}" style="font-size:12px;color:#1E2761;margin-top:6px;display:inline-block">{DASH}</a>
      <p style="color:#999;font-size:12px;margin-top:16px">Full report attached as PDF.</p>
    </div>"""
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText("\n".join(f"* {s}" for s in summ)+f"\n\nDashboard: {DASH}","plain"))
    alt.attach(MIMEText(html,"html")); msg.attach(alt)
    part = MIMEBase("application","octet-stream"); part.set_payload(pdf); encoders.encode_base64(part)
    part.add_header("Content-Disposition",f'attachment; filename="market-dashboard-{dt.date.today().isoformat()}.pdf"')
    msg.attach(part)
    print("Connecting to Gmail...")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com",465) as srv:
            print("Logging in..."); srv.login(GMAIL_USER,GMAIL_APP_PWD)
            print("Sending..."); srv.sendmail(GMAIL_USER,MAIL_TO,msg.as_string())
            print(f"SUCCESS: Email sent to {', '.join(MAIL_TO)}")
    except smtplib.SMTPAuthenticationError as e:
        print(f"AUTH FAILED: {e}\nFix: New App Password at https://myaccount.google.com/apppasswords"); sys.exit(1)
    except Exception as e:
        print(f"FAILED: {e}"); sys.exit(1)

if __name__ == "__main__":
    def _c(v):
        """Coloured % change cell — same markup the dashboard emits."""
        if v is None:
            return '<span class="muted">NA</span>'
        arrow = "\u25b2" if v >= 0 else "\u25bc"
        col = "var(--pos)" if v >= 0 else "var(--neg)"
        return f'<span style="color:{col}">{arrow} {abs(v):.2f}%</span>'

    def _cells(rec, labels):
        """Change cells across horizons — mirrors the dashboard's pcells()."""
        if not rec:
            return ['<span class="muted">NA</span>' for _ in labels]
        return [_c(rec.get(l)) for l in labels]

    def _r(d, k):
        v = d.get(k) if d else None
        return f"{v:.2f}%" if isinstance(v, (int, float)) else "N/A"

    print("Fetching equities...")
    eq = {}
    for _, n, t in EQ:
        eq[t] = yq(t)
        r = eq[t]
        print(f"  {n}: {r['price']:,.2f} ({r['d1']:+.2f}%)" if r else f"  {n}: FAILED")

    print("\nFetching FX, crypto, commodities, VIX...")
    fx = {t: yq(t) for _, t in FX}
    cry = {t: yq(t) for _, t in CR}
    cmd = {t: yq(t) for _, t, _ in CM}
    vix = {t: yq(t) for _, t in VX}
    g = gold_in()
    print(f"  Gold: Rs {g:,.0f}/g" if g else "  Gold: FAILED")

    print("\nFetching yields...")
    _e = ecb(); _j = jgb()
    rates = {"India": {"1Y": None, "2Y": None, "10Y": fv("INDIRLTLT01STM")},
             "US": {"1Y": fv("DGS1"), "2Y": fv("DGS2"), "10Y": fv("DGS10")},
             "UK": {"1Y": None, "2Y": None, "10Y": fv("IRLTLT01GBM156N")},
             "Germany": _e, "Japan": _j}

    print("Building chart...")
    ch = build_chart(); print(f"  Chart: {'OK' if ch else 'SKIPPED'}")

    # summary needs (price, d1) tuples
    _eq_t = {t: ((r["price"], r["d1"]) if r else (None, None)) for t, r in eq.items()}
    _fx_t = {t: ((r["price"], r["d1"]) if r else (None, None)) for t, r in fx.items()}
    su = summary(_eq_t, _fx_t, g)
    print("\nSummary:"); [print(f"  * {s}") for s in su]

    secs = []

    # 1. Equities — Current + 1D/1M/3M/6M/1Y/YTD (same as dashboard)
    eq_rows = []
    for region, n, t in EQ:
        r = eq.get(t)
        cur = f"{r['price']:,.2f}" if r else "NA"
        eq_rows.append([region, n, cur] + _cells(r, ("d1", "m1", "m3", "m6", "y1", "ytd")))
    secs.append(("1 . Global equity markets",
                 ["Region", "Index", "Current", "1D", "1M", "3M", "6M", "1Y", "YTD"],
                 eq_rows))

    # 2. Interest rates — country curve, then the policy-rate table
    _ff_now, _ff_chg = policy_changes("FEDFUNDS")
    _rbi_now, _rbi_chg = policy_changes("INTDSRINM193N")

    def _bps(d, l):
        v = d.get(l)
        if v is None:
            return '<span class="muted">NA</span>'
        arrow = "\u25b2" if v >= 0 else "\u25bc"
        col = "var(--neg)" if v >= 0 else "var(--pos)"   # falling rate = green
        return f'<span style="color:{col}">{arrow} {abs(v):.0f} bps</span>'

    _pol_rows = [
        ["RBI Repo Rate", f"{_rbi_now:.2f}%" if _rbi_now is not None else "NA"]
        + [_bps(_rbi_chg, l) for l in ("m1","m3","m6","y1","y5")],
        ["US Fed Funds Rate", f"{_ff_now:.2f}%" if _ff_now is not None else "NA"]
        + [_bps(_ff_chg, l) for l in ("m1","m3","m6","y1","y5")],
    ]
    secs.append(("2 . Interest rates & fixed income",
                 ["Country", "1Y", "2Y", "10Y"],
                 [[k, _r(v, "1Y"), _r(v, "2Y"), _r(v, "10Y")] for k, v in rates.items()]))
    secs.append(("__policy__",
                 ["Central bank", "Policy rate", "1M", "3M", "6M", "1Y", "5Y"],
                 _pol_rows))

    # 3. Currency & crypto — Current + all horizons
    cur_rows = []
    for n, t in FX:
        r = fx.get(t)
        cur = f"{r['price']:.2f}" if r else "NA"
        cur_rows.append([n, cur] + _cells(r, ("d1", "m1", "m3", "m6", "y1", "y5")))
    for n, t in CR:
        r = cry.get(t)
        cur = f"${r['price']:,.0f}" if r else "NA"
        cur_rows.append([n, cur] + _cells(r, ("d1", "m1", "m3", "m6", "y1", "y5")))
    secs.append(("3 . Currency & crypto markets",
                 ["Pair / Asset", "Current", "1D", "1M", "3M", "6M", "1Y", "5Y"],
                 cur_rows))

    # 4. Commodities — Intl + Indian price + all horizons
    _fxr = fx.get("INR=X")
    _fxnow = _fxr["price"] if _fxr else None
    _fxbase = _fxr["base"] if _fxr else {}

    def _inr(usd_now, usd_base, fx_base, factor):
        if usd_base is None or _fxnow is None or fx_base is None:
            return '<span class="muted">NA</span>'
        pct = ((usd_now * _fxnow * factor) / (usd_base * fx_base * factor) - 1) * 100
        return _c(pct)

    cm_rows = []
    for n, t, unit in CM:
        r = cmd.get(t)
        intl = f"${r['price']:,.2f} <span class='muted'>{unit}</span>" if r else "NA"
        if n == "Gold" and g:
            inr_cell = f"Rs {g*10:,.0f} <span class='muted'>/10g</span>"
        elif r and _fxnow:
            factor = 1/31.1035 if "oz" in unit else 1.0
            v = r["price"] * _fxnow * factor
            inr_cell = (f"Rs {v*10:,.0f} <span class='muted'>/10g</span>" if "oz" in unit
                        else f"Rs {v:,.2f}")
        else:
            inr_cell = '<span class="muted">NA</span>'
        chgs = ([_inr(r["price"], r["base"].get(l), _fxbase.get(l),
                      1/31.1035 if "oz" in unit else 1.0)
                 for l in ("d1", "m1", "m6", "y1", "y5")] if r
                else ['<span class="muted">NA</span>'] * 5)
        cm_rows.append([n, intl, inr_cell] + chgs)
    secs.append(("4 . Commodities",
                 ["Commodity", "Intl Price", "Indian Price", "1D", "1M", "6M", "1Y", "5Y"],
                 cm_rows))

    # 5. Volatility — Current + 1D/1M/3M/6M/1Y (same as dashboard)
    vx_rows = []
    for n, t in VX:
        r = vix.get(t)
        cur = f"{r['price']:.2f}" if r else "NA"
        vx_rows.append([n, cur] + _cells(r, ("d1", "m1", "m3", "m6", "y1")))
    secs.append(("5 . Volatility & risk indicators",
                 ["Indicator", "Current", "1D", "1M", "3M", "6M", "1Y"], vx_rows))

    # 6. Macro — Latest + YoY change + period
    mr = []
    for sid, lb, sf, per in [("CPIAUCSL", "US CPI Index", "", "Monthly"),
                             ("UNRATE", "US Unemployment", "%", "Monthly"),
                             ("TRESEGINM052N", "India Forex Reserves", "", "Monthly")]:
        lvl, yoy, dtm = macro_yoy(sid)
        if lvl is None:
            continue
        if sid == "TRESEGINM052N":
            val = f"${lvl/1000:,.2f}B <span class='muted'>({dtm}, excl. gold)</span>"
        else:
            val = f"{lvl:,.2f}{sf}" + (f" <span class='muted'>({dtm})</span>" if dtm else "")
        mr.append([lb, val, _c(yoy) if yoy is not None else '<span class="muted">NA</span>', per])
    # India CPI / WPI / GDP have no free live API — latest published figures
    def _ind(c):
        val = f"{c[0]}% <span class='muted'>({c[1]})</span>"
        try:
            return val, _c(float(c[0]) - float(c[2]))
        except Exception:
            return val, '<span class="muted">NA</span>'
    _v, _ch = _ind(LATEST_INDIA_CPI)
    mr.insert(0, ["India CPI inflation (YoY)", _v, _ch, "Monthly"])
    _v, _ch = _ind(LATEST_INDIA_WPI)
    mr.insert(1, ["India WPI inflation (YoY)", _v, _ch, "Monthly"])
    _v, _ch = _ind(LATEST_INDIA_GDP)
    mr.insert(2, ["India GDP Growth", _v, _ch, "Quarterly / annual"])
    secs.append(("6 . Macro indicators",
                 ["Indicator", "Latest", "Change", "Period"], mr))

    print("\nBuilding PDF (shared builder - identical to dashboard download)...")
    # Build the shared report structure. "__policy__" is folded into the
    # previous section as a second table, exactly like the dashboard renders it.
    report = []
    for t, h, r in secs:
        if t == "__policy__" and report:
            report[-1]["tables"].append({"headers": h, "rows": r})
        else:
            report.append({"title": t, "tables": [{"headers": h, "rows": r}]})
    meta = [now_ist.strftime("%a %d %b %Y  %H:%M IST")]
    pdf = _report_pdf.build_pdf(report, meta, su, chart_png=ch, dashboard_url=DASH)
    print(f"  PDF: {len(pdf):,} bytes")
    with open(f"market-dashboard-{dt.date.today().isoformat()}.pdf", "wb") as f:
        f.write(pdf)
    send_email(pdf, su)
