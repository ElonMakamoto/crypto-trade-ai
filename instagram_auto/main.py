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


def prepare(picks, stories, workdir, needed):
    """Attach a photo to each pick; without one, use a Pubity-style text card background."""
    by_id = {s["id"]: s for s in stories}
    ready = []
    for pick in picks[:needed]:
        story = by_id[pick["id"]]
        photo = workdir / f"photo_{len(ready)}.img"
        url = news.find_image_url(story, pick.get("image_query", ""))
        try:
            if not url:
                raise ValueError("no image found")
            news.download_image(url, photo)
            render.load_photo(photo, (64, 64))  # validate it opens
        except Exception as e:  # no image, bad download or unreadable image
            print(f"[main] no photo for: {story['title']} ({e}) — using a text card")
            photo = render.text_card_background(story.get("source") or story.get("topic", ""),
                                                workdir / f"card_{len(ready)}.jpg")
        ready.append((pick, story, photo))
    return ready


def run_once(dry_run=False, poster=None):
    """One round: returns the list of media files made."""
    state = load_state()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    workdir = config.OUTPUT_DIR / stamp
    workdir.mkdir(parents=True, exist_ok=True)

    kinds = {"both": ["post", "reel"], "post": ["post"], "reel": ["reel"]}[config.POST_MODE]
    stories = news.fetch_trending()
    if not stories:
        print("[main] no news fetched — skipping this round")
        return []
    picks = ai.pick_and_write(stories, len(kinds) + 3, set(state["posted"]))
    ready = prepare(picks, stories, workdir, len(kinds))
    if not ready:
        print("[main] nothing postable this round")
        return []

    built = []
    for kind, (pick, story, photo) in zip(kinds, ready):
        caption = build_caption(pick, story)
        (workdir / f"{kind}_caption.txt").write_text(caption, encoding="utf-8")
        if kind == "post":
            media = cover = render.feed_post(photo, pick["headline"], pick.get("highlight"), workdir / f"post-{stamp}.jpg")
        else:
            media = reel.build_reel(photo, pick, workdir, workdir / f"reel-{stamp}.mp4")
            cover = reel.extract_cover(media, workdir / f"reel-{stamp}.jpg")
        print(f"[main] {kind}: {pick['headline']} -> {media}")
        built.append((kind, pick, story, media, caption, cover))

    if not dry_run and poster is None:
        poster = __import__("poster").get_poster()
    for kind, pick, story, media, caption, cover in built:
        if dry_run:
            continue
        try:
            code = poster.post_image(media, caption) if kind == "post" else poster.post_reel(media, caption, cover)
            print(f"[main] uploaded {kind}: {code}")
            state["posted"].append(story["key"])
        except Exception as e:
            print(f"[main] upload of {kind} failed: {e}")

    state["runs"] = state.get("runs", 0) + 1
    state["last_run"] = stamp
    save_state(state)
    return [b[3] for b in built]


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
