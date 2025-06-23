# app.py  –  Vema Blog scraper  v1.8
# • Correct ?News_page= pagination
# • Progress bar & status
# • Sends ONE JSON payload with title, url, image, date, summary
# • Summary = first non-empty <p> or OG/meta description
# • /send endpoint for hands-off scheduling

import os, re, requests, streamlit as st, pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict

# ───────────────────────── CONFIG
BASE_URL   = "https://www.vema.sk"
START_PATH = "/sk-sk/svet-vema"
TILE_SEL   = "div.blog__item"
DATE_RE    = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")
CUTOFF     = datetime(2024, 1, 1)
HEADERS    = {"User-Agent": "Mozilla/5.0 VemaScraper/1.8"}
TIMEOUT    = 20
DEFAULT_HOOK = os.getenv("MAKE_WEBHOOK_URL", "")

# ───────────────────────── HELPERS
def soup_from(url: str) -> BeautifulSoup:
    html = requests.get(url, headers=HEADERS, timeout=TIMEOUT).text
    return BeautifulSoup(html, "html.parser")


def summary_from_page(url: str) -> str:
    """Return first meaningful paragraph; else meta/OG description."""
    try:
        s = soup_from(url)

        # 1️⃣ first non-empty <p> anywhere in article/body
        for p in s.select("article p, main p, body p"):
            txt = p.get_text(strip=True)
            if txt:
                return txt

        # 2️⃣ meta description fallbacks
        meta = (
            s.select_one('meta[property="og:description"]')
            or s.select_one('meta[name="description"]')
        )
        if meta and meta.get("content"):
            return meta["content"].strip()
    except Exception:
        pass
    return ""


def parse_tile(tile) -> Dict[str, str] | None:
    # headline link
    link_tag = tile.select_one(".blog__content h3 a")
    if not link_tag or not link_tag.get("href"):
        return None
    href = link_tag["href"]
    url  = href if href.startswith("http") else BASE_URL + href
    title = link_tag.get_text(strip=True)

    # date
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

    # image
    img = ""
    bg = tile.select_one(".blog__media-inner")
    if bg and bg.has_attr("style"):
        if (m_img := re.search(r"url\(([^)]+)\)", bg["style"])):
            img = BASE_URL + m_img.group(1)

    summary = summary_from_page(url)

    return {
        "title":   title,
        "url":     url,
        "image":   img,
        "date":    pub.isoformat(),
        "summary": summary
    }


def scrape_page(path: str) -> List[Dict[str, str]]:
    soup = soup_from(BASE_URL + path)
    return [art for t in soup.select(TILE_SEL) if (art := parse_tile(t))]


def scrape_all(status, progress) -> List[Dict[str, str]]:
    out, page = [], 1
    while True:
        path = START_PATH if page == 1 else f"{START_PATH}?News_page={page}"
        status.info(f"🔄 Fetching {path}")
        items = scrape_page(path)
        if not items:
            status.warning("⚠️ No tiles found — stopping.")
            break

        bar = st.progress(0, text=f"Parsing {len(items)} tiles on page {page}")
        for i, art in enumerate(items, 1):
            out.append(art)
            bar.progress(i / len(items))

        if min(datetime.fromisoformat(a["date"]) for a in items) < CUTOFF:
            status.success("✅ Reached cutoff date — done.")
            break
        page += 1
        progress.progress(min(page / 15, 1.0))
    status.success(f"✅ Parsed {len(out)} articles ≥ {CUTOFF:%d %b %Y}")
    progress.empty()
    return out

# ───────────────────────── STREAMLIT UI
st.title("Vema blog scraper → Make webhook")

hook = st.text_input("Make webhook URL", value=DEFAULT_HOOK, type="password")
status_box  = st.empty()
overall_bar = st.progress(0)

if st.button("Scrape & show"):
    with st.spinner("Initialising scraper…"):
        data = scrape_all(status_box, overall_bar)
    st.dataframe(pd.DataFrame(data))

if st.button("Send to Make") and hook:
    with st.spinner("Scraping & posting to Make…"):
        arts = scrape_all(status_box, overall_bar)
        try:
            requests.post(hook, json={"articles": arts}, timeout=30)
            st.success(f"✅ Sent {len(arts)} articles to Make")
        except Exception as e:
            st.error(f"❌ POST failed: {e}")

# ───────────────────────── /send endpoint
if st.secrets.get("viewer_api"):
    import streamlit.web.bootstrap as bootstrap
    from fastapi import FastAPI

    api = FastAPI()

    @api.get("/send")
    def send_now():
        if not hook:
            return {"error": "Webhook not configured"}
        dummy_status, dummy_prog = st.empty(), st.progress(0)
        arts = scrape_all(dummy_status, dummy_prog)
        requests.post(hook, json={"articles": arts}, timeout=30)
        dummy_status.empty(); dummy_prog.empty()
        return {"sent": len(arts)}

    bootstrap.add_fastapi(api)
