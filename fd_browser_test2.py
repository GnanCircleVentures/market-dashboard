#!/usr/bin/env python3
"""
DIAGNOSTIC v2 — can the headless browser read (a) RBI lending rates and
(b) India/Germany/UK short-tenor yields?  Does NOT touch your dashboard.

You already have Playwright installed, so just run:
    python3 fd_browser_test2.py
and paste ALL the output back to me.
"""

import re
import sys

try:
    from playwright.sync_api import sync_playwright
except Exception:
    print("Playwright missing. Run: pip3 install playwright ; "
          "python3 -m playwright install chromium")
    sys.exit(1)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# (a) RBI: the press-release LISTING page; we find the latest lending-rate item.
RBI_SEARCH = ("https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx")
RBI_LIST = ("https://www.rbi.org.in/Scripts/NewLinkDisplay.aspx")  # press releases list

# (b) Yield pages to probe (bot-protection likely):
YIELD_PAGES = {
    "India 1Y":   "https://www.investing.com/rates-bonds/india-1-year-bond-yield",
    "India 2Y":   "https://www.investing.com/rates-bonds/india-2-year-bond-yield",
    "Germany 2Y": "https://www.investing.com/rates-bonds/germany-2-year-bond-yield",
    "UK 2Y":      "https://www.investing.com/rates-bonds/uk-2-year-bond-yield",
}

WALR_RE = re.compile(r"WALR[^.]{0,120}?fresh[^%]{0,60}?(\d\.\d{1,2})\s*per\s*cent", re.I)
MCLR_RE = re.compile(r"median[^%]{0,80}?MCLR[^%]{0,80}?(\d\.\d{1,2})\s*per\s*cent", re.I)
YIELD_RE = re.compile(r"\b([2-9]\.\d{1,3})\b")

print("=" * 70)
print("DIAGNOSTIC v2")
print("=" * 70)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)

    # ---- (a) RBI ----
    print("\n##### RBI lending/deposit press release #####")
    try:
        pg = b.new_page(user_agent=UA)
        # Google the latest release to get a fresh prid, then open it.
        pg.goto("https://www.google.com/search?q=RBI+data+on+lending+and+deposit+rates+press+release",
                timeout=45000, wait_until="domcontentloaded")
        pg.wait_for_timeout(3000)
        html = pg.content()
        m = re.search(r"BS_PressReleaseDisplay\.aspx\?prid=(\d+)", html)
        if m:
            url = f"https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid={m.group(1)}"
            print("Found release URL:", url)
            pg.goto(url, timeout=45000, wait_until="domcontentloaded")
            pg.wait_for_timeout(3000)
            txt = re.sub(r"\s+", " ", pg.inner_text("body"))
            wal = WALR_RE.search(txt); mcl = MCLR_RE.search(txt)
            print("WALR fresh found:", wal.group(1)+"%" if wal else "NO")
            print("median MCLR found:", mcl.group(1)+"%" if mcl else "NO")
            print("Sample around 'MCLR':",
                  (txt[txt.lower().find("mclr")-40:txt.lower().find("mclr")+60]
                   if "mclr" in txt.lower() else "n/a"))
        else:
            print("Could not find a release link from search.")
        pg.close()
    except Exception as e:
        print("RBI FAILED:", type(e).__name__, e)

    # ---- (b) Yields ----
    for name, url in YIELD_PAGES.items():
        print(f"\n##### {name} #####")
        print("URL:", url)
        try:
            pg = b.new_page(user_agent=UA)
            pg.goto(url, timeout=45000, wait_until="domcontentloaded")
            pg.wait_for_timeout(5000)
            txt = pg.inner_text("body")
            blocked = any(w in txt.lower() for w in
                          ["are you a robot", "verify you are human",
                           "access denied", "cloudflare", "captcha"])
            print("Looks blocked:", blocked, "| text length:", len(txt))
            nums = YIELD_RE.findall(re.sub(r"\s+", " ", txt))[:10]
            print("First numeric-looking values:", nums)
            pg.close()
        except Exception as e:
            print("FAILED:", type(e).__name__, e)

    b.close()

print("\n" + "=" * 70)
print("Done. Copy everything above and paste it back to me.")
print("=" * 70)
