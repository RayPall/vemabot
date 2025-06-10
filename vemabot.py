# app.py  –  Vema blog scraper with correct ?News_page=… pagination
import os, re, requests, streamlit as st, pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from typing import Dict, List

# ───────────────────────── Configuration
BASE_URL   = "https://www.vema.cz"
START_PATH = "/cs-cz/svet-vema"            # first page (no query string)
NEXT_FMT   = "/cs-cz/svet-vema?News_page={}"   # page ≥ 2
TILE_SEL   = "div.blog__item"
DATE_RE    = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")
CUTOFF     = datetime(2024, 1, 1)
HEADERS    = {"User-Agent": "Mozilla/5.0 VemaScraper/1.2"}
TIMEOUT    = 20

DEFAULT_HOOK = os.getenv("MAKE_WEBHOOK_URL", "")

# ───────────────────────── Helpers
def fetch(url: str) -> BeautifulSoup:
    html = requests.get(url, headers=HEADERS, timeout=TIMEOUT).text
    return BeautifulSoup(html, "html.parser")


def parse_tile(tile) -> Dict[str, str] | None:
    link = tile.select_one(".blog__content h3 a")
    if not link or not link.get("href"):
        return None
    url   = BASE_URL + link["href"]
    title = link.get_text(strip=True)

    li_date = tile.select_one(".blog__footer .blog__info ul li:nth-of-type(2)")
    if not li_date:
        return None
    m = DATE_RE.search(li_date.text.strip())
    if not m:
        return None
    day, month, year = map(int, m.groups())
    pub = datetime(year, month, day)
    if pub < CUTOFF:
        return None

    # optional thumbnail
    bg  = tile.select_one(".blog__media-inner")
    img = ""
    if bg and bg.has_attr("style"):
        if (m_img := re.search(r"url\(([^)]+)\)", bg["style"])):
            img = BASE_URL + m_img.group(1)

    return {"title": title, "url": url, "image": img, "date": pub.isoformat()}


def scrape_page(path: str) -> List[Dict[str, str]]:
    soup = fetch(BASE_URL + path)
    return [item for t in soup.select(TILE_SEL) if (item := parse_tile(t))]

# ─── scrape_all with progress / status ────────────────────────────────────
def scrape_all(status, page_prog):
    results, page_num = [], 1
    while True:
        path = START_PATH if page_num == 1 else NEXT_FMT.format(page_num)
        status.info(f"🔄 Fetching {path}")
        tiles = scrape_page(path)
        if not tiles:
            status.warning("⚠️ No tiles on this page – stopping.")
            break

        page_bar = page_prog.progress(0, text=f"Parsing {len(tiles)} tiles")
        for i, t in enumerate(tiles, 1):
            results.append(t)
            page_bar.progress(i / len(tiles),
                              text=f"{i}/{len(tiles)} tiles parsed")

        if min(datetime.fromisoformat(a["date"]) for a in tiles) < CUTOFF:
            status.success("✅ Reached cutoff date – finished.")
            break

        page_num += 1
        if page_num > 50:                  # safety guard
            status.error("🚨 Too many pages, aborting at 50.")
            break
    page_prog.empty()
    return results

# ───────────────────────── Streamlit UI
st.title("Vema blog scraper → Make webhook")

hook = st.text_input("Make webhook URL", value=DEFAULT_HOOK, type="password")
status_box  = st.empty()
progress_box = st.empty()

if st.button("Scrape & show"):
    with st.spinner("Scraping…"):
        articles = scrape_all(status_box, progress_box)
    st.success(f"Found {len(articles)} articles ≥ {CUTOFF:%d %b %Y}")
    st.dataframe(pd.DataFrame(articles))

if st.button("Send to Make") and hook:
    with st.spinner("Scraping & sending…"):
        arts = scrape_all(status_box, progress_box)
        sent, failed = 0, 0
        for art in arts:
            try:
                requests.post(hook, json=art, timeout=10)
                sent += 1
            except Exception as e:
                failed += 1
                st.error(f"❌ {art['title'][:40]} – {e}")
    st.success(f"✅ Sent {sent}  ❌ {failed} failed")

# ───────────────────────── head-less /send route
if st.secrets.get("viewer_api"):
    import streamlit.web.bootstrap as bootstrap
    from fastapi import FastAPI
    api = FastAPI()

    @api.get("/send")
    def send_now():
        if not hook:
            return {"error": "no webhook configured"}
        dummy_status = st.empty()
        dummy_prog   = st.empty()
        arts = scrape_all(dummy_status, dummy_prog)
        for art in arts:
            requests.post(hook, json=art, timeout=10)
        return {"sent": len(arts)}

    bootstrap.add_fastapi(api)
