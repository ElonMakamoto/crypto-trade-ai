"""Fetch currently trending news from Google News and find an image for each story."""
import html
import json
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

import config

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
# Wikimedia rejects browser-imitating clients with 429; it asks for an identifying User-Agent
WIKI_UA = {"User-Agent": "InstagramAuto/1.0 (https://chedlab.org/instagram) python-requests"}
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


def resolve_google_news(url):
    """news.google.com/rss/articles/<id> only redirects with JavaScript: ask Google for the publisher URL."""
    m = re.search(r"news\.google\.com/(?:rss/)?articles/([^?/]+)", url)
    if not m:
        return url
    art_id = m.group(1)
    try:
        page = requests.get(f"https://news.google.com/articles/{art_id}", headers=UA, timeout=20).text
        sig = re.search(r'data-n-a-sg="([^"]+)"', page).group(1)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page).group(1)
        inner = ["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None,
                                 None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                 art_id, int(ts), sig]
        r = requests.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={**UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data={"f.req": json.dumps([[["Fbv4je", json.dumps(inner), None, "generic"]]])},
            timeout=20,
        )
        rows = json.loads(r.text.split("\n\n")[1])[:-2]
        resolved = json.loads(rows[0][2])[1]
        return resolved if resolved.startswith("http") else url
    except (requests.RequestException, AttributeError, IndexError, ValueError, TypeError):
        return url


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


def article_context(story):
    """The publisher article behind a story: its photo and readable text (for grounded slides)."""
    url = resolve_google_news(story["link"])
    ctx = {"url": url, "image": None, "text": ""}
    try:
        page = requests.get(url, headers=UA, timeout=20, allow_redirects=True).text
    except requests.RequestException:
        return ctx

    def meta(name):
        m = re.search(rf'<meta[^>]+(?:property|name)=["\']{name}["\'][^>]+content=["\']([^"\']+)', page, re.I) \
            or re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{name}["\']', page, re.I)
        return html.unescape(m.group(1)) if m else ""

    image = meta("og:image") or meta("twitter:image")
    if image and "googleusercontent" not in image and "gstatic" not in image:
        ctx["image"] = image
    paragraphs = [html.unescape(re.sub(r"<[^>]+>", "", p)).strip()
                  for p in re.findall(r"<p[^>]*>(.*?)</p>", page, re.S | re.I)]
    body = " ".join(p for p in paragraphs if len(p) > 60)
    ctx["text"] = (meta("og:description") + "\n" + body)[:4000].strip()
    return ctx


def wikimedia_images(query, limit=5):
    """Freely licensed photos from Wikimedia Commons matching the query (best first)."""
    try:
        r = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6, "gsrlimit": limit + 3,
                "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 1600,
            },
            headers=WIKI_UA, timeout=20,
        )
        pages = r.json().get("query", {}).get("pages", {})
        urls = [(p.get("imageinfo") or [{}])[0].get("thumburl")
                for p in sorted(pages.values(), key=lambda p: p.get("index", 99))]
        return [u for u in urls if u][:limit]
    except (requests.RequestException, ValueError):
        return []


def find_image_url(story, keywords=""):
    return _og_image(resolve_google_news(story["link"])) or next(iter(wikimedia_images(keywords or story["title"], 1)), None)


def download_image(url, dest):
    r = requests.get(url, headers=WIKI_UA if "wikimedia.org" in url else UA, timeout=30)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def search_url(query):
    return f"https://news.google.com/search?q={quote(query)}"
