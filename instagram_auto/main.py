"""Trending news -> Pubity-style post + reel -> Instagram, every few hours.

    python main.py              # run once (post now)
    python main.py --dry-run    # make the images/video but don't upload
    python main.py --loop       # keep running, one round every INTERVAL_HOURS
    python app.py               # Windows desktop app
"""
import argparse
import json
import time
from datetime import datetime, timezone

import ai
import config
import news
import reel
import render

MAX_FACT_SLIDES = 4  # cover + up to 4 fact slides + follow slide = 3-6 images


def load_state():
    if config.STATE_FILE.exists():
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    return {"posted": [], "runs": 0}


def save_state(state):
    config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["posted"] = state["posted"][-500:]
    config.STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def build_caption(pick, story):
    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in pick.get("hashtags", []))
    source = f"\n\n📰 Source: {story['source']}" if story.get("source") else ""
    return f"{pick['caption']}{source}\n\n{tags}".strip()[:2200]


def gather_photos(story, ctx, queries, needed, workdir, tag):
    """`needed` different photos: the article's own image, then Wikimedia photos for each query; text cards fill gaps."""
    results = [news.wikimedia_images(q, 4) for q in dict.fromkeys(q for q in queries if q)]
    urls = [ctx["image"]] if ctx.get("image") else []
    for rank in range(4):  # one photo per query first, so slides about different things get different photos
        for found in results:
            if rank < len(found) and found[rank] not in urls:
                urls.append(found[rank])
    photos = []
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
    return photos


def build_album(pick, story, workdir, stamp):
    """Cover + 2-4 fact slides (each with its own photo) + follow slide = 3-6 images."""
    ctx = news.article_context(story)
    slides = ai.write_slides(pick, story, ctx["text"], n=MAX_FACT_SLIDES)
    queries = [pick.get("image_query", "")] + [sl.get("image_query", "") for sl in slides] + [story["title"]]
    photos = gather_photos(story, ctx, queries, 1 + len(slides), workdir, "post")
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
    picks = ai.pick_and_write(stories, len(kinds), set(state["posted"]))
    if not picks:
        print("[main] no new stories this round")
        return []
    by_id = {s["id"]: s for s in stories}

    built = []
    for kind, pick in zip(kinds, picks):
        story = by_id[pick["id"]]
        caption = build_caption(pick, story)
        (workdir / f"{kind}_caption.txt").write_text(caption, encoding="utf-8")
        if kind == "post":
            media = build_album(pick, story, workdir, stamp)
            cover = media[0]
        else:
            lines = [l for l in (pick.get("reel_lines") or []) if l][:3] or [""]
            photos = gather_photos(story, news.article_context(story),
                                   [pick.get("image_query", ""), story["title"]], len(lines), workdir, "reel")
            media = [reel.build_reel(photos, pick, workdir, workdir / f"reel-{stamp}.mp4")]
            cover = reel.extract_cover(media[0], workdir / f"reel-{stamp}.jpg")
        print(f"[main] {kind} ({len(media)} file{'s' if len(media) > 1 else ''}): {pick['headline']}")
        built.append((kind, pick, story, media, caption, cover))

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
