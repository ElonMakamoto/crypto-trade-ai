"""Search data from Naver and Google: related searches, autocomplete, trends, news, and where our posts rank.

Autocomplete and related searches are what real people type, so the writer always works them into the post.
Every function returns [] / None when a site can't be reached, so a round never fails because of them.
"""
import html
import re
import xml.etree.ElementTree as ET
from collections import OrderedDict
from urllib.parse import quote

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6"}


def _get(url, **kw):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, **kw)
        return r if r.ok else None
    except requests.RequestException:
        return None


def norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def squash(text):
    return re.sub(r"\s+", "", (text or "").lower())


# ---------------------------------------------------------------- Naver
def parse_naver_autocomplete(data):
    """The autocomplete JSON -> phrases. Tolerates the old and new answer layouts."""
    out = []

    def first_string(entry):
        if isinstance(entry, str):
            return entry
        if isinstance(entry, list) and entry:
            return first_string(entry[0])
        if isinstance(entry, dict):
            return entry.get("keyword") or entry.get("query") or entry.get("value")
        return None

    for group in data.get("items", []) if isinstance(data, dict) else []:
        for entry in group if isinstance(group, list) else [group]:
            phrase = first_string(entry)
            if phrase and isinstance(phrase, str) and len(phrase) <= 40:
                out.append(html.unescape(phrase).strip())
    return list(OrderedDict.fromkeys(p for p in out if p))


def naver_autocomplete(query):
    r = _get("https://ac.search.naver.com/nx/ac", params={
        "q": query, "con": "1", "frm": "nv", "ans": "2", "r_format": "json", "r_enc": "UTF-8", "r_unicode": "0",
        "t_koreng": "1", "run": "2", "rev": "4", "q_enc": "UTF-8", "st": "100"})
    if not r:
        return []
    try:
        return parse_naver_autocomplete(r.json())
    except ValueError:
        return []


def parse_naver_related(page):
    """'연관검색어' / '함께 많이 찾는' phrases from a Naver search result page."""
    found = []
    blocks = re.findall(r'(?:related_srch|lst_related|relatedSearch|related-keyword|fds-comps-keyword)(.{0,20000})',
                        page, re.S)
    for block in blocks[:3]:
        for pattern in (r'class="tit"[^>]*>(.*?)</div>', r'class="keyword"[^>]*>(?:\s*<[^>]+>)*\s*([^<]{2,40})<',
                        r'data-keyword="([^"]{2,40})"'):
            for raw in re.findall(pattern, block, re.S):
                text = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
                if 2 <= len(text) <= 40 and not text.startswith(("연관", "관련")):
                    found.append(text)
        if found:
            break
    return list(OrderedDict.fromkeys(found))[:15]


def naver_related(query):
    r = _get("https://search.naver.com/search.naver", params={"where": "nexearch", "query": query})
    return parse_naver_related(r.text) if r else []


BLOG_LINK = re.compile(r"https?://(?:m\.)?blog\.naver\.com/([A-Za-z0-9_-]+)/(\d{6,})")


def parse_blog_results(page):
    """Blog posts in a search result page, in the order shown: [(blog_id, log_no), ...]."""
    seen = OrderedDict()
    for blog_id, log_no in BLOG_LINK.findall(page):
        if blog_id.lower() not in ("postview", "prologue", "postlist"):
            seen.setdefault((blog_id.lower(), log_no), None)
    return list(seen)


def naver_rank(keyword, blog_id, log_no=None):
    """Where our blog shows for this keyword: blog tab rank (1 = top) and whether it's on the main search page.
    None values when Naver can't be reached."""
    result = {"blog_rank": None, "main_page": None}
    if not blog_id:
        return result
    blog_id = blog_id.lower()
    r = _get("https://search.naver.com/search.naver", params={"ssc": "tab.blog.all", "query": keyword})
    if r:
        posts = parse_blog_results(r.text)
        result["blog_rank"] = 0  # 0 = not in the first page
        for i, (bid, no) in enumerate(posts, 1):
            if bid == blog_id and (not log_no or no == str(log_no)):
                result["blog_rank"] = i
                break
    r = _get("https://search.naver.com/search.naver", params={"where": "nexearch", "query": keyword})
    if r:
        result["main_page"] = any(bid == blog_id and (not log_no or no == str(log_no))
                                  for bid, no in parse_blog_results(r.text))
    return result


# ---------------------------------------------------------------- Google
def google_suggest(query):
    r = _get("https://suggestqueries.google.com/complete/search",
             params={"client": "firefox", "hl": "ko", "gl": "kr", "ie": "UTF-8", "oe": "UTF-8", "q": query})
    if not r:
        return []
    try:
        import json

        data = json.loads(r.content.decode("utf-8", errors="replace"))
        return [s.strip() for s in data[1] if isinstance(s, str) and s.strip()][:15]
    except (ValueError, IndexError, TypeError):
        return []


def _rss_titles(url, limit=15):
    r = _get(url)
    if not r:
        return []
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return []
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        date = (item.findtext("pubDate") or "").strip()
        if title:
            out.append({"title": html.unescape(title), "date": date[:16]})
        if len(out) >= limit:
            break
    return out


def trending():
    """Today's rising searches in Korea (Google Trends)."""
    return [x["title"] for x in _rss_titles("https://trends.google.com/trending/rss?geo=KR", 20)]


def news(query, limit=10):
    """Recent Korean news headlines about the query (Google News), used as fresh source material."""
    return _rss_titles(f"https://news.google.com/rss/search?q={quote(query + ' when:60d')}&hl=ko&gl=KR&ceid=KR:ko",
                       limit)


# ---------------------------------------------------------------- related searches, merged
def _overlap(phrase, keyword):
    """Share of the keyword's two-letter pieces that the phrase also has (0..1)."""
    k, p = squash(keyword), squash(phrase)
    grams = {k[i:i + 2] for i in range(len(k) - 1)} or {k}
    return sum(1 for g in grams if g in p) / len(grams)


def related(keyword):
    """Related searches for a keyword from Naver (autocomplete + related searches) and Google (autocomplete).
    Returns {"naver": [...], "google": [...], "ranked": [...]} — ranked is merged, best first."""
    naver = naver_autocomplete(keyword) + naver_autocomplete(keyword + " ")
    naver_rel = naver_related(keyword)
    google = google_suggest(keyword) + google_suggest(keyword + " ")
    return merge(keyword, naver, naver_rel, google)


def merge(keyword, naver, naver_rel, google):
    scores, shown = {}, {}
    for weight, items in ((3.0, naver), (3.0, naver_rel), (2.0, google)):
        for i, phrase in enumerate(items):
            key = squash(phrase)
            if not key or key == squash(keyword) or len(phrase) > 30:
                continue
            closeness = _overlap(phrase, keyword)
            score = (weight - i * 0.05) * (1.0 if closeness >= 0.5 else 0.5)
            scores[key] = scores.get(key, 0) + score
            shown.setdefault(key, norm(phrase))
    ranked = [shown[k] for k in sorted(scores, key=lambda k: -scores[k])]
    return {"naver": list(OrderedDict.fromkeys(naver + naver_rel)), "google": list(OrderedDict.fromkeys(google)),
            "ranked": ranked[:20]}
