#!/usr/bin/env python3
"""
FD MULTI-TENOR SCRAPE DIAGNOSTIC  (run once, paste me ALL the output)
=====================================================================
Goal: find out, for each institution, whether we can read its FD rates by
tenor (1M / 3M / 6M / 1Y / 3Y) from YOUR machine -- and from which source
(the bank's own page, or an aggregator like PolicyBazaar / StableMoney).

This does NOT touch your dashboard. It just visits pages and reports what it
can see, so I can then wire only the sources that actually work.

It tries a plain fetch first; if that finds little and Playwright is installed,
it retries the page in a real headless browser.

SETUP (only if it says Playwright is missing):
    pip3 install playwright            (add --break-system-packages if needed)
    python3 -m playwright install chromium

RUN:
    python3 fd_tenor_test.py
Then copy EVERYTHING it prints and paste it back to me.
"""

import re
import sys

import requests

try:
    from playwright.sync_api import sync_playwright
    HAS_PW = True
except Exception:
    HAS_PW = False

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

# Each institution: (name, [candidate URLs in priority order]).
# First URL is the official page; the second is an aggregator fallback.
INSTITUTIONS = [
    ("SBI", [
        "https://sbi.bank.in/web/interest-rates/deposit-rates/retail-domestic-term-deposits",
        "https://www.policybazaar.com/fd-interest-rates/sbi-fd-interest-rates/"]),
    ("HDFC Bank", [
        "https://www.hdfc.bank.in/fixed-deposit/fd-interest-rate",
        "https://www.policybazaar.com/fd-interest-rates/hdfc-bank-fd-interest-rates/"]),
    ("ICICI Bank", [
        "https://www.icici.bank.in/personal-banking/deposits/fixed-deposit/fd-interest-rates",
        "https://www.policybazaar.com/fd-interest-rates/icici-bank-fd-interest-rates/"]),
    ("Axis Bank", [
        "https://www.axisbank.com/fixed-deposit-interest-rate",
        "https://www.policybazaar.com/fd-interest-rates/axis-bank-fd-interest-rates/"]),
    ("Kotak", [
        "https://www.kotak.com/en/personal-banking/deposits/fixed-deposit/fixed-deposit-interest-rate.html",
        "https://www.policybazaar.com/fd-interest-rates/kotak-mahindra-bank-fd-interest-rates/"]),
    ("AU SFB", [
        "https://www.au.bank.in/interest-rates/fixed-deposit-interest-rates",
        "https://www.policybazaar.com/fd-interest-rates/au-small-finance-bank-fd-rates/"]),
    ("Ujjivan SFB", [
        "https://www.ujjivansfb.in/fixed-deposit-interest-rates",
        "https://www.policybazaar.com/fd-interest-rates/ujjivan-small-finance-bank-fd-rates/"]),
    ("Utkarsh SFB", [
        "https://www.utkarsh.bank/fixed-deposit",
        "https://www.policybazaar.com/fd-interest-rates/utkarsh-small-finance-bank-fd-rates/"]),
    ("Unity SFB", [
        "https://theunitybank.com/fixed-deposit",
        "https://www.policybazaar.com/fd-interest-rates/unity-small-finance-bank-fd-rates/"]),
    ("Bajaj Finance", [
        "https://www.bajajfinserv.in/fixed-deposit",
        "https://www.policybazaar.com/fd-interest-rates/bajaj-finance-fd-interest-rates/"]),
    ("Shriram Finance", [
        "https://www.shriramfinance.in/fixed-deposit",
        "https://www.policybazaar.com/fd-interest-rates/shriram-finance-fd-interest-rates/"]),
    ("Suryoday SFB", [
        "https://www.suryodaybank.com/fixed-deposit",
        "https://www.policybazaar.com/fd-interest-rates/suryoday-small-finance-bank-fd-rates/"]),
]

# tenor + rate pairs, e.g. "1 year ... 7.10%", "180 days ... 6.50 %"
TENOR_RE = re.compile(
    r"(\d{1,4})\s*(day|days|month|months|year|years|yr|yrs|y|m|d)\b[^%]{0,40}?"
    r"([2-9]\.\d{1,2})\s*%", re.I)
UNIT_DAYS = {"day": 1, "days": 1, "d": 1, "month": 30, "months": 30, "m": 30,
             "year": 365, "years": 365, "yr": 365, "yrs": 365, "y": 365}
RATE_RE = re.compile(r"\b([2-9]\.\d{1,2})\s*%")
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<script.*?</script>", re.S | re.I)

# tenors we ultimately want, in days
TARGETS = {"1M": 30, "3M": 91, "6M": 182, "1Y": 365, "3Y": 1095}


def visible_text_from_html(html):
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", SCRIPT_RE.sub(" ", html)))


def analyse(text):
    """Return (rate_count, {target: (days, rate)} nearest match per target)."""
    pairs = []
    for m in TENOR_RE.finditer(text):
        n, unit, rate = int(m.group(1)), m.group(2).lower(), float(m.group(3))
        days = n * UNIT_DAYS.get(unit, 0)
        if 2.0 <= rate <= 10.0 and 7 <= days <= 4000:
            pairs.append((days, rate))
    picks = {}
    for label, want in TARGETS.items():
        near = sorted(pairs, key=lambda p: abs(p[0] - want))
        picks[label] = near[0] if near and abs(near[0][0] - want) <= want * 0.5 else None
    return len(RATE_RE.findall(text)), picks


def fetch_simple(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    return r.status_code, r.text


def fetch_browser(url):
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=UA)
        pg.goto(url, timeout=45000, wait_until="domcontentloaded")
        pg.wait_for_timeout(6000)
        txt = pg.inner_text("body")
        b.close()
    return txt


def report_picks(picks):
    out = []
    for label in ("1M", "3M", "6M", "1Y", "3Y"):
        p = picks.get(label)
        out.append(f"{label}={p[1]:.2f}%@{p[0]}d" if p else f"{label}=?")
    return "  ".join(out)


print("=" * 74)
print("FD MULTI-TENOR SCRAPE DIAGNOSTIC")
print("Playwright (headless browser):", "available" if HAS_PW else "NOT installed")
print("=" * 74)

results = {}


for name, urls in INSTITUTIONS:
    print(f"\n##### {name} #####")
    done = False
    for url in urls:
        print(f"  URL: {url}")
        # 1) plain fetch
        try:
            status, html = fetch_simple(url)
            txt = visible_text_from_html(html)
            n, picks = analyse(txt)
            hits = sum(1 for v in picks.values() if v)
            print(f"    fetch: HTTP {status}, {len(html):,} bytes, "
                  f"{n} rate-like numbers, {hits}/5 tenors")
            if hits >= 3:
                print(f"    -> FETCH OK: {report_picks(picks)}")
                results[name] = {
        "1M": picks.get("1M")[0] if picks.get("1M") else "",
        "3M": picks.get("3M")[0] if picks.get("3M") else "",
        "6M": picks.get("6M")[0] if picks.get("6M") else "",
        "1Y": picks.get("1Y")[0] if picks.get("1Y") else "",
        "3Y": picks.get("3Y")[0] if picks.get("3Y") else ""
    }
                done = True
                break
        except Exception as e:
            print(f"    fetch FAILED: {type(e).__name__}: {e}")
        # 2) headless browser (if available)
        if HAS_PW:
            try:
                txt = fetch_browser(url)
                txt = re.sub(r"\s+", " ", txt)
                n, picks = analyse(txt)
                hits = sum(1 for v in picks.values() if v)
                print(f"    browser: {len(txt):,} chars, {n} rate-like numbers, "
                      f"{hits}/5 tenors")
                if hits >= 3:
                    print(f"    -> BROWSER OK: {report_picks(picks)}")
                    done = True
                    break
                elif hits >= 1:
                    print(f"    -> PARTIAL: {report_picks(picks)}")
            except Exception as e:
                print(f"    browser FAILED: {type(e).__name__}: {e}")
    if not done:
        print("    -> no clean tenor table from these URLs "
              "(needs a better URL, a click/scroll, or it's blocked)")

print("\n" + "=" * 74)
print("Done. Copy EVERYTHING above and paste it back to me.")
print("Tell me which institutions show OK / PARTIAL, and I'll wire those in.")
import json
with open("fd_results.json", "w") as f:
    json.dump(results, f, indent=2)

print("Saved FD results to fd_results.json")
print("=" * 74)
print("FD MULTI-TENOR SCRAPE DIAGNOSTIC")
print("Playwright (headless browser):", 
print("=" * 74)
results = {}


