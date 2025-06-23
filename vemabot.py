# app.py  –  Vema SK blog scraper  v1.9-SK
# • Handles numeric dates, nominative words ("máj"), genitive words ("mája")
# • Stops only after CUTOFF (2024-01-01)
# • Sends JSON with title, url, image, date, summary

import os, re, requests, streamlit as st, pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict

# ───────────────────────── CONFIG
BASE_URL   = "https://www.vema.sk"
START_PATH = "/sk-sk/svet-vema"
TILE_SEL   = "div.blog__item"

# "28. 5. 2024" or "28.5.2024"
DATE_NUM   = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")

# "16. máj 2025", "31. marca 2024", "18. apríla 2024" …
DATE_WORD  = re.compile(r"(\d{1,2})\.\s*([A-Za-zÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽáäčďéíĺľňóôŕšťúýž]+)\s*(\d{4})")

# map first three ASCII letters of Slovak month to number
MONTH3 = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "máj": 5, "maj": 5,   # both spellings
    "jún": 6, "jun": 6,
    "júl": 7, "jul": 7,
    "aug": 8,
    "sep": 9,
    "okt": 10,
    "nov": 11,
    "dec": 12,
}

CUTOFF     = datetime(2024, 1, 1)
HEADERS    = {"User-Agent": "Mozilla/5.0 VemaScraper/1.9-SK"}
TIMEOUT    = 20
DEFAULT_HOOK = os.getenv("MAKE_WEBHOOK_URL", "")

# ───────────────────────── HELPERS
def soup_from(url: str) -> BeautifulSoup:
    html = requests.get(url, headers=HEADERS, timeout=TIMEOUT).text
    return BeautifulSoup(html, "html.parser")


def summary_from_page(url: str) -> str:
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


def month_from_word(word: str) -> int:
    stem = (
        word.lower()
        .replace("á", "a").replace("ä", "a")
        .replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ô", "o")
        .replace("ú", "u").replace("ý", "y")
        .replace("č", "c").replace("ď", "d")
        .replace("ľ", "l").replace("ĺ", "l")
        .replace("ň", "n").replace("ť", "t")
        .replace("š", "s").replace("ž", "z")
    )[:3]  # first three letters
    return MONTH3.get(stem, 0)


def parse_tile(tile) -> Dict[str, str] | None:
    link_tag = tile.select_one(".blog__content h3 a")
    if not link_tag or not link_tag.get("href"):
        return None
    href = link_tag["href"]
    url  = href if href.startswith("http") else BASE_URL + href
    title = link_tag.get_text(strip=True)

    li_date = tile.select_one(".blog__footer .blog__info ul li:nth-of-type(2)")
    if not li_date:
        return None
    txt = li_date.get_text(strip=True)

    m = DATE_NUM.search(txt)
    if m:
        day, month, year = map(int, m.groups())
    else:
        m = DATE_WORD.search(txt)
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
st.title("Vema SK blog scraper → Make webhook")

hook = st.text_input("Make webhook URL", value=DEFAULT_HOOK, type="password")
status_box  = st.empty()
overall_bar = st.progress(0)

if st.button("Scrape
