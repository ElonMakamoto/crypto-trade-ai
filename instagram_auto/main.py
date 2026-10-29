"""Trending news -> Pubity-style post + reel -> Instagram, every few hours.

    python main.py              # run once (post now)
    python main.py --dry-run    # make the images/video but don't upload
    python main.py --loop       # keep running, one round every INTERVAL_HOURS
"""
import argparse
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone

import ai
import config
import news
import reel
import render

SITE_DIR = config.BASE_DIR.parent / "public" / "instagram"
SITE_MEDIA = SITE_DIR / "media"
SITE_FEED = SITE_DIR / "feed.json"
SITE_KEEP = 30


def load_state():
    if config.STATE_FILE.exists():
        return json.loads(config.STATE_FILE.read_text())
    return {"posted": [], "runs": 0}


def save_state(state):
    config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["posted"] = state["posted"][-500:]
    config.STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def build_caption(pick, story):
    tags = " ".join("#" + t.lstrip("#").replace(" ", "") for t in pick.get("hashtags", []))
    source = f"\n\n📰 Source: {story['source']}" if story.get("source") else ""
    return f"{pick['caption']}{source}\n\n{tags}".strip()[:2200]


def prepare(picks, stories, workdir, needed):
    """Attach a downloaded photo to each pick; skip stories without a usable image."""
    by_id = {s["id"]: s for s in stories}
    ready = []
    for pick in picks:
        story = by_id[pick["id"]]
        url = news.find_image_url(story, pick.get("image_query", ""))
        if not url:
            print(f"[main] no image for: {story['title']}")
            continue
        try:
            photo = news.download_image(url, workdir / f"photo_{len(ready)}.img")
            render.load_photo(photo, (64, 64))  # validate it opens
        except Exception as e:  # bad download or unreadable image
            print(f"[main] image failed for {story['title']}: {e}")
            continue
        ready.append((pick, story, photo))
        if len(ready) == needed:
            break
    return ready


def publish_to_site(entries):
    """Copy media into public/instagram and update feed.json (Cloudflare redeploys on push)."""
    SITE_MEDIA.mkdir(parents=True, exist_ok=True)
    feed = json.loads(SITE_FEED.read_text()) if SITE_FEED.exists() else {"items": []}
    for e in entries:
        shutil.copy(e.pop("file"), SITE_MEDIA / e["media"])
        if e.get("cover_file"):
            shutil.copy(e.pop("cover_file"), SITE_MEDIA / e["cover"])
    feed["items"] = (entries + feed["items"])[:SITE_KEEP]
    feed["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    feed["interval_hours"] = config.INTERVAL_HOURS
    SITE_FEED.write_text(json.dumps(feed, indent=2, ensure_ascii=False))
    keep = {i["media"] for i in feed["items"]} | {i.get("cover") for i in feed["items"]}
    for f in SITE_MEDIA.iterdir():
        if f.name not in keep and not f.name.startswith("."):
            f.unlink()


def run_once(dry_run=False, site=True):
    state = load_state()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    workdir = config.OUTPUT_DIR / stamp
    workdir.mkdir(parents=True, exist_ok=True)

    kinds = {"both": ["post", "reel"], "post": ["post"], "reel": ["reel"]}[config.POST_MODE]
    stories = news.fetch_trending()
    if not stories:
        print("[main] no news fetched — skipping this round")
        return
    picks = ai.pick_and_write(stories, len(kinds) + 3, set(state["posted"]))
    ready = prepare(picks, stories, workdir, len(kinds))
    if not ready:
        print("[main] nothing postable this round")
        return

    built = []
    for kind, (pick, story, photo) in zip(kinds, ready):
        caption = build_caption(pick, story)
        (workdir / f"{kind}_caption.txt").write_text(caption)
        cover = render.feed_post(photo, pick["headline"], pick.get("highlight"), workdir / f"{kind}-{stamp}.jpg")
        media = cover if kind == "post" else reel.build_reel(photo, pick, workdir, workdir / f"reel-{stamp}.mp4")
        print(f"[main] {kind}: {pick['headline']} -> {media}")
        built.append((kind, pick, story, media, caption, cover))

    if site:
        entries = []
        for kind, pick, story, media, _, cover in built:
            entry = {"type": kind, "headline": pick["headline"], "highlight": pick.get("highlight"),
                     "caption": pick["caption"], "source": story.get("source"), "link": story.get("link"),
                     "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "media": media.name, "file": media}
            if kind == "reel":
                entry.update(cover=cover.name, cover_file=cover)
            entries.append(entry)
        publish_to_site(entries)
        # e.g. git commit + push, so the Graph API can fetch images from the live site
        if config.SITE_PUBLISH_HOOK and not dry_run:
            subprocess.run(config.SITE_PUBLISH_HOOK, shell=True, check=False)

    poster = None if dry_run else __import__("poster").get_poster()
    for kind, pick, story, media, caption, cover in built:
        if poster:
            try:
                code = poster.post_image(media, caption) if kind == "post" else poster.post_reel(media, caption, cover)
                print(f"[main] uploaded {kind}: {code}")
            except Exception as e:
                print(f"[main] upload of {kind} failed: {e}")
                continue
        state["posted"].append(story["key"])

    state["runs"] = state.get("runs", 0) + 1
    state["last_run"] = stamp
    save_state(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="create media but don't upload")
    parser.add_argument("--loop", action="store_true", help=f"repeat every INTERVAL_HOURS ({config.INTERVAL_HOURS}h)")
    parser.add_argument("--no-site", action="store_true", help="don't update public/instagram")
    args = parser.parse_args()
    while True:
        try:
            run_once(dry_run=args.dry_run, site=not args.no_site)
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
