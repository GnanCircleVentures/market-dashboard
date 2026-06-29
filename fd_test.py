#!/usr/bin/env python3
"""
FD-RATE SCRAPE DIAGNOSTIC  (run once, paste me the output)
----------------------------------------------------------
This does NOT touch your dashboard. It just visits each bank's FD page
and reports what it can actually see, so we know which banks can be
scraped with a simple fetch and which need a full browser.

Run it in Terminal from your dashboard folder:
    python3 fd_test.py
Then copy ALL the output and paste it back to me.
"""

import re
import requests

# Official FD-rate pages (best-known current URLs)
BANKS = {
    "SBI":   "https://sbi.bank.in/web/interest-rates/interest-rates/deposit-rates",
    "HDFC":  "https://www.hdfc.bank.in/fixed-deposit/fd-interest-rate",
    "ICICI": "https://www.icici.bank.in/personal-banking/deposits/fixed-deposit/fd-interest-rates",
    "Axis":  "https://www.axisbank.com/retail/deposits/fixed-deposit/fd-interest-rate",
    "Kotak": "https://www.kotak.com/en/personal-banking/deposits/fixed-deposit/fixed-deposit-interest-rate.html",
}

# Pretend to be a normal browser, or many sites block us outright.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}

# Rate-like tokens: 6.60%, 7.10 %, etc.
RATE_RE = re.compile(r"\b([2-9]\.\d{1,2})\s*%")
# Visible text (very rough: strip tags/scripts)
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<script.*?</script>", re.S | re.I)


def visible_text(html: str) -> str:
    no_script = SCRIPT_RE.sub(" ", html)
    return TAG_RE.sub(" ", no_script)


def verdict(html: str) -> str:
    """Rough call on whether the numbers are in the raw HTML or loaded by JS."""
    txt = visible_text(html)
    rates = RATE_RE.findall(txt)
    has_tenor = bool(re.search(r"\b(1 year|365 days|12 months|tenure|tenor)\b",
                               txt, re.I))
    n_scripts = len(re.findall(r"<script", html, re.I))
    if len(rates) >= 5 and has_tenor:
        return f"LIKELY SCRAPEABLE - found {len(rates)} rate-like numbers in raw HTML"
    if len(rates) >= 1:
        return f"MAYBE - only {len(rates)} rate-like numbers found (might be partial)"
    if n_scripts > 20:
        return "PROBABLY JS-RENDERED - no rates in raw HTML, heavy script use (needs a browser)"
    return "NO RATES FOUND in raw HTML"


def sample_rates(html: str, k: int = 8):
    txt = visible_text(html)
    seen, out = set(), []
    for m in RATE_RE.finditer(txt):
        val = m.group(1)
        if val in seen:
            continue
        seen.add(val)
        start = max(0, m.start() - 35)
        ctx = re.sub(r"\s+", " ", txt[start:m.end() + 3]).strip()
        out.append(ctx)
        if len(out) >= k:
            break
    return out


print("=" * 70)
print("FD-RATE SCRAPE DIAGNOSTIC")
print("=" * 70)

for bank, url in BANKS.items():
    print(f"\n----- {bank} -----")
    print(f"URL: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        html = r.text
        print(f"HTTP status : {r.status_code}")
        print(f"Page size   : {len(html):,} bytes")
        print(f"Verdict     : {verdict(html)}")
        samples = sample_rates(html)
        if samples:
            print("Sample matches in raw HTML:")
            for s in samples:
                print(f"   ... {s}")
        else:
            print("No rate-like numbers in raw HTML.")
    except requests.exceptions.RequestException as e:
        print(f"FETCH FAILED: {type(e).__name__}: {e}")

print("\n" + "=" * 70)
print("Done. Copy everything above and paste it back to me.")
print("=" * 70)
