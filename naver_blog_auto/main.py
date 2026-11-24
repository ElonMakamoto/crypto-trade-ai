"""One round for one account: keyword -> related searches -> research -> post -> SEO gate -> images -> Naver.

Command line (for testing):
    python main.py --account a --dry-run            # write the post + images + preview, don't post
    python main.py --account a --keyword "청년도약계좌 조건"
    python main.py --account a --ranks              # check where earlier posts show in Naver search
"""
import argparse
import json
import time
from datetime import datetime

import config
import images
import keywords
import naver
import render
import writer


def make_story_post(aid, account, keyword=None):
    """연애 categories: a news-story post in the reference style."""
    import story

    result = story.generate(aid, account, keyword)
    keyword, post = result["keyword"], result["post"]
    out_dir = config.output_dir(aid) / f"{datetime.now():%Y%m%d-%H%M}_{images.slug(keyword)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pics = images.make_story(post, keyword, account, out_dir, result["sources"], seed=f"{aid}{time.time()}")
    related = None  # no [함께보면 좋은 글] link at the end
    photo_outlets = list(dict.fromkeys(p["caption"].split("출처: ", 1)[1] for p in pics if "출처: " in p["caption"]))
    blocks = render.story_blocks(post, pics, related, photo_outlets or post.get("sources_used") or result["outlets"][:3],
                                 love=config.is_love(account.get("TOPIC")))
    final = result["seo"]
    final["checks"].append({"ok": 8 <= len(pics) <= 10, "weight": 0, "name": "사진 8~10장", "detail": f"{len(pics)}장",
                            "fix": ""})
    page = render.preview(post, pics, final, keyword, result["outlets"], out_dir / "미리보기.html", blocks)
    job = {"aid": aid, "keyword": keyword, "post": post, "seo": final, "related": result["related"], "must": [],
           "notes": result["notes"], "sources": result["sources"], "related_post": related,
           "images": [{"path": str(p["path"]), "caption": p["caption"], "place": p["place"]} for p in pics],
           "blocks": blocks, "preview": str(page), "dir": str(out_dir), "topic": account["TOPIC"]}
    (out_dir / "post.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📝 '{post['title']}' — 형식 점수 {final['score']}점, 공백 제외 {final['stats']['chars']:,}자, 사진 {len(pics)}장")
    print(f"   미리보기: {page}")
    return job


def make_post(aid, keyword=None):
    """Write the post and its images (nothing is uploaded). Returns the job dict saved as post.json."""
    account = config.load_account(aid)
    if config.is_love(account.get("TOPIC")) or account.get("FORMAT", "story") == "story":
        return make_story_post(aid, account, keyword)
    result = writer.generate(aid, account, keyword)
    keyword, post = result["keyword"], result["post"]
    out_dir = config.output_dir(aid) / f"{datetime.now():%Y%m%d-%H%M}_{images.slug(keyword)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pics = images.make(post, keyword, account, out_dir, seed=f"{aid}{time.time()}")
    blocks = render.blocks(post, pics)
    from seo import analyze

    final = analyze(post, keyword, result["must"], account.get("LENGTH", config.AUTO), n_images=len(pics))
    page = render.preview(post, pics, final, keyword, result["related"]["ranked"], out_dir / "미리보기.html")
    job = {"aid": aid, "keyword": keyword, "post": post, "seo": final, "related": result["related"],
           "must": result["must"], "notes": result["notes"],
           "images": [{"path": str(p["path"]), "caption": p["caption"], "place": p["place"]} for p in pics],
           "blocks": blocks, "preview": str(page), "dir": str(out_dir), "topic": account.get("TOPIC")}
    (out_dir / "post.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📝 '{post['title']}' — SEO {final['score']}점, 공백 제외 {final['stats']['chars']:,}자, 이미지 {len(pics)}장")
    print(f"   미리보기: {page}")
    return job


def publish_job(job):
    """Upload a prepared post to the account's Naver blog and record it."""
    aid = job["aid"]
    account = config.load_account(aid)
    publish = account.get("PUBLISH", "publish") == "publish"
    from pathlib import Path

    # the Naver category set for this app category (⚙ 카테고리 연결), else the account's, else the AI's pick
    preferred = config.category_map().get(job.get("topic") or account.get("TOPIC"), "") or account.get("CATEGORY", "")

    def pick(names):
        return writer.pick_category(names, job["post"], job["keyword"], preferred)

    result = naver.post(aid, job["post"]["title"], job["blocks"], job["post"]["tags"], publish=publish,
                        shot_dir=Path(job["dir"]), pick_category=pick)
    config.add_history(aid, {
        "keyword": job["keyword"], "title": job["post"]["title"], "url": result["url"], "log_no": result["log_no"],
        "draft": result["draft"], "blog_id": result["blog_id"], "score": job["seo"]["score"], "chars": job["seo"]["stats"]["chars"],
        "images": result["images"], "json": str(Path(job["dir"]) / "post.json"),
        "blog_rank": None, "main_page": None, "rank_checked": ""})
    if result["url"]:
        print(f"✅ 발행 완료: {result['url']}")
    return result


def run_round(aid, dry_run=False, keyword=None):
    job = make_post(aid, keyword)
    if dry_run:
        return job
    publish_job(job)
    return job


def check_ranks(aid, days=30, force=False):
    """Where this account's recent posts show in Naver search (blog tab rank, main search page).
    Checked at most once every 12 hours per post unless force=True."""
    items = config.load_history(aid)
    blog_id = config.load_account(aid).get("BLOG_ID")
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    recent = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 12 * 3600))
    changed = 0
    for item in items:
        if item.get("draft") or not item.get("url") or item.get("time", "") < cutoff:
            continue
        if not force and item.get("rank_checked", "") > recent:
            continue
        rank = keywords.naver_rank(item["keyword"], item.get("blog_id") or blog_id, item.get("log_no"))
        if rank["blog_rank"] is None:
            continue  # Naver not reachable now
        item.update(rank, rank_checked=time.strftime("%Y-%m-%d %H:%M"))
        changed += 1
        where = f"블로그탭 {rank['blog_rank']}위" if rank["blog_rank"] else "블로그탭 1페이지 밖"
        print(f"📈 {item['keyword']}: {where}{' · 통합검색 노출' if rank['main_page'] else ''}")
        time.sleep(2)
    if changed:
        config.save_history(aid, items)
    return items


def main():
    parser = argparse.ArgumentParser(description="Naver Blog Auto (command line)")
    parser.add_argument("--account", default="a", choices=list(config.ACCOUNTS))
    parser.add_argument("--keyword")
    parser.add_argument("--dry-run", action="store_true", help="write only, don't post")
    parser.add_argument("--login", action="store_true", help="open the browser to log in to Naver")
    parser.add_argument("--ranks", action="store_true", help="check search ranks of recent posts")
    parser.add_argument("--topic", help="category for this run, e.g. love_show (see config.CHOICES['TOPIC'])")
    args = parser.parse_args()
    if args.login:
        print(naver.login(args.account))
    elif args.ranks:
        check_ranks(args.account, force=True)
    else:
        if args.topic:
            config.save_account(args.account, {"TOPIC": args.topic})
        run_round(args.account, dry_run=args.dry_run, keyword=args.keyword)


if __name__ == "__main__":
    main()
