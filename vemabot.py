# app.py  –  Vema blog scraper  v2.0  (CZ + SK, all date forms)
#
# • Works on https://www.vema.cz/cs-cz/svet-vema
#   and  https://www.vema.sk/sk-sk/svet-vema
# • Handles numeric dates, CZ genitive, SK nominative & genitive
# • Stops when article date < CUTOFF
# • Sends one JSON payload with title, url, image, date, summary

import os
import re
import requests
import streamlit as st
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict

# ───────────────────────── CONFIG ──────────────────────────
# Choose which site you scrape ↓  (cz OR sk)
BASE_URL   = "https://www.vema.sk
START_PATH = "/sk-sk/svet-vema"          # "/sk-sk/svet-vema" for Slovak site
TILE_SEL   = "div.blog__item"

# Numeric date  "28. 5. 2024"
DATE_NUM = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")

# Month-word date  "15. března 2024", "31. marca 2024", "16. máj 2025"
DATE_WORD = re.compile(
    r"(\d{1,2})\.\s*([A-Za-zÁÄČĎÉĚÍĹĽŇÓÔŘŠŤÚŮÝŽáäčďéěíĺľňóôřšťúůýž]+)\s*(\d{4})"
)

# Normalise → map to month number
MONTH_STEM = {
    # Czech & Slovak stems
    "led": 1, "uno": 2, "úno": 2,
    "bre": 3, "bře": 3, "mar": 3,
    "dub": 4, "apr": 4,
    "kve": 5, "máj": 5, "maj": 5, "maj": 5,
    "cer": 6, "čer": 6,
    "cvc": 7, "cve": 7, "čec": 7, "črv": 7, "jul": 7, "júl": 7,
    "srp": 8, "aug": 8,
    "zar": 9, "zář": 9, "sep": 9,
    "rij": 10, "říj": 10, "okt": 10,
    "lis": 11, "nov": 11,
    "pro": 12, "dec": 12,
}

CUTOFF = datetime(2024, 1, 1)
HEADERS = {"User-Agent": "Mozilla/5.0 VemaScraper/2.0"}
TIMEOUT = 20
DEFAULT_HOOK = os.getenv("MAKE_WEBHOOK_URL", "")

# ───────────────────────── UTILITIES ───────────────────────
def soup_from(url: str) -> BeautifulSoup:
    html = requests.get(url, headers=HEADERS, timeout=TIMEOUT).text
    return BeautifulSoup(html, "html.parser")


def month_from_word(word: str) -> int:
    """Return month number from CZ/SK month word (genitive or nominative)."""
    tx = (
        word.lower()
        .replace("á", "a").replace("ä", "a").replace("á", "a")
        .replace("č", "c").replace("ď", "d").replace("é", "e").replace("ě", "e")
        .replace("í", "i").replace("ľ", "l").replace("ĺ", "l")
        .replace("ň", "n").replace("ó", "o").replace("ô", "o")
        .replace("ř", "r").replace("š", "s").replace("ť", "t")
        .replace("ú", "u").replace("ů", "u").replace("ý", "y").replace("ž", "z")
    )
    stem = tx[:3]  # first three letters
    return MONTH_STEM.get(stem, 0)


def summary_from_page(url: str) -> str:
    """Return first meaningful paragraph; else meta/OG description."""
    try:
        s = soup_from(url)
        for p in s.select("article p, main p, body p"):
            txt = p.get_text(strip=True)
            if txt:
                return txt
        meta = (
            s.select_one('meta[property="og:description"]')
            or s.select_one('meta[name="description"]')
        )
        if meta and meta.get("content"):
            return meta["content"].strip()
    except Exception:
        pass
    return ""


# ───────────────────────── CORE PARSER ─────────────────────
def parse_tile(tile) -> Dict[str, str] | None:
    link_tag = tile.select_one(".blog__content h3 a")
    if not link_tag or not link_tag.get("href"):
        return None
    href = link_tag["href"]
    url = href if href.startswith("http") else BASE_URL + href
    title = link_tag.get_text(strip=True)

    date_li = tile.select_one(".blog__footer .blog__info ul li:nth-of-type(2)")
    if not date_li:
        return None
    date_txt = date_li.get_text(strip=True)

    # 1) numeric
    m = DATE_NUM.search(date_txt)
    if m:
        day, month, year = map(int, m.groups())
    else:
        # 2) month word
        m = DATE_WORD.search(date_txt)
        if not m:
            return None
        day, word, year = m.groups()
        month = month_from_word(word)
        if month == 0:
            return None
        day, year = int(day), int(year)

    pub = datetime(year, month, day)
    if pub < CUTOFF:
        return None

    img = ""
    bg = tile.select_one(".blog__media-inner")
    if bg and bg.has_attr("style"):
        if (m_img := re.search(r"url\(([^)]+)\)", bg["style"])):
            img = BASE_URL + m_img.group(1)

    return {
        "title": title,
        "url": url,
        "image": img,
        "date": pub.isoformat(),
        "summary": summary_from_page(url),
    }


def scrape_page(path: str) -> List[Dict[str, str]]:
    soup = soup_from(BASE_URL + path)
    return [a for t in soup.select(TILE_SEL) if (a := parse_tile(t))]


def scrape_all(status, progress) -> List[Dict[str, str]]:
    out, page = [], 1
    while True:
        path = START_PATH if page == 1 else f"{START_PATH}?News_page={page}"
        status.info(f"🔄 Fetching {path}")
        items = scrape_page(path)
        if not items:
            status.warning("⚠️ No tiles found — stopping.")
            break

        for i, art in enumerate(items, 1):
            out.append(art)
            progress.progress(i / len(items), text=f"Page {page}")

        if min(datetime.fromisoformat(a["date"]) for a in items) < CUTOFF:
            status.success("✅ Cut-off reached")
            break
        page += 1

    status.success(f"✅ Parsed {len(out)} articles ≥ {CUTOFF:%d %b %Y}")
    progress.empty()
    return out

# ───────────────────────── STREAMLIT UI ────────────────────
st.title("Vema blog scraper → Make webhook")

hook = st.text_input("Make webhook URL", value=DEFAULT_HOOK, type="password")
status_box = st.empty()
progress_bar = st.empty()

if st.button("Scrape & show"):
    with st.spinner("Running scraper…"):
        data = scrape_all(status_box, progress_bar)
    st.dataframe(pd.DataFrame(data))

if st.button("Send to Make") and hook:
    with st.spinner("Scraping & posting…"):
        arts = scrape_all(status_box, progress_bar)
        try:
            requests.post(hook, json={"articles": arts}, timeout=30)
            st.success(f"Sent {len(arts)} articles to Make")
        except Exception as e:
            st.error(f"POST failed: {e}")

# ───────────────────────── /send endpoint (optional) ───────
if st.secrets.get("viewer_api"):
    import streamlit.web.bootstrap as bootstrap
    from fastapi import FastAPI

    api = FastAPI()

    @api.get("/send")
    def send_now():
        if not hook:
            return {"error": "Webhook not configured"}
        dummy = st.empty()
        arts = scrape_all(dummy, dummy)
        requests.post(hook, json={"articles": arts}, timeout=30)
        dummy.empty()
        return {"sent": len(arts)}

    bootstrap.add_fastapi(api)
