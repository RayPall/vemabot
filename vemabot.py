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


def scrape_page(path: str) -> L_
