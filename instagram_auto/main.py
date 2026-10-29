"""Trending news -> Pubity-style post + reel -> Instagram, every few hours.

    python main.py              # run once (post now)
    python main.py --dry-run    # make the images/video but don't upload
    python main.py --loop       # keep running, one round every INTERVAL_HOURS
    python app.py               # Windows desktop app
"""
import argparse
import json
import re
import time
from datetime import datetime, timezone

import ai
import config
import l10n
import news
import reel
import render

MAX_FACT_SLIDES = 4  # cover + up to 4 fact slides + follow slide = 3-6 images
HASHTAGS = 5


def load_state():
    if config.STATE_FILE.exists():
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    return {"posted": [], "runs": 0}


def save_state(state):
    config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["posted"] = state["posted"][-500:]
    config.STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


ABBREVIATIONS = ("Mr", "Mrs", "Ms", "Dr", "St", "Jr", "Sr", "vs", "No", "Gov", "Sen", "Rep", "Gen", "Prof", "Inc", "Co")


def space_sentences(text):
    """A blank line after every full stop that ends a sentence (not after ? or !, abbreviations or decimals)."""
    abbrev = "".join(f"(?<!\\b{a})" for a in ABBREVIATIONS)
    # a lowercase letter, digit or closing quote/bracket before the stop rules out initials like "U.S."
    text = re.sub(rf"(?<=[a-z0-9)\"'”’]){abbrev}\.[ \t]+(?=\S)", ".\n\n", text)
    # Korean sentences end in a Hangul syllable before the stop; Japanese uses "。"
    text = re.sub(r"(?<=[\uac00-\ud7a3])\.[ \t]+(?=\S)", ".\n\n", text)
    return re.sub(r"。[ \t]*(?=[^\s」』）)])", "。\n\n", text)


def build_caption(pick, story, details):
    """Detailed description + follow line + source + 5 hashtags."""
    text = space_sentences(details.get("caption") or pick.get("caption", ""))
    tags, seen = [], set()
    for tag in list(details.get("hashtags", [])) + list(pick.get("hashtags", [])):
        tag = re.sub(r"[^\w]", "", str(tag).lstrip("#"))
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append("#" + tag)
    source = "\n" + l10n.t("source", source=story["source"]) if story.get("source") else ""
    follow = "\n\n" + l10n.t("follow_line_", handle=config.BRAND_HANDLE)
    return f"{text}{follow}{source}\n\n{' '.join(tags[:HASHTAGS])}".strip()[:2200]


def find_cover(story, ctx, query, workdir, tag):
    """A real photo related to the story for the front, or None if none can be found.

    Channels start from different candidates (English the best, Korean the 2nd, Japanese the 3rd) so the
    same story doesn't get identical posts; if fewer exist, the last one found is used.
    """
    prefer, found, tried = config.CHANNEL_INDEX, [], set()
    for url in news.cover_candidates(story, ctx, query):
        if url in tried:
            continue
        tried.add(url)
        dest = workdir / f"{tag}_cover{len(found)}.img"
        try:
            news.download_image(url, dest)
            render.load_photo(dest, (64, 64))  # validate it opens
            found.append((dest, url))
            if len(found) > prefer:
                break
        except Exception as e:  # bad download or unreadable image
            print(f"[main] cover photo skipped ({e})")
    return found[-1] if found else (None, None)


def gather_photos(story, ctx, queries, needed, workdir, tag, cover=None, cover_url=None):
    """`needed` different photos starting with the cover; Wikimedia photos per query; text cards fill gaps."""
    queries = list(dict.fromkeys(q for q in queries if q))
    results = [news.wikipedia_images(q, 2) + news.wikimedia_images(q, 3) for q in queries]
    urls = [ctx["image"]] if ctx.get("image") and ctx["image"] != cover_url else []
    for rank in range(4):  # one photo per query first, so slides about different things get different photos
        for found in results:
            if rank < len(found) and found[rank] not in urls:
                urls.append(found[rank])
    photos = [cover] if cover else []
    for url in urls:
        if len(photos) == needed:
            break
        dest = workdir / f"{tag}_photo{len(photos)}.img"
        try:
            news.download_image(url, dest)
            render.load_photo(dest, (64, 64))  # validate it opens
            photos.append(dest)
        except Exception as e:  # bad download or unreadable image
            print(f"[main] photo skipped ({e})")
    if len(photos) < needed:
        print(f"[main] found {len(photos)}/{needed} photos for: {story['title']} — filling with text cards")
    while len(photos) < needed:
        photos.append(render.text_card_background(story.get("source") or story.get("topic", ""),
                                                  workdir / f"{tag}_card{len(photos)}.jpg"))
    # each language channel shows the inner photos in a different order
    first, rest = photos[:1], photos[1:]
    shift = config.CHANNEL_INDEX % len(rest) if rest else 0
    return first + rest[shift:] + rest[:shift]


def build_album(pick, story, ctx, details, cover, workdir, stamp):
    """Cover + 2-4 fact slides (each with its own photo) + follow slide = 3-6 images."""
    slides = details["slides"]
    queries = [sl.get("image_query", "") for sl in slides] + [pick.get("image_query", ""), story["title"]]
    photos = gather_photos(story, ctx, queries, 1 + len(slides), workdir, "post", *cover)
    # nothing more to tell than the headline: a comment slide keeps the carousel at 3 slides
    total = max(len(slides), 1) + 2
    images = [render.feed_post(photos[0], pick["headline"], pick.get("highlight"),
                               workdir / f"post-{stamp}-1.jpg", swipe=True)]
    for i, (slide, photo) in enumerate(zip(slides, photos[1:]), start=2):
        images.append(render.fact_slide(photo, slide["text"], slide.get("highlight"), i, total,
                                        workdir / f"post-{stamp}-{i}.jpg"))
    if not slides:
        print("[main] no story details found — adding a comment slide")
        images.append(render.question_slide(photos[0], workdir / f"post-{stamp}-2.jpg", 2, total))
    images.append(render.cta_slide(workdir / f"post-{stamp}-{total}.jpg", total, total))
    return images


def run_once(dry_run=False, poster=None, only=None):
    """One round: returns the list of media files made. only="reel"/"post" forces that kind."""
    state = load_state()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    workdir = config.OUTPUT_DIR / stamp
    workdir.mkdir(parents=True, exist_ok=True)

    if only:
        kinds = [only]
    elif config.POST_MODE == "alternate":
        # one upload per round, taking turns: reel, then carousel post, then reel...
        kinds = ["post" if state.get("last_kind") == "reel" else "reel"]
    else:
        kinds = {"both": ["post", "reel"], "post": ["post"], "reel": ["reel"]}[config.POST_MODE]
    stories = news.fetch_trending()
    if not stories:
        print("[main] no news fetched — skipping this round")
        return []
    # a few spare stories, so one without a related photo for the front can be skipped
    picks = ai.pick_and_write(stories, len(kinds) + 3, set(state["posted"]))
    if not picks:
        print("[main] no new stories this round")
        return []
    by_id = {s["id"]: s for s in stories}

    built = []
    for kind in kinds:
        if not picks:
            break
        for pick in list(picks):
            story = by_id[pick["id"]]
            ctx = news.article_context(story)
            cover = find_cover(story, ctx, pick.get("image_query", ""), workdir, kind)
            if cover[0]:
                break
            print(f"[main] no related photo for: {story['title']} — trying the next story")
        else:
            print("[main] no story with a related photo — using a text card on the front")
            pick = picks[0]
            story, ctx, cover = by_id[pick["id"]], news.article_context(by_id[pick["id"]]), (None, None)
        picks.remove(pick)
        details = ai.write_details(pick, story, ctx["text"], n_slides=MAX_FACT_SLIDES if kind == "post" else 0)
        ai.localize(pick, details)  # nothing left in English on the Korean/Japanese channels
        caption = build_caption(pick, story, details)
        (workdir / f"{kind}_caption.txt").write_text(caption, encoding="utf-8")
        if kind == "post":
            media = build_album(pick, story, ctx, details, cover, workdir, stamp)
            cover_img = media[0]
        else:
            lines = [l for l in (pick.get("reel_lines") or []) if l][:3] or [""]
            photos = gather_photos(story, ctx, [pick.get("image_query", ""), story["title"]], len(lines), workdir,
                                   "reel", *cover)
            media = [reel.build_reel(photos, pick, workdir, workdir / f"reel-{stamp}.mp4")]
            cover_img = reel.extract_cover(media[0], workdir / f"reel-{stamp}.jpg")
        print(f"[main] {kind} ({len(media)} file{'s' if len(media) > 1 else ''}): {pick['headline']}")
        built.append((kind, pick, story, media, caption, cover_img))

    if not dry_run and poster is None:
        poster = __import__("poster").get_poster()
    for kind, pick, story, media, caption, cover in built:
        if dry_run:
            continue
        try:
            if kind == "post":
                code = poster.post_album(media, caption)
            else:
                code = poster.post_reel(media[0], caption, cover)
            print(f"[main] uploaded {kind}: {code}")
            state["posted"].append(story["key"])
            state["last_kind"] = kind
        except Exception as e:
            print(f"[main] upload of {kind} failed: {e}")

    state["runs"] = state.get("runs", 0) + 1
    state["last_run"] = stamp
    save_state(state)
    return [path for b in built for path in b[3]]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="create media but don't upload")
    parser.add_argument("--loop", action="store_true", help=f"repeat every INTERVAL_HOURS ({config.INTERVAL_HOURS}h)")
    args = parser.parse_args()
    while True:
        try:
            run_once(dry_run=args.dry_run)
        except Exception as e:
            if not args.loop:
                raise
            print(f"[main] round failed: {e}")
        if not args.loop:
            break
        print(f"[main] next round in {config.INTERVAL_HOURS}h")
        time.sleep(config.INTERVAL_HOURS * 3600)


if __name__ == "__main__":
    main()
