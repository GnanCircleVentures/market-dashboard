# Live "Moving" Market Dashboard — Setup Guide

This is an auto-refreshing dashboard. You run it once, leave the browser tab
open, and it keeps updating itself. **Every number on screen is labelled with
its source — nothing is hardcoded or guessed.**

## Where each number comes from

| Data | Source | Type |
|---|---|---|
| US 2Y / 10Y yield, 10Y–2Y spread | **treasury.gov** official daily CSV | 🟢 Primary |
| Fed Funds, US CPI, unemployment | **FRED** (Federal Reserve) | 🟢 Primary |
| Nifty 50, India VIX, Midcap, FII/DII | **NSE India** official API | 🟢 Primary* |
| Bitcoin, Ethereum | **CoinGecko** API | 🟢 Primary |
| Global indices, FX, commodities | **Yahoo Finance** | 🟡 Aggregator |
| RBI repo, bank FD, India G-Sec daily | *no free official API* | ⚪ Gap + link |

\*NSE is the official Indian source, but it's accessed through an unofficial
wrapper that NSE actively rate-limits/firewalls. It usually works from an
**Indian IP** (you're in India, so you're well placed). If it's blocked, the
app shows a clear "unavailable" notice instead of a fake number.

---

## Step 1 — Install Python (one time)
- Windows: https://www.python.org/downloads/ — **tick "Add Python to PATH"**.
- Mac: `python3 --version` (usually pre-installed).

## Step 2 — Install libraries (one time)
Open a terminal in this folder and run:
```
pip install -r requirements.txt
```
(Mac: use `pip3`.) If `nsepython` fails to install, that's fine — the app still
runs; you just lose the live NSE section.

## Step 3 — Run the live dashboard
```
streamlit run app.py
```
(Mac: `python3 -m streamlit run app.py` if `streamlit` isn't found.)

Your browser opens automatically at `http://localhost:8501`. **Leave the tab
open** — it refreshes on the interval you pick in the sidebar (30s–5min). Stop
it anytime with `Ctrl+C` in the terminal.

## Step 4 (optional) — add US macro
Get a free key at https://fredaccount.stlouisfed.org/apikeys, then open `app.py`
and set `FRED_API_KEY = "your_key"`.

---

## "Moving" vs "scheduled" — which do you want?

- **This app (`app.py`)** = a *live* dashboard. It moves on its own while open.
  Best when you're actively watching the market. It does **not** run when the
  tab/terminal is closed.
- **The earlier script (`dashboard.py`)** = a *snapshot* generator. Scheduled
  once a day, it writes a static HTML page and a CSV history even when you're
  not watching. Best for an end-of-day record.

They're complementary. Many people run the live app during market hours and
schedule the snapshot script for an end-of-day archive.

---

## Troubleshooting

- **`streamlit: command not found`** → use `python -m streamlit run app.py`.
- **NSE section says "unavailable"** → NSE rate-limited you. Wait a few minutes,
  refresh, or increase the refresh interval in the sidebar. Don't set a very
  short interval (it gets you blocked faster).
- **Treasury shows nothing on a US holiday/weekend** → the feed only updates on
  US business days; it'll show the last published curve.
- **Yahoo numbers look stale or missing** → Yahoo throttles bursts; the app
  caches for a few minutes to avoid this. `pip install --upgrade yfinance` if it
  breaks broadly.
- **A yield looks 10× off** → tell me; it's a one-line scaling fix. (Treasury's
  own CSV is already in plain percent, so this should be correct.)

Delayed/representative data, for information only — not investment advice.
Always confirm against the official source before acting.
