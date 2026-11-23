"""Turns a written post + its images into editor blocks (pasted into Naver's SmartEditor) and a preview page."""
import html
import re

import seo


def inline(text):
    """Plain text with **bold** -> safe HTML."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(str(text)))


HEADING_STYLE = "font-size:24px;font-weight:bold;"


def heading_html(text):
    """Every heading the same: big and bold (pasted on its own so it never picks up the text around it)."""
    plain = re.sub(r"\*\*(.+?)\*\*", r"\1", str(text))
    return f'<p><span style="{HEADING_STYLE}"><b>{html.escape(plain)}</b></span></p>'


BODY_STYLE = "font-size:16px;font-weight:normal;"


def para_html(text):
    # an explicit normal style, so body text never takes on the big bold of the heading above it
    return f'<p><span style="{BODY_STYLE}">{inline(text)}</span></p>'


GAP = "<p><br></p>"


def caption_html(text):
    return f'<p><span style="color:#888888;font-size:13px;">▲ {inline(text)}</span></p>'


class Builder:
    """Collects text pieces and images in reading order; neighbouring text becomes one paste."""

    def __init__(self):
        self.blocks = []

    def text(self, html_part, plain, alone=False):
        if self.blocks and self.blocks[-1]["type"] == "text" and not alone and not self.blocks[-1].get("alone"):
            self.blocks[-1]["html"] += html_part
            self.blocks[-1]["text"] += "\n" + plain
        else:
            self.blocks.append({"type": "text", "html": html_part, "text": plain, "alone": alone})

    def heading(self, text):
        self.text(heading_html(text), seo.clean(text), alone=True)

    def image(self, item):
        self.blocks.append({"type": "image", "path": str(item["path"]), "caption": item.get("caption", "")})
        if item.get("caption"):
            self.text(caption_html(item["caption"]), "▲ " + seo.clean(item["caption"]))

    def paragraphs(self, items):
        for p in items:
            self.text(para_html(p) + GAP, seo.clean(p) + "\n")

    def bullets(self, items, mark="✔"):
        for b in items:
            self.text(para_html(f"{mark} {b}"), f"{mark} {seo.clean(b)}")
        if items:
            self.text(GAP, "")


def blocks(post, images):
    """-> [{"type": "text", "html", "text"} | {"type": "image", "path", "caption"}] in reading order."""
    by_place = {}
    for item in images:
        place = item["place"]
        by_place[tuple(place) if isinstance(place, list) else place] = item
    b = Builder()
    if "top" in by_place:
        b.image(by_place["top"])
    b.paragraphs(post.get("intro", []))
    for i, sec in enumerate(post.get("sections", [])):
        b.heading(sec["heading"])
        if ("section", i) in by_place:
            b.image(by_place[("section", i)])
        b.paragraphs(sec.get("paragraphs", []))
        b.bullets(sec.get("bullets", []), "•")
    if post.get("summary") or "summary" in by_place:
        b.heading("한눈에 정리")
        if "summary" in by_place:
            b.image(by_place["summary"])
        b.bullets(post.get("summary", []))
    b.paragraphs(post.get("outro", []))
    return b.blocks


PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --fg:#222; --sub:#777; --bg:#fff; --card:#f6f7f9; --ok:#03c75a; --warn:#e5a000; }}
@media (prefers-color-scheme: dark) {{ :root {{ --fg:#e8e8e8; --sub:#999; --bg:#16181c; --card:#22252b; }} }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.8 "Malgun Gothic","Apple SD Gothic Neo",sans-serif; }}
main {{ max-width:760px; margin:0 auto; padding:24px 16px 80px; }}
h1 {{ font-size:28px; line-height:1.4; margin:8px 0 24px; }}
img {{ max-width:100%; border-radius:8px; display:block; margin:16px auto; }}
.meta {{ background:var(--card); border-radius:12px; padding:16px 20px; margin-bottom:28px; font-size:14px; }}
.meta b {{ color:var(--ok); }} .tags span {{ display:inline-block; margin:2px 6px 2px 0; color:var(--sub); }}
.ok {{ color:var(--ok); }} .warn {{ color:var(--warn); }}
</style></head><body><main>
<div class="meta">
<div>SEO 점수 <b>{score}/100</b> · 메인 키워드 <b>{keyword}</b> · {chars}</div>
<div>{checks}</div>
<div>연관검색어: {related}</div>
<div class="tags">{tags}</div>
</div>
<h1>{title}</h1>
{body}
</main></body></html>"""


def preview(post, images, result, keyword, related, dest):
    """A preview page (open it in any browser) with the post as it will look and the SEO checklist."""
    body = []
    for block in blocks(post, images):
        if block["type"] == "image":
            body.append(f'<img src="{html.escape(_name(block["path"]))}" alt="{html.escape(keyword)}">')
        else:
            body.append(block["html"])
    checks = "<br>".join(f'<span class="{"ok" if c["ok"] else "warn"}">{"✅" if c["ok"] else "⚠️"}</span> '
                         f'{html.escape(c["name"])}: {html.escape(str(c["detail"]))}' for c in result["checks"])
    page = PAGE.format(
        title=html.escape(post["title"]), score=result["score"], keyword=html.escape(keyword),
        chars=f"공백 제외 {result['stats']['chars']:,}자 / 포함 {result['stats']['chars_with_spaces']:,}자",
        checks=checks, related=html.escape(", ".join(related[:14]) or "-"),
        tags="".join(f"<span>#{html.escape(t)}</span>" for t in post.get("tags", [])), body="\n".join(body))
    dest.write_text(page, encoding="utf-8")
    return dest


def _name(path):
    return str(path).replace("\\", "/").rsplit("/", 1)[-1]
