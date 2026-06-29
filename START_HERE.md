# Market Dashboard — Start Here

You have two dashboards in this folder. They share the same data libraries, so
you install once and can run either.

| File | What it is | When to use |
|---|---|---|
| `app.py` | **Live** dashboard. Auto-refreshes, shows up/down arrows, every number labelled with its source. | Watching the market in real time. |
| `dashboard.py` | **Snapshot** generator. Builds a static HTML page + saves a daily CSV history. | A scheduled end-of-day record. |
| `requirements.txt` | The libraries both scripts need. | Install step (below). |
| `README_LIVE.md` | Full detail on the live app + data sources. | Reference. |
| `README.md` | Full detail on the snapshot script + scheduling. | Reference. |

---

## Install (macOS) — do this once

1. Open **Terminal** (`Cmd + Space`, type `Terminal`, Enter).
2. Go into this folder — type `cd ` (with a space) then drag the folder into the
   Terminal window, press Enter. Or: `cd ~/market-dashboard`.
3. Check Python: `python3 --version` (if missing, install from python.org).
4. Install the libraries:
   ```
   pip3 install -r requirements.txt
   ```
   If you get an **"externally-managed-environment"** error, use a virtual
   environment instead:
   ```
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
   (Re-run `source venv/bin/activate` each new Terminal session before running.)
   If `nsepython` fails, ignore it — the live India/NSE section just won't load;
   everything else still works.

---

## Run

**Live dashboard:**
```
python3 -m streamlit run app.py
```
Browser opens at `localhost:8501`. Leave the tab open; it refreshes itself.
Stop with `Ctrl + C` in Terminal.

**Snapshot (static page + CSV history):**
```
python3 dashboard.py
```
Then open the `output/dashboard.html` file it creates.

---

## Where the numbers come from (no hardcoded values)

- US 2Y/10Y yields, 10Y–2Y spread → **treasury.gov** official daily feed.
- US macro (Fed Funds, CPI, unemployment) → **FRED** (add a free key in the file).
- Nifty 50, India VIX, FII/DII → **NSE India** official API (works best from an
  Indian IP; shows "unavailable" rather than a fake number if blocked).
- Bitcoin/Ethereum → **CoinGecko**.
- Global indices, FX, commodities → **Yahoo Finance** (aggregator, clearly
  labelled as such in the app).
- RBI repo rate, bank FD rates, daily India G-Sec → no free official API, shown
  as a labelled gap with a link to the official site.

Optional: add a free FRED key (https://fredaccount.stlouisfed.org/apikeys) inside
`app.py` and `dashboard.py` to turn on US macro.

Data is delayed/representative and for information only — not investment advice.
Always confirm against the official source before acting.
