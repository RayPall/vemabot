# app.py  ·  Vema “Svět Vema” scraper → Make webhook  (batch POST version)
import os, re, requests, streamlit as st, pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict

# ───────────────────────────── CONFIG ─────────────────────────────────────
BASE_URL   = "https://www.vema.cz"
START_PATH = "/cs-cz/svet-vema"            # landing page
TILE_SEL   = "div.blog__item"              # every article tile
DATE_RE    = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")
CUTOFF     = datetime(2024, 1, 1)          # ignore older than this
HEADERS    = {"User-Agent": "Mozilla/5.0 VemaScraper/2.0"}
TIMEOUT    = 20                            # seconds

DEFAULT_HOOK = os.getenv("MAKE_WEBHOOK_URL", "")  # set in Streamlit secrets

# ───────────────────────────── SCRAPER ────────────────────────────────────
def fetch(url: str) -> BeautifulSoup:
    html = requests.get(url, timeout=TIMEOUT, headers=HEADERS).text
    return BeautifulSoup(html, "html.parser")


def parse_tile(tile) -> Dict[str, str] | None:
    """Return dict(title,url,image,date) or None if date < CUTOFF."""
    link = tile.select_one(".blog__content h3 a")
    if not link or not link.get("href"):
        return None
    url   = BASE_URL + link["href"]
    title = link.get_text(strip=True)

    # second <li> holds raw date "17. 4. 2025"
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

    img_url = ""
    bg = tile.select_one(".blog__media-inner")
    if bg and bg.has_attr("style"):
        if (m_img := re.search(r"url\(([^)]+)\)", bg["style"])):
            img_url = BASE_URL + m_img.group(1)

    return {
        "title": title,
        "url": url,
        "image": img_url,
        "date": pub.isoformat()
    }


def scrape_page(page_num: int) -> List[Dict[str, str]]:
    path = START_PATH if page_num == 1 else f"{START_PATH}?News_page={page_num}"
    soup = fetch(BASE_URL + path)
    return [art for t in soup.select(TILE_SEL) if (art := parse_tile(t))]


def scrape_all(status, page_bar) -> List[Dict[str, str]]:
    """Scrape paginated list until oldest article < CUTOFF."""
    page, out = 1, []
    while True:
        status.info(f"🔄 Fetching page {page} …")
        tiles = scrape_page(page)
        if not tiles:
            status.warning("⚠️ No tiles found – stopping.")
            break

        page_bar.empty()
        bar = st.progress(0, text=f"Parsing {len(tiles)} tiles on page {page}")

        for idx, art in enumerate(tiles, 1):
            out.append(art)
            bar.progress(idx / len(tiles),
                         text=f"{idx}/{len(tiles)} parsed (page {page})")

        oldest = min(datetime.fromisoformat(a["date"]) for a in tiles)
        if oldest < CUTOFF:
            status.success("✅ Reached cutoff date – done.")
            break
        page += 1
    page_bar.empty()
    status.success(f"✅ Scraped {len(out)} articles ≥ {CUTOFF:%d %b %Y}")
    return out

# ─────────────────────────── STREAMLIT UI ─────────────────────────────────
st.title("Vema blog scraper → Make webhook (batch)")

hook = st.text_input("Make webhook URL", value=DEFAULT_HOOK, type="password")
status_area  = st.empty()
progress_area = st.empty()

if st.button("Scrape & show"):
    with st.spinner("Scraping…"):
        articles = scrape_all(status_area, progress_area)
    st.dataframe(pd.DataFrame(articles))

if st.button("Send to Make") and hook:
    with st.spinner("Scraping & sending…"):
        arts = scrape_all(status_area, progress_area)
    try:
        resp = requests.post(hook, json={"articles": arts}, timeout=15)
        resp.raise_for_status()
        st.success(f"✅ Sent {len(arts)} articles to Make (status {resp.status_code})")
    except Exception as e:
        st.error(f"❌ Make webhook error: {e}")

# ─────────────────────────── HEAD-LESS /send ─────────────────────────────
if st.secrets.get("viewer_api"):           # Streamlit Cloud indicator
    import streamlit.web.bootstrap as bootstrap
    from fastapi import FastAPI

    api = FastAPI()

    @api.get("/se
