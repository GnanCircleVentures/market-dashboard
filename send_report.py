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
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image

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
DASH = "https://dashboard-e6gfggmwdroxjgxjde8azc.streamlit.app"
LOGO = os.path.join(os.path.dirname(__file__) or ".", "logo.png")
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
    for _ in range(3):
        try:
            h = yf.Ticker(tk).history(period="5d")
            if h.empty: time.sleep(2); continue
            p = round(float(h["Close"].iloc[-1]), 2)
            pv = float(h["Close"].iloc[-2]) if len(h)>=2 else p
            return p, round((p/pv-1)*100, 2) if pv else 0
        except: time.sleep(2)
    return None, None

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

def build_pdf(secs, summ, chart_buf):
    bio = io.BytesIO()
    hl = os.path.exists(LOGO)
    def wm(canvas,doc):
        if hl:
            try:
                canvas.saveState()
                pw,ph = A4
                from reportlab.lib.utils import ImageReader
                img = ImageReader(LOGO); iw,ih = img.getSize()
                sc = (pw*0.5)/iw; dw,dh = iw*sc,ih*sc
                canvas.setFillAlpha(0.06)
                canvas.drawImage(LOGO,(pw-dw)/2,(ph-dh)/2,dw,dh,preserveAspectRatio=True,mask='auto')
                canvas.restoreState()
            except: pass
    doc = SimpleDocTemplate(bio,pagesize=A4,topMargin=12*mm,bottomMargin=12*mm,leftMargin=10*mm,rightMargin=10*mm)
    ss = getSampleStyleSheet()
    cs = ParagraphStyle("c",fontName="Helvetica",fontSize=6.4,leading=7.4)
    hs = ParagraphStyle("h",fontName="Helvetica-Bold",fontSize=6.4,leading=7.4)
    el = []
    if hl:
        try: el.append(Image(LOGO,width=120,height=26)); el.append(Spacer(1,4))
        except: pass
    stamp = now_ist.strftime("%a %d %b %Y  %H:%M IST")
    el.append(Paragraph("Daily Market Dashboard",ss["Title"]))
    el.append(Paragraph(stamp,ss["Normal"]))
    el.append(Paragraph(f'<a href="{DASH}" color="#1E2761"><u>{DASH}</u></a>',ss["Normal"]))
    el.append(Spacer(1,8))
    if summ:
        el.append(Paragraph("Today's summary",ss["Heading2"]))
        bs = ParagraphStyle("b",fontName="Helvetica",fontSize=8.5,leading=12,leftIndent=8,spaceAfter=2)
        for s in summ: el.append(Paragraph("&bull; "+s,bs))
        el.append(Spacer(1,10))
    for title,headers,rows in secs:
        el.append(Paragraph(title,ss["Heading2"]))
        nc = len(headers)
        data = [[Paragraph(h,hs) for h in headers]]
        for row in rows: data.append([Paragraph(str(c),cs) for c in row])
        fw = doc.width*0.25; rw = (doc.width-fw)/(nc-1) if nc>1 else doc.width
        wds = [fw]+[rw]*(nc-1)
        t = Table(data,colWidths=wds,hAlign="LEFT",repeatRows=1)
        t.setStyle(TableStyle([
            ("TEXTCOLOR",(0,0),(-1,0),colors.black),
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#9db8ff")),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f3f4f6")]),
            ("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#d0d7de")),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3),
            ("TOPPADDING",(0,0),(-1,-1),2),("BOTTOMPADDING",(0,0),(-1,-1),2),
        ]))
        el.append(t); el.append(Spacer(1,6))
        if title.startswith("2") and chart_buf:
            el.append(Image(chart_buf,width=doc.width,height=doc.width*0.42))
            el.append(Spacer(1,6))
    el.append(Spacer(1,8))
    el.append(Paragraph(f'<a href="{DASH}" color="blue"><u>Open live dashboard</u></a>  |  {stamp}',
              ParagraphStyle("ft",fontName="Helvetica",fontSize=7,textColor=colors.grey)))
    doc.build(el,onFirstPage=wm,onLaterPages=wm)
    return bio.getvalue()

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
        if v is None: return ""
        s = f"{'+' if v>=0 else ''}{v:.2f}%"
        return f'<font color="{"#0a8f3c" if v>=0 else "#c0392b"}">{s}</font>'
    def _r(d,k):
        v = d.get(k) if d else None
        return f"{v:.2f}%" if isinstance(v,(int,float)) else "N/A"

    print("Fetching equities...")
    eq = {}
    for _,n,t in EQ:
        eq[t] = yp(t); p,c = eq[t]
        print(f"  {n}: {p:,.2f} ({c:+.2f}%)" if p else f"  {n}: FAILED")
    print("\nFetching FX, commodities, alts, VIX...")
    fx = {t:yp(t) for _,t in FX}
    cmd = {t:yp(t) for _,t,_ in CM}
    cry = {t:yp(t) for _,t in CR}
    vix = {t:yp(t) for _,t in VX}
    g = gold_in()
    print(f"  Gold: Rs {g:,.0f}/g" if g else "  Gold: FAILED")
    print("\nFetching yields...")
    _e = ecb(); _j = jgb()
    rates = {"India":{"1Y":None,"2Y":None,"10Y":fv("INDIRLTLT01STM")},
             "US":{"1Y":fv("DGS1"),"2Y":fv("DGS2"),"10Y":fv("DGS10")},
             "UK":{"1Y":None,"2Y":None,"10Y":fv("IRLTLT01GBM156N")},
             "Germany":_e,"Japan":_j}
    print("Building chart...")
    ch = build_chart(); print(f"  Chart: {'OK' if ch else 'SKIPPED'}")
    su = summary(eq,fx,g)
    print("\nSummary:"); [print(f"  * {s}") for s in su]
    secs = []
    secs.append(("1. Global equity markets",["Region","Index","Price","1D"],
        [[r,n,f"{p:,.2f}" if p else "N/A",_c(c)] for r,n,t in EQ for p,c in [eq.get(t,(None,None))]]))
    secs.append(("2. Interest rates",["Country","1Y","2Y","10Y"],
        [[k,_r(v,"1Y"),_r(v,"2Y"),_r(v,"10Y")] for k,v in rates.items()]))
    _fxrows = [[n,f"{p:.2f}" if p else "N/A",_c(c)] for n,t in FX for p,c in [fx.get(t,(None,None))]]
    _cryrows = [[n,f"${p:,.0f}" if p else "N/A",_c(c)] for n,t in CR for p,c in [cry.get(t,(None,None))]]
    secs.append(("3. Currency & crypto markets",["Pair / Asset","Rate","1D"], _fxrows + _cryrows))
    cr = []
    if g: cr.append(["Gold 24K (India)",f"Rs {g*10:,.0f}/10g",""])
    for n,t,u in CM:
        p,c = cmd.get(t,(None,None)); cr.append([n,f"${p:,.2f} {u}" if p else "N/A",_c(c)])
    secs.append(("4. Commodities",["Commodity","Price","1D"],cr))
    secs.append(("5. Volatility",["Indicator","Level","1D Change"],
        [[n,f"{p:.2f}" if p else "N/A",_c(c)] for n,t in VX for p,c in [vix.get(t,(None,None))]]))
    mr = []
    for sid,lb,sf,per in [("DGS10","US 10Y Yield","%","Daily"),
                           ("CPIAUCSL","US CPI","","Monthly"),
                           ("UNRATE","US Unemployment","%","Monthly"),
                           ("INDIRLTLT01STM","India 10Y","%","Monthly")]:
        v = fv(sid)
        if v: mr.append([lb,f"{v:.2f}{sf}",per])
    secs.append(("6. Macro indicators",["Indicator","Latest","Period"],mr))
    print("\nBuilding PDF...")
    pdf = build_pdf(secs,su,ch); print(f"  PDF: {len(pdf):,} bytes")
    with open(f"market-dashboard-{dt.date.today().isoformat()}.pdf","wb") as f: f.write(pdf)
    send_email(pdf,su)
