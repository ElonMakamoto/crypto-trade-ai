"""Fetch currently trending news from Google News and find an image for each story."""
import html
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

import config

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
TOPICS = ["WORLD", "ENTERTAINMENT", "SPORTS", "TECHNOLOGY", "SCIENCE"]


def _rss_url(topic=None):
    params = f"hl={config.NEWS_LANGUAGE}-{config.NEWS_COUNTRY}&gl={config.NEWS_COUNTRY}&ceid={config.NEWS_COUNTRY}:{config.NEWS_LANGUAGE}"
    if topic:
        return f"https://news.google.com/rss/headlines/section/topic/{topic}?{params}"
    return f"https://news.google.com/rss?{params}"


def _parse(xml_text):
    items = []
    for item in ET.fromstring(xml_text).iter("item"):
        title = html.unescape(item.findtext("title", ""))
        source = item.findtext("source", "")
        # Google appends " - Source" to titles
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        pub = item.findtext("pubDate")
        items.append({
            "title": title.strip(),
            "link": item.findtext("link", ""),
            "source": source,
            "published": parsedate_to_datetime(pub).isoformat() if pub else "",
        })
    return items


def fetch_trending(limit=40):
    """Top stories plus a few hot sections, de-duplicated, newest first."""
    seen, stories = set(), []
    for topic in [None] + TOPICS:
        try:
            r = requests.get(_rss_url(topic), headers=UA, timeout=20)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"[news] {topic or 'TOP'} failed: {e}")
            continue
        for s in _parse(r.text):
            key = re.sub(r"\W+", "", s["title"].lower())[:60]
            if key and key not in seen:
                seen.add(key)
                s["key"] = key
                s["topic"] = topic or "TOP"
                stories.append(s)
    stories.sort(key=lambda s: s["published"], reverse=True)
    return stories[:limit]


def _og_image(url):
    try:
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
        m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)', r.text, re.I) \
            or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)', r.text, re.I)
        if m and "googleusercontent" not in m.group(1) and "gstatic" not in m.group(1):
            return html.unescape(m.group(1))
    except requests.RequestException:
        pass
    return None


def _wikimedia_image(query):
    """Fallback: a freely licensed photo from Wikimedia Commons matching the query."""
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6, "gsrlimit": 5,
                "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 1600,
            },
            headers=UA, timeout=20,
        )
        pages = r.json().get("query", {}).get("pages", {})
        for p in sorted(pages.values(), key=lambda p: p.get("index", 99)):
            info = (p.get("imageinfo") or [{}])[0]
            if info.get("thumburl"):
                return info["thumburl"]
    except (requests.RequestException, ValueError):
        pass
    return None


def find_image_url(story, keywords=""):
    return _og_image(story["link"]) or _wikimedia_image(keywords or story["title"])


def download_image(url, dest):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def search_url(query):
    return f"https://news.google.com/search?q={quote(query)}"
