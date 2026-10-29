"""Fetch currently trending news from Google News and find an image for each story."""
import html
import json
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

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
        # the description lists other outlets' headlines for the same story: <li><a>headline</a> <font>source</font>
        desc = item.findtext("description", "")
        related = [(html.unescape(re.sub(r"<[^>]+>", "", h)).strip(), html.unescape(src).strip(), html.unescape(link))
                   for link, h, src in re.findall(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>(?:&nbsp;|\s)*<font[^>]*>(.*?)</font>',
                                                  desc, re.S)]
        items.append({
            "title": title.strip(),
            "link": item.findtext("link", ""),
            "source": source,
            "published": parsedate_to_datetime(pub).isoformat() if pub else "",
            # (headline, source, link) of other outlets covering the same story
            "related": [r for r in related if r[0] and r[0].lower() != title.strip().lower()],
        })
    return items


# Google News searches for natural disasters (last 2 days); the label becomes the story's topic
DISASTER_SEARCHES = {
    "EARTHQUAKE": "earthquake OR tsunami OR aftershock",
    "STORM": "hurricane OR typhoon OR cyclone OR tropical storm",
    "WILDFIRE": "wildfire OR bushfire OR forest fire",
    "FLOOD": "flood OR flash flood OR flooding OR monsoon",
    "TORNADO": "tornado OR severe storms OR hailstorm",
    "VOLCANO": "volcano eruption OR volcanic",
    "LANDSLIDE": "landslide OR mudslide OR avalanche",
    "EXTREME WEATHER": "heatwave OR drought OR blizzard OR winter storm",
}
DISASTER_WORDS = re.compile(
    r"earthquake|quake|tremor|magnitude|tsunami|hurricane|typhoon|cyclone|tropical storm|storm|tornado|twister|"
    r"flood|flooding|monsoon|wildfire|bushfire|forest fire|blaze|volcan|eruption|lava|landslide|mudslide|"
    r"avalanche|heatwave|heat wave|drought|blizzard|snowstorm|hail|evacuat|disaster", re.I)
# sports teams and other false friends ("Carolina Hurricanes", "Colorado Avalanche", "stock market storm"...)
NOT_DISASTER = re.compile(
    r"\b(NHL|NBA|WNBA|NFL|MLB|NCAA|playoffs?|coach|vs\.?|"
    r"Carolina Hurricanes|Miami Hurricanes|Colorado Avalanche|Miami Heat|Tampa Bay Lightning|Thunder|Seattle Storm|"
    r"Cyclones|Iowa State|stocks?|markets?|Nasdaq|Dow|S&P|shares|investors|crypto|bitcoin|election|polls?)\b", re.I)


def _search_url(query):
    params = f"hl={config.NEWS_LANGUAGE}-{config.NEWS_COUNTRY}&gl={config.NEWS_COUNTRY}&ceid={config.NEWS_COUNTRY}:{config.NEWS_LANGUAGE}"
    return f"https://news.google.com/rss/search?q={quote(query + ' when:2d')}&{params}"


def _fetch_feeds(feeds, limit, keep=lambda s: True):
    seen, stories = set(), []
    for topic, url in feeds:
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"[news] {topic} failed: {e}")
            continue
        for s in _parse(r.text):
            key = re.sub(r"\W+", "", s["title"].lower())[:60]
            if key and key not in seen and keep(s):
                seen.add(key)
                s["key"] = key
                s["topic"] = topic
                stories.append(s)
    stories.sort(key=lambda s: s["published"], reverse=True)
    return stories[:limit]


def fetch_trending(limit=40):
    """Stories for the configured focus: natural disasters (default) or all top stories."""
    if config.NEWS_FOCUS == "disasters":
        def is_disaster(story):
            return bool(DISASTER_WORDS.search(story["title"])) and not NOT_DISASTER.search(story["title"])

        stories = _fetch_feeds([(t, _search_url(q)) for t, q in DISASTER_SEARCHES.items()], limit, is_disaster)
        print(f"[news] {len(stories)} natural disaster stories")
        return stories
    return _fetch_feeds([("TOP", _rss_url())] + [(t, _rss_url(t)) for t in TOPICS], limit)


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
    host = urlparse(url).netloc
    if host.endswith("news.google.com"):
        print("[news] could not resolve the Google News link to the article")
        return ctx
    try:
        page = requests.get(url, headers=UA, timeout=20, allow_redirects=True).text
    except requests.RequestException as e:
        print(f"[news] article {host} unreachable ({type(e).__name__})")
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
    print(f"[news] article {host}: {len(ctx['text'])} chars of text, photo {'yes' if ctx['image'] else 'no'}")
    return ctx


STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by", "from", "is", "are",
             "was", "were", "be", "has", "have", "had", "now", "what", "why", "how", "who", "after", "says", "new"}


def wikimedia_images(query, limit=5):
    """Freely licensed photos for the query; long queries that match nothing are retried with key words."""
    words = [w for w in re.findall(r"[\w'-]+", query) if w.lower() not in STOPWORDS and len(w) > 2]
    names = [w for w in words if w[0].isupper()]
    attempts = [query, " ".join(names[:3]), " ".join(names[:2]), " ".join(words[:2]), (names or words or [""])[0]]
    for attempt in dict.fromkeys(a for a in attempts if a):
        found = _wikimedia_search(attempt, limit)
        if found:
            return found
    return []


def _wikimedia_search(query, limit):
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


def wikipedia_images(query, limit=3):
    """Lead photos of the Wikipedia pages matching the query (people, places, organisations)."""
    if not query:
        return []
    try:
        r = requests.get(
            f"https://{config.NEWS_LANGUAGE or 'en'}.wikipedia.org/w/api.php",
            params={"action": "query", "format": "json", "generator": "search", "gsrsearch": query,
                    "gsrlimit": limit, "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 1600},
            headers=WIKI_UA, timeout=20,
        )
        pages = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
        return [p["thumbnail"]["source"] for p in pages if p.get("thumbnail", {}).get("source")]
    except (requests.RequestException, ValueError, KeyError):
        return []


def related_images(story, limit=3):
    """Photos from other outlets' articles on the same story."""
    urls = []
    for _headline, _source, link in story.get("related", [])[:limit]:
        image = _og_image(resolve_google_news(link))
        if image:
            urls.append(image)
    return urls


def key_names(text):
    """Proper-noun phrases from a headline, longest first ("Christine Lagarde", "European Central Bank")."""
    words = re.findall(r"[\w'’-]+", text)
    phrases, current = [], []
    for w in words + [""]:
        if w[:1].isupper() and w.lower() not in STOPWORDS:
            current.append(w)
        else:
            if current:
                phrases.append(" ".join(current))
            current = []
    return sorted(dict.fromkeys(phrases), key=len, reverse=True)


def cover_candidates(story, ctx, query):
    """Photo URLs for the cover, best first: the article's photo, Wikipedia lead photos of the people/places
    named, other outlets' photos, then Wikimedia Commons."""
    yield from [ctx["image"]] if ctx.get("image") else []
    for name in ([query] if query else []) + key_names(story["title"])[:3]:
        yield from wikipedia_images(name, 2)
    yield from related_images(story)
    yield from wikimedia_images(query or story["title"], 3)
    if config.NEWS_FOCUS == "disasters" and story.get("topic") in DISASTER_SEARCHES:
        # last resort: a real photo of this kind of disaster
        yield from wikimedia_images(f"{story['topic'].lower()} damage", 3)


def find_image_url(story, keywords=""):
    return _og_image(resolve_google_news(story["link"])) or next(iter(wikimedia_images(keywords or story["title"], 1)), None)


def download_image(url, dest):
    r = requests.get(url, headers=WIKI_UA if "wikimedia.org" in url else UA, timeout=30)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def search_url(query):
    return f"https://news.google.com/search?q={quote(query)}"
