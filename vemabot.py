import os, re, requests, streamlit as st, pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict

# ───────────────────────── Configuration
BASE_URL   = "https://www.vema.cz"
START_PATH = "/cs-cz/svet-vema"              # landing page
TILE_SEL   = "div.blog__item"                # every tile is a <div>
DATE_RE    = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")
CUTOFF     = datetime(2024, 1, 1)

DEFAULT_HOOK = os.getenv("MAKE_WEBHOOK_URL", "")  # set in secrets on Streamlit Cloud
HEADERS = {"User-Agent": "Mozilla/5.0 VemaScraper/1.0"}
TIMEOUT = 20

# ───────────────────────── Scraper helpers
def fetch(url: str) -> BeautifulSoup:
    html = requests.get(url, headers=HEADERS, timeout=TIMEOUT).text
    return BeautifulSoup(html, "html.parser")


def parse_tile(tile) -> Dict[str, str] | None:
    """Return dict(title, url, image, date) or None if < CUTOFF."""
    a_tag = tile.select_one(".blog__content h3 a")  # headline link
    if not a_tag or not a_tag.get("href"):
        return None
    url   = BASE_URL + a_tag["href"]
    title = a_tag.get_text(strip=True)

    # second <li> in footer -> raw date e.g. "17. 4. 2025"
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

    img_tag = tile.select_one(".blog__media-inner")
    img_url = ""
    if img_tag and "style" in img_tag.attrs:
        # background-image: url(...)
        m_img = re.search(r"url\(([^)]+)\)", img_tag["style"])
        if m_img:
            img_url = BASE_URL + m_img.group(1)

    return {"title": title, "url": url, "image": img_url, "date": pub.isoformat()}


def scrape_page(path: str) -> List[Dict[str, str]]:
    soup = fetch(BASE_URL + path)
    return [item for t in soup.select(TILE_SEL) if (item := parse_tile(t))]


def scrape_all() -> List[Dict[str, str]]:
    """Follow ?p=2, ?p=3… until oldest article < CUTOFF."""
    out, p = [], 1
    while True:
        path = f"{START_PATH}?p={p}" if p > 1 else START_PATH
        batch = scrape_page(path)
        if not batch:
            break
        out.extend(batch)
        if min(datetime.fromisoformat(a["date"]) for a in batch) < CUTOFF:
            break
        p += 1
    return out

# ───────────────────────── Streamlit UI
st.title("Vema blog scraper → Make webhook")

hook = st.text_input("Make webhook URL", value=DEFAULT_HOOK, type="password")

if st.button("Scrape & show"):
    articles = scrape_all()
    st.success(f"Found {len(articles)} articles since {CUTOFF:%d %b %Y}")
    st.dataframe(pd.DataFrame(articles))

if st.button("Send to Make") and hook:
    sent = 0
    for art in scrape_all():
        try:
            requests.post(hook, json=art, timeout=10)
            sent += 1
        except Exception as e:
            st.error(f"❌ {art['title'][:40]} – {e}")
    st.success(f"✅ Sent {sent} articles to Make")

# ───────────────────────── head-less /send endpoint
if st.secrets.get("viewer_api"):             # Streamlit Cloud flag
    import streamlit.web.bootstrap as bootstrap
    from fastapi import FastAPI

    api = FastAPI()

    @api.get("/send")
    def send_now():
        if not hook:
            return {"error": "no webhook"}
        for art in scrape_all():
            requests.post(hook, json=art, timeout=10)
        return {"sent": len(scrape_all())}

    bootstrap.add_fastapi(api)
