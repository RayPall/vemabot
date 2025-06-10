# app.py  –  Vema Blog scraper with progress + correct ?News_page pagination
import os, re, requests, streamlit as st, pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict

# ───────────────────────── Configuration
BASE_URL   = "https://www.vema.cz"
START_PATH = "/cs-cz/svet-vema"               # landing page
TILE_SEL   = "div.blog__item"                 # each article tile
DATE_RE    = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")
CUTOFF     = datetime(2024, 1, 1)             # ignore older articles
HEADERS    = {"User-Agent": "Mozilla/5.0 VemaScraper/1.1"}
TIMEOUT    = 20

DEFAULT_HOOK = os.getenv("MAKE_WEBHOOK_URL", "")  # set in Streamlit secrets

# ───────────────────────── Scraper helpers
def fetch(url: str) -> BeautifulSoup:
    html = requests.get(url, headers=HEADERS, timeout=TIMEOUT).text
    return BeautifulSoup(html, "html.parser")


def parse_tile(tile) -> Dict[str, str] | None:
    # link is inside h3 > a
    link = tile.select_one(".blog__content h3 a")
    if not link or not link.get("href"):
        return None
    url   = BASE_URL + link["href"]
    title = link.get_text(strip=True)

    # date is 2nd <li> in footer
    li_date = tile.select_one(".blog__footer .blog__info ul li:nth-of-type(2)")
    if not li_date:
        return None
    m = DATE_RE.search(li_date.get_text(strip=True))
    if not m:
        return None
    day, month, year = map(int, m.groups())
    pub = datetime(year, month, day)
    if pub < CUTOFF:
        return None

    # optional background image
    img = ""
    bg  = tile.select_one(".blog__media-inner")
    if bg and bg.has_attr("style"):
        m_img = re.search(r"url\(([^)]+)\)", bg["style"])
        if m_img:
            img = BASE_URL + m_img.group(1)

    return {"title": title, "url": url, "image": img, "date": pub.isoformat()}


def scrape_page(path: str) -> List[Dict[str, str]]:
    soup = fetch(BASE_URL + path)
    return [item for t in soup.select(TILE_SEL) if (item := parse_tile(t))]


def scrape_all(status, main_prog) -> List[Dict[str, str]]:
    """Scrape all paginated pages, updating Streamlit status + progress."""
    results, page = [], 1
    while True:
        path   = START_PATH if page == 1 else f"{START_PATH}?News_page={page}"
        status.info(f"🔄 Fetching {path}")
        tiles  = scrape_page(path)
        if not tiles:
            status.warning("⚠️ No tiles found—stopping.")
            break

        # per-page progress bar
        page_bar = st.progress(0, text=f"Parsing {len(tiles)} tiles on page {page}")
        for i, art in enumerate(tiles, 1):
            results.append(art)
            page_bar.progress(i / len(tiles))

        # done with page
        oldest = min(datetime.fromisoformat(a["date"]) for a in tiles)
        if oldest < CUTOFF:
            status.success("✅ Reached cutoff date—done.")
            break
        page += 1
        main_prog.progress(min(page / 15, 1.0))   # rough overall progress

    status.success(f"✅ Parsed {len(results)} articles ≥ {CUTOFF:%d %b %Y}")
    main_prog.empty()
    return results

# ───────────────────────── Streamlit UI
st.title("Vema blog scraper → Make webhook")

hook = st.text_input("Make webhook URL", value=DEFAULT_HOOK, type="password")
status_box  = st.empty()       # live status messages
overall_bar = st.progress(0)   # main progress bar

if st.button("Scrape & show"):
    with st.spinner("Initialising scraper…"):
        arts = scrape_all(status_box, overall_bar)
    st.dataframe(pd.DataFrame(arts))

if st.button("Send to Make") and hook:
    with st.spinner("Scraping & pushing…"):
        arts = scrape_all(status_box, overall_bar)
        # single POST with all articles
        try:
            requests.post(hook, json={"articles": arts}, timeout=30)
            st.success(f"✅ Sent {len(arts)} articles to Make")
        except Exception as e:
            st.error(f"❌ Failed to POST to Make – {e}")

# ───────────────────────── Head-less /send endpoint
if st.secrets.get("viewer_api"):                         # Streamlit Cloud flag
    import streamlit.web.bootstrap as bootstrap
    from fastapi import FastAPI

    api = FastAPI()

    @api.get("/send")
    def send_now():
        if not hook:
            return {"error": "Webhook not configured"}
        dummy_status = st.empty()
        dummy_prog   = st.progress(0)
        arts = scrape_all(dummy_status, dummy_prog)
        requests.post(hook, json={"articles": arts}, timeout=30)
        dummy_status.empty(); dummy_prog.empty()
        return {"sent": len(arts)}

    bootstrap.add_fastapi(api)
