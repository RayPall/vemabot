import os, re, requests, streamlit as st
from bs4 import BeautifulSoup
from datetime import datetime
import pandas as pd
import requests

# ─── CONFIG ───────────────────────────────────────────────────────────────
BASE_URL       = "https://www.vema.cz"
START_PATH     = "/cs-cz/svet-vema"    # blog landing page
DATE_RE        = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")
CUTOFF         = datetime(2024, 1, 1)   # keep articles on/after this date
DEFAULT_HOOK   = os.getenv("MAKE_WEBHOOK_URL", "")  # set in Streamlit secrets

# ─── SCRAPER ──────────────────────────────────────────────────────────────
def fetch_page(url: str) -> BeautifulSoup:
    html = requests.get(url, timeout=20).text
    return BeautifulSoup(html, "html.parser")

def parse_tile(tile) -> dict | None:
    """Return dict(title,url,date) or None if date < cutoff."""
    link_tag = tile["href"] if tile.has_attr("href") else None
    if not link_tag: return None
    url   = BASE_URL + link_tag
    title = tile.select_one(".blog__title").get_text(strip=True)

    # date lives in second <li> under .blog__info ul
    raw = tile.select_one(".blog__info ul li:nth-of-type(2)").get_text(strip=True)
    m   = DATE_RE.search(raw)
    if not m: return None
    day, month, year = map(int, m.groups())
    pubdate = datetime(year, month, day)

    if pubdate < CUTOFF:
        return None
    return {"title": title, "url": url, "date": pubdate.isoformat()}

def scrape_all() -> list[dict]:
    """Follow pagination until no further pages; stop if next page is < cutoff."""
    results, page_idx = [], 1
    while True:
        path   = f"{START_PATH}?p={page_idx}" if page_idx > 1 else START_PATH
        soup   = fetch_page(BASE_URL + path)
        tiles  = soup.select("a.blog__item")
        if not tiles:
            break

        for t in tiles:
            art = parse_tile(t)
            if not art:
                continue
            results.append(art)

        # stop pagination if oldest article on page is already < cutoff
        oldest = min(datetime.fromisoformat(a["date"]) for a in results[-len(tiles):])
        if oldest < CUTOFF:
            break
        page_idx += 1
    return results

# ─── STREAMLIT UI ─────────────────────────────────────────────────────────
st.title("Vema Blog → Make webhook")
hook = st.text_input("Make webhook URL", value=DEFAULT_HOOK, type="password")

if st.button("Scrape & show"):
    data = scrape_all()
    df   = pd.DataFrame(data)
    st.success(f"Found {len(df)} articles since {CUTOFF:%d %b %Y}")
    st.dataframe(df)

if st.button("Send to Make") and hook:
    data = scrape_all()
    sent, fail = 0, 0
    for art in data:
        try:
            requests.post(hook, json=art, timeout=10)
            sent += 1
        except Exception as e:
            st.error(f"❌ {art['title'][:40]}… – {e}")
            fail += 1
    st.success(f"✅ Sent {sent} articles  ❌ {fail} failed")

# expose a lightweight /send JSON route so a ping keeps it headless-friendly
if st.secrets.get("viewer_api"):  # Streamlit Cloud sets this
    import streamlit.web.bootstrap as bootstrap
    from fastapi import FastAPI
    app = FastAPI()

    @app.get("/send")
    def send_endpoint():
        if not hook:
            return {"error": "No webhook set"}
        data = scrape_all()
        for art in data:
            requests.post(hook, json=art, timeout=10)
        return {"sent": len(data)}

    bootstrap.add_fastapi(app)
