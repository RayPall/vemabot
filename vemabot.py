# app.py
import os
import re
import requests
import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict

# ──────────────────────────── CONFIG ──────────────────────────────────────
BASE_URL   = "https://www.vema.cz"
START_PATH = "/cs-cz/svet-vema"          # landing page with article tiles
TILE_SEL   = "div.blog__item"            # each tile is a <div>, not <a>
DATE_RE    = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")
CUTOFF     = datetime(2024, 1, 1)        # ignore articles older than this

DEFAULT_HOOK = os.getenv("MAKE_WEBHOOK_URL", "")  # set in Streamlit secrets

PAGE_TIMEOUT = 20     # seconds for HTTP requests
HEADERS = {           # polite header so the site sees a browser
    "User-Agent": "Mozilla/5.0 (compatible; VemaScraper/1.0; +https://github.com/)"
}

# ──────────────────────── SCRAPER CORE  ───────────────────────────────────
def fetch_page(url: str) -> BeautifulSoup:
    html = requests.get(url, timeout=PAGE_TIMEOUT, headers=HEADERS).text
    return BeautifulSoup(html, "html.parser")


def parse_tile(tile) -> Dict[str, str] | None:
    """
    Extract title, url, date from one <div class="blog__item">.
    Return None if date < cutoff or pattern not found.
    """
    a_tag = tile.find("a", class_="blog__link")
    if not a_tag or not a_tag.get("href"):
        return None
    url = BASE_URL + a_tag["href"]

    title_tag = tile.select_one(".blog__title")
    if not title_tag:
        return None
    title = title_tag.get_text(strip=True)

    # second <li> inside .blog__info ul holds "16. 5. 2025"
    li_date = tile.select_one(".blog__info ul li:nth-of-type(2)")
    if not li_date:
        return None

    m = DATE_RE.search(li_date.get_text(strip=True))
    if not m:
        return None
    day, month, year = map(int, m.groups())
    pubdate = datetime(year, month, day)
    if pubdate < CUTOFF:
        return None

    img_tag = tile.select_one("img")
    img_url = img_tag["src"] if img_tag and img_tag.has_attr("src") else ""

    return {"title": title, "url": url, "image": img_url, "date": pubdate.isoformat()}


def scrape_index(index_url: str) -> List[Dict[str, str]]:
    """Scrape one page and return list of article dicts."""
    soup = fetch_page(index_url)
    return [a for t in soup.select(TILE_SEL) if (a := parse_tile(t))]


def scrape_all() -> List[Dict[str, str]]:
    """Follow pagination (…?p=2, …) until we hit articles older than cutoff."""
    results, page = [], 1
    while True:
        path = f"{START_PATH}?p={page}" if page > 1 else START_PATH
        page_url = BASE_URL + path
        page_items = scrape_index(page_url)
        if not page_items:
            break
        results.extend(page_items)

        # stop if the oldest item on this page is already before cutoff
        oldest_on_page = min(datetime.fromisoformat(i["date"]) for i in page_items)
        if oldest_on_page < CUTOFF:
            break
        page += 1
    return results


# ───────────────────────── STREAMLIT UI  ──────────────────────────────────
st.title("Vema Blog → Make Webhook")

hook = st.text_input("Make webhook URL", value=DEFAULT_HOOK, type="password")

if st.button("Scrape & show"):
    articles = scrape_all()
    df = pd.DataFrame(articles)
    st.success(f"Found {len(df)} articles since {CUTOFF:%d %b %Y}")
    st.dataframe(df)

if st.button("Send to Make") and hook:
    articles = scrape_all()
    sent, failed = 0, 0
    for art in articles:
        try:
            requests.post(hook, json=art, timeout=10)
            sent += 1
        except Exception as e:
            st.error(f"❌  {art['title'][:40]}…  –  {e}")
            failed += 1
    st.success(f"✅  Sent {sent} articles   ❌  {failed} failed")


# ────────────────────── FASTAPI ENDPOINT (/send) ──────────────────────────
# lets Make (or a crontab) hit https://<app>.streamlit.app/send
if st.secrets.get("viewer_api"):               # Streamlit Cloud sets this
    import streamlit.web.bootstrap as bootstrap
    from fastapi import FastAPI

    api = FastAPI()

    @api.get("/send")
    def send_now():
        if not hook:
            return {"error": "No webhook configured"}
        arts = scrape_all()
        for art in arts:
            requests.post(hook, json=art, timeout=10)
        return {"sent": len(arts)}

    bootstrap.add_fastapi(api)
