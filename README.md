# Daily Market Dashboard — Setup Guide

A one-page market dashboard that refreshes automatically every day. It pulls
live (delayed) data from Yahoo Finance for free — no account, no API key — and
generates an HTML page you open in your browser.

---

## What updates automatically vs. by hand

| Automatic (Yahoo Finance, free) | You edit by hand (in `dashboard.py`) |
|---|---|
| 10 equity indices (Nifty, Sensex, S&P, etc.) | RBI / Fed / ECB / BoE policy rates |
| US 10Y yield, CBOE VIX, India VIX | Bank FD rates, MCLR / loan benchmarks |
| All FX pairs, commodities, gold in ₹ | India G-Sec yields (no free daily API) |
| Bitcoin, Ethereum | India CPI / WPI / GDP, forex reserves |

The hand-edited items change only every few weeks. Open `dashboard.py`, find the
**CONFIG** block near the top, type the current values, and update the
`MANUAL_LAST_UPDATED` date.

---

## Step 1 — Install Python (one time)

- **Windows:** download from https://www.python.org/downloads/ and during install
  **tick "Add Python to PATH"**.
- **Mac:** Python 3 is usually pre-installed. Check with `python3 --version`.
  If missing, install from python.org or run `brew install python`.

## Step 2 — Install the libraries (one time)

Open a terminal **in this folder**:
- Windows: open the folder, type `cmd` in the address bar, press Enter.
- Mac: right-click the folder → "New Terminal at Folder".

Then run:
```
pip install -r requirements.txt
```
(On Mac, use `pip3` if `pip` isn't found.)

## Step 3 — Run it

```
python dashboard.py
```
(Mac: `python3 dashboard.py`.) It takes ~30–60 seconds. When done, open
`output/dashboard.html` in any browser. A dated CSV snapshot is also saved in
`output/history/` so you slowly build your own price history.

---

## Step 4 — Make it run automatically every day

### Windows (Task Scheduler)
1. Press Start, type **Task Scheduler**, open it.
2. **Create Basic Task** → name it "Market Dashboard" → **Daily** → pick a time
   (e.g. 7:00 PM, after Indian market close).
3. Action: **Start a program**.
   - Program/script: `python`
   - Add arguments: `dashboard.py`
   - Start in: paste the full path to this folder
     (e.g. `C:\Users\You\market-dashboard`).
4. Finish. To auto-open the page too, you can instead point it at a small `.bat`
   file containing:
   ```
   cd /d C:\Users\You\market-dashboard
   python dashboard.py
   start output\dashboard.html
   ```

### Mac (cron)
1. Terminal: `crontab -e`
2. Add this line (runs daily at 7 PM — adjust the path):
   ```
   0 19 * * * cd /Users/you/market-dashboard && /usr/bin/python3 dashboard.py
   ```
3. Save and exit. Find your exact Python path with `which python3`.

> The laptop must be **on and awake** at the scheduled time, or the task runs at
> the next wake. For always-on updates you'd need a small cloud server, but for a
> personal dashboard, scheduling on your laptop is plenty.

---

## Optional — add US macro (CPI, unemployment)

1. Get a free key (1 minute): https://fredaccount.stlouisfed.org/apikeys
2. Open `dashboard.py`, set `FRED_API_KEY = "your_key_here"`.

---

## Customizing

- **Add/remove a ticker:** edit the lists in section 2 of `dashboard.py`. Find
  Yahoo symbols by searching the instrument on finance.yahoo.com — the symbol is
  in the page title (e.g. Reliance = `RELIANCE.NS`).
- **Change alert levels:** edit the `THRESHOLDS` dict.
- **Add today's events:** type them into `KEY_EVENTS_TODAY`.

---

## Troubleshooting

- **"Missing library"** → you skipped Step 2; run the `pip install` command.
- **Lots of `—` or `! ticker` messages** → Yahoo occasionally rate-limits or
  changes its format. Wait a few minutes and re-run, or upgrade the library:
  `pip install --upgrade yfinance`. Individual failures never crash the run;
  the rest of the dashboard still builds.
- **A yield or VIX number looks 10x off** → Yahoo sometimes changes how it quotes
  yield indices. Sanity-check `^TNX` against a news source once and tell me if
  it's off; the fix is a one-line scaling change.
- **`python` not recognized (Windows)** → you missed "Add to PATH"; reinstall
  Python and tick that box, or use the full path to python.exe.

Data is delayed and for information only — not investment advice.
