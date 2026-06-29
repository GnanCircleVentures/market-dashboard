#!/usr/bin/env python3
"""
HEADLESS-BROWSER FD DIAGNOSTIC  (run once, paste me the output)
---------------------------------------------------------------
This opens each JS-rendered bank page in a REAL Chrome engine, waits for the
rate table to load, then reports the 1-year-ish rates it can see. It does NOT
touch your dashboard.

ONE-TIME SETUP (run these two lines first, in Terminal):
    pip3 install playwright          (add --break-system-packages if it errors)
    python3 -m playwright install chromium

THEN run:
    python3 fd_browser_test.py
and paste ALL the output back to me.
"""

import re
import sys

try:
    from playwright.sync_api import sync_playwright
except Exception:
    print("Playwright is not installed yet. Run these two lines first:\n"
          "    pip3 install playwright\n"
          "    python3 -m playwright install chromium")
    sys.exit(1)

BANKS = {
    "SBI":   "https://sbi.bank.in/web/interest-rates/deposit-rates/retail-domestic-term-deposits",
    "ICICI": "https://www.icici.bank.in/personal-banking/deposits/fixed-deposit/fd-interest-rates",
    "Kotak": "https://www.kotak.com/en/personal-banking/deposits/fixed-deposit/fixed-deposit-interest-rate.html",
}

RATE_RE = re.compile(r"\b([2-9]\.\d{1,2})\s*%")
# tenor + rate pairs (same logic the dashboard will use)
TENOR_RE = re.compile(
    r"(\d{1,4})\s*(day|days|month|months|year|years|yr|yrs)\b[^%]{0,45}?"
    r"([3-9]\.\d{1,2})\s*%", re.I)
UNIT_DAYS = {"day": 1, "days": 1, "month": 30, "months": 30,
             "year": 365, "years": 365, "yr": 365, "yrs": 365}


def analyse(text):
    cands = []
    for m in TENOR_RE.finditer(text):
        n, unit, rate = int(m.group(1)), m.group(2).lower(), float(m.group(3))
        days = n * UNIT_DAYS[unit]
        if 2.0 <= rate <= 9.5 and 7 <= days <= 3700:
            cands.append((days, rate))
    near_1y = sorted(set(cands), key=lambda c: (abs(c[0] - 365), c[0]))[:8]
    return len(RATE_RE.findall(text)), near_1y


print("=" * 70)
print("HEADLESS-BROWSER FD DIAGNOSTIC")
print("=" * 70)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for bank, url in BANKS.items():
        print(f"\n----- {bank} -----")
        print(f"URL: {url}")
        try:
            page = browser.new_page(
                user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0 Safari/537.36"))
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(6000)          # let the rate JS finish
            body = page.inner_text("body")
            page.close()
            total, near = analyse(re.sub(r"\s+", " ", body))
            print(f"Visible text length : {len(body):,} chars")
            print(f"Rate-like numbers   : {total}")
            if near:
                print("Tenor/rate pairs nearest 1 year:")
                for d, rt in near:
                    print(f"   {rt:.2f}%  @ ~{d}d")
            else:
                print("No tenor/rate pairs found (page may need a click/scroll).")
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")
    browser.close()

print("\n" + "=" * 70)
print("Done. Copy everything above and paste it back to me.")
print("=" * 70)
