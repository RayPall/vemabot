# app.py — same scraper, now with progress & status
import os, re, requests, streamlit as st, pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict

# ───────────────────────── Configuration
BASE_URL   = "https://www.vema.cz"
START_PATH = "/cs-cz/svet-vema"
TILE_SEL   = "div.blog__item"
DATE_RE    = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")
CUTOFF     = datetime(2024, 1, 1)
HEADERS    = {"User-Agent": "Mozilla/5.0 VemaScraper/1.1"}
TIMEOUT    = 20

DEFAULT_HOOK = os.getenv("MAKE_WEBHOOK_URL", "")

# ───────────────────────── Scraper helpers
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

    img = ""
    bg  = tile.select_one(".blog__media-inner")
    if bg and bg.has_attr("style"):
        if (m_img := re.search(r"url\(([^)]+)\)", bg["style"])):
            img = BASE_URL + m_img.group(1)

    return {"title": title, "url": url, "image": img, "date": pub.isoformat()}


def scrape_all(status_container, progress_bar) -> List[Dict[str, str]]:
    """Scrape pages, updating status + progress."""
    out, page, total_tiles = [], 1, 0
    while True:
        path = f"{START_PATH}?p={page}" if page > 1 else START_PATH
        status_container.info(f"🔄 Fetching {path} … page {page}")
        soup  = fetch(BASE_URL + path)
        tiles = soup.select(TILE_SEL)

        if not tiles:                       # no more pages
            status_container.warning("⚠️ No tiles found – stopping.")
            break

        total_tiles += len(tiles)
        progress_bar.empty()                # reset bar for new page
        page_bar = st.progress(0, text=f"Parsing {len(tiles)} tiles")

        for idx, t in enumerate(tiles, start=1):
            if (item := parse_tile(t)):
                out.append(item)
            page_bar.progress(idx / len(tiles),
                              text=f"{idx} / {len(tiles)} tiles parsed")

        oldest = min(datetime.fromisoformat(a["date"]) for a in out[-len(tiles):])
        if oldest < CUTOFF:
            status_container.success("✅ Reached cutoff date – done.")
            break
        page += 1

    status_container.success(f"✅ Finished. Parsed {len(out)} articles "
                             f"(≥ {CUTOFF:%d %b %Y}).")
    progress_bar.empty()
    return out

# ───────────────────────── Streamlit UI
st.title("Vema blog scraper → Make webhook")

hook = st.text_input("Make webhook URL", value=DEFAULT_HOOK, type="password")
status = st.empty()          # area for spinner / info / success
progress = st.empty()        # the progress bar placeholder

if st.button("Scrape & show"):
    with st.spinner("Initialising scraper…"):
        articles = scrape_all(status, progress)
    st.dataframe(pd.DataFrame(articles))

if st.button("Send to Make") and hook:
    with st.spinner("Scraping & pushing to Make…"):
        arts = scrape_all(status, progress)
        sent, failed = 0, 0
        for a in arts:
            try:
                requests.post(hook, json=a, timeout=10)
                sent += 1
            except Exception as e:
                failed += 1
                st.error(f"❌ {a['title'][:40]} – {e}")
    st.success(f"✅ Sent {sent} articles  ❌ {failed} failed")

# ───────────────────────── head-less /send endpoint
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
        articles = scrape_all(dummy_status, dummy_prog)
        for a in articles:
            requests.post(hook, json=a, timeout=10)
        return {"sent": len(articles)}

    bootstrap.add_fastapi(api)
