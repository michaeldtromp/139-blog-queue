#!/usr/bin/env python3
"""139 Design Studio - daily blog automation for https://139aruba.com/news/

Flow (one run = one post):
  1. Work out today's date in Aruba (UTC-4, no daylight saving).
  2. Find today's row in blog_topic_queue.md, skipping rows marked PUBLISHED.
  3. Check WordPress for a post that already exists for that topic.
  4. Ask Claude (with web search) to write the post in the 139aruba house style
     and return it as structured JSON.
  5. Pick images (Pexels when PEXELS_API_KEY is set, otherwise reuse the newest
     featured image in the same category) and upload them to WordPress.
  6. Build the Elementor layout from elementor_template.json and publish through
     the WordPress REST API with an Application Password.
  7. Write the AIOSEO fields and regenerate the Elementor CSS.
  8. Move the row from the active queue to the "Published" section and push.

Environment:
  ANTHROPIC_API_KEY   required unless --stub is used
  WP_APP_PASSWORD     required unless --dry-run or --check
  WP_USER             default Mic139
  WP_URL              default https://139aruba.com
  CLAUDE_MODEL        default claude-sonnet-5
  PEXELS_API_KEY      optional, enables fresh photography
  BLOG_POST_STATUS    default publish (use draft to review before going live)

Usage:
  python blog_automation.py                 # normal daily run
  python blog_automation.py --check         # only parse the queue, no network
  python blog_automation.py --dry-run       # generate, build payload, publish nothing
  python blog_automation.py --date 2026-09-10 --stub stub.json --dry-run
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
QUEUE_FILE = ROOT / "blog_topic_queue.md"
STYLE_FILE = ROOT / "blog_139aruba.md"
LOCAL_FILE = ROOT / "aruba_local_context.md"
TEMPLATE_FILE = ROOT / "elementor_template.json"
OUT_DIR = ROOT / "out"

SITE = os.environ.get("WP_URL", "https://139aruba.com").rstrip("/")
WP_USER = os.environ.get("WP_USER", "Mic139")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")
POST_STATUS = os.environ.get("BLOG_POST_STATUS", "publish")

ARUBA_TZ = dt.timezone(dt.timedelta(hours=-4), name="AST")
NEWS_TAG_ID = 5
AUTHOR_ID = 2
HTTP_TIMEOUT = 60

CATEGORIES = {
    15: ("Web development", "web-development"),
    30: ("AI", "ai"),
    18: ("Graphic design", "graphic-design"),
    10: ("E-commerce", "e-commerce"),
    7: ("Branding", "branding"),
    25: ("Amazon", "amazon"),
    24: ("Event", "event"),
    13: ("Summit", "summit"),
}

ROW_RE = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$")
LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(.+?)\s+[—–-]+\s+(.+?)\s*$")


def log(msg: str) -> None:
    print(f"[blog] {msg}", flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"[blog] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

def parse_queue(text: str) -> list[dict]:
    rows = []
    for n, line in enumerate(text.splitlines()):
        m = ROW_RE.match(line) or LINE_RE.match(line)
        if not m:
            continue
        date, title, cat_text = m.group(1), m.group(2).strip(), m.group(3).strip()
        if title.lower() in ("topic", "title") or set(title) <= {"-", ":", " "}:
            continue
        published = "PUBLISHED" in cat_text.upper()
        before_mark = re.split(r"PUBLISHED", cat_text, flags=re.I)[0]
        ids = [int(x) for x in re.findall(r"\b(\d{1,3})\b", before_mark) if int(x) in CATEGORIES]
        rows.append({
            "line_no": n,
            "line": line,
            "date": date,
            "title": title,
            "category_text": cat_text,
            "category_ids": ids,
            "published": published,
        })
    return rows


def find_topic(rows: list[dict], date: str) -> dict | None:
    for row in rows:
        if row["date"] == date and not row["published"]:
            return row
    return None


def remove_from_queue(text: str, row: dict, post_id: int, link: str) -> str:
    """Drop the row from the active table and record it under '## Published'."""
    lines = text.splitlines()
    assert lines[row["line_no"]] == row["line"], "queue changed on disk since it was read"
    del lines[row["line_no"]]
    entry = f"- {row['date']} — {row['title']} — post {post_id} — {link}"
    for i, line in enumerate(lines):
        if line.strip().lower() == "## published":
            j = i + 1
            while j < len(lines) and (lines[j].startswith("- ") or not lines[j].strip()):
                j += 1
            while j > i + 1 and not lines[j - 1].strip():
                j -= 1
            lines.insert(j, entry)
            break
    else:
        lines += ["", "## Published", entry]
    return "\n".join(lines).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# WordPress REST helpers
# ---------------------------------------------------------------------------

class WP:
    def __init__(self, site: str, user: str, password: str):
        self.site = site
        self.auth = (user, password) if password else None
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "139-blog-automation/2.0"

    def _req(self, method: str, path: str, auth: bool = True, **kw) -> requests.Response:
        url = f"{self.site}/wp-json{path}"
        if auth:
            if not self.auth:
                die("WP_APP_PASSWORD is not set and this step needs authentication")
            kw.setdefault("auth", self.auth)
        kw.setdefault("timeout", HTTP_TIMEOUT)
        r = self.s.request(method, url, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:800]}")
        return r

    def get(self, path: str, auth: bool = False, **params):
        return self._req("GET", path, auth=auth, params=params).json()

    def post_json(self, path: str, payload: dict):
        return self._req("POST", path, json=payload).json()

    def upload_media(self, filename: str, data: bytes, mime: str, alt: str, title: str, caption: str = "") -> dict:
        headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": mime,
        }
        media = self._req("POST", "/wp/v2/media", data=data, headers=headers).json()
        self.post_json(f"/wp/v2/media/{media['id']}", {"alt_text": alt, "title": title, "caption": caption})
        return media

    def run_ability(self, name: str, inputs: dict):
        return self.post_json(f"/wp-abilities/v1/abilities/{name}/run", {"input": inputs})

    def execute_php(self, code: str):
        out = self.run_ability("novamira/execute-php", {"code": code})
        if not out.get("success", True):
            raise RuntimeError(f"execute-php failed: {json.dumps(out)[:600]}")
        return out


def existing_post_for(wp: WP, title: str, date: str) -> dict | None:
    """Return a post that already covers this topic (any status), if there is one."""
    key = re.sub(r"[^a-z0-9 ]", "", title.lower()).split()[:4]
    needle = " ".join(key)
    for status in ("publish", "future", "draft", "pending", "private"):
        try:
            posts = wp.get("/wp/v2/posts", auth=(status != "publish"), search=needle, status=status,
                           per_page=5, _fields="id,title,status,link,date")
        except Exception as e:  # noqa: BLE001
            log(f"search for existing {status} posts failed: {e}")
            continue
        for p in posts:
            t = re.sub(r"[^a-z0-9 ]", "", p["title"]["rendered"].lower())
            if all(k in t for k in key) or p["date"][:10] == date:
                return p
    return None


def recent_posts(wp: WP, n: int = 15) -> list[dict]:
    posts = wp.get("/wp/v2/posts", per_page=n, _fields="id,title,link,date,categories,excerpt")
    return [{
        "id": p["id"],
        "title": re.sub(r"<[^>]+>", "", p["title"]["rendered"]),
        "link": p["link"],
        "date": p["date"][:10],
        "categories": p["categories"],
    } for p in posts]


def fallback_hero(wp: WP, category_ids: list[int]) -> dict | None:
    for cid in category_ids or list(CATEGORIES):
        posts = wp.get("/wp/v2/posts", categories=cid, per_page=3, _fields="id,featured_media,title")
        for p in posts:
            if p.get("featured_media"):
                m = wp.get(f"/wp/v2/media/{p['featured_media']}", _fields="id,source_url,alt_text,media_details")
                return {"id": m["id"], "url": m["source_url"], "alt": m.get("alt_text") or "", "reused": True}
    return None


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

IMAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "search_query": {"type": "string", "description": "3 to 6 words for a stock photo search: real people at work in real spaces, candid, natural light, no screens facing the camera."},
        "alt": {"type": "string", "description": "Descriptive alt text; the hero alt must contain the focus keyphrase."},
    },
    "required": ["search_query", "alt"],
    "additionalProperties": False,
}

POST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Post title, sentence case, under 80 characters."},
        "slug": {"type": "string", "description": "URL slug, lowercase words joined by hyphens, keyphrase first."},
        "excerpt": {"type": "string", "description": "One or two sentences, at most 200 characters."},
        "intro_html": {"type": "string", "description": "Exactly one <p>: a punchy hook plus one hard, sourced statistic."},
        "body_html": {"type": "string", "description": "The article body: <h2> sections in sentence case, <ul><li><strong>lead-in.</strong> sentence</li></ul> lists, paragraphs. Must contain the markers {{IMAGE_1}} and {{IMAGE_2}}, each on its own line immediately before an <h2>. Ends with an Aruba angle section, a checklist section and a bottom-line paragraph."},
        "cta_heading": {"type": "string", "description": "Closing call-to-action heading phrased as a question."},
        "cta_html": {"type": "string", "description": "One <p> linking to https://139aruba.com/contact/ followed by <p><em>Sources: ...</em></p> with real, linked sources."},
        "seo": {
            "type": "object",
            "properties": {
                "focus_keyphrase": {"type": "string"},
                "seo_title": {"type": "string", "description": "Under 60 characters, keyphrase at the start."},
                "meta_description": {"type": "string", "description": "140 to 155 characters, contains the keyphrase."},
                "additional_keyphrases": {"type": "array", "items": {"type": "string"}},
                "og_title": {"type": "string"},
                "og_description": {"type": "string"},
                "twitter_title": {"type": "string"},
                "twitter_description": {"type": "string"},
            },
            "required": ["focus_keyphrase", "seo_title", "meta_description", "additional_keyphrases",
                         "og_title", "og_description", "twitter_title", "twitter_description"],
            "additionalProperties": False,
        },
        "images": {
            "type": "object",
            "properties": {"hero": IMAGE_SCHEMA, "body_1": IMAGE_SCHEMA, "body_2": IMAGE_SCHEMA},
            "required": ["hero", "body_1", "body_2"],
            "additionalProperties": False,
        },
    },
    "required": ["title", "slug", "excerpt", "intro_html", "body_html", "cta_heading", "cta_html", "seo", "images"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You write the daily post for the 139 Design Studio news blog at https://139aruba.com/news/.
139 Design Studio is a web design, graphic design and e-commerce studio in Aruba run by Michael. The reader is a small business owner, mostly in Aruba, sometimes abroad.

Follow the house style below exactly. Research first with web search, write second: every statistic, date, price and link must come from a real page you actually found, and the Sources line must link to those pages. If you cannot verify a number, leave it out.

Hard rules:
- Aruba sits below the hurricane belt. Never write hurricane, storm-season or disaster-prep content.
- Aruba is UTC-4 with no daylight saving. Languages in daily use: English, Spanish, Dutch and Papiamento (spell it exactly so).
- For trade shows, expos and summits the reader is a VISITOR who attends to buy, compare and learn. Never write the reader as an exhibitor, booth-holder, sponsor or stand designer. Verify dates, venue, prices and registration links on the organiser's own site at write time.
- Amazon posts are educational (how to sell on Amazon). Never mention Tromp Wholesale.
- Never use the words "crafting" or "the Americas". Do not claim Dutch, Portuguese or Italian language service.
- H2 headings in sentence case. Bulleted lists use <strong>lead-ins</strong> followed by one or two explanatory sentences.
- Use single-quoted HTML attributes (href='...') and no inline styles.
- 800 to 1,100 words across intro, body and CTA. Close with an Aruba/local angle, a practical checklist and a CTA to https://139aruba.com/contact/.
- Link to one older 139aruba.com post from the list provided when it is genuinely relevant.
- The focus keyphrase must appear in the title, the slug, the first paragraph, at least one H2, the hero alt text and at least four times in the body.
"""


def load_context() -> str:
    parts = []
    for f in (STYLE_FILE, LOCAL_FILE):
        if f.exists():
            parts.append(f"===== {f.name} =====\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def generate_post(topic: dict, today: str, recent: list[dict]) -> dict:
    import anthropic  # imported here so --check and --stub work without the package

    if not os.environ.get("ANTHROPIC_API_KEY"):
        die("ANTHROPIC_API_KEY is not set")

    cat_names = [CATEGORIES[c][0] for c in topic["category_ids"]] or ["Web development"]
    recent_lines = "\n".join(f"- {p['date']} {p['title']} -> {p['link']}" for p in recent)
    user_prompt = f"""Today is {today} (Aruba).

Topic for today's post: {topic['title']}
Category: {', '.join(cat_names)}

Older posts on the blog you may link to when relevant:
{recent_lines}

Reference material (house style and local context):
{load_context()}

Write today's post now. Use web search to verify every figure and source before you cite it. Return only the JSON object described by the output schema."""

    client = anthropic.Anthropic()
    web_search = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}
    messages = [{"role": "user", "content": user_prompt}]

    for attempt in range(6):
        with client.messages.stream(
            model=MODEL,
            max_tokens=32000,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[web_search],
            thinking={"type": "adaptive"},
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": POST_SCHEMA}},
        ) as stream:
            msg = stream.get_final_message()
        if msg.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": msg.content})
            log(f"pause_turn, resuming ({attempt + 1})")
            continue
        if msg.stop_reason == "refusal":
            die(f"Claude refused: {getattr(msg, 'stop_details', None)}")
        if msg.stop_reason == "max_tokens":
            die("Claude hit max_tokens before finishing the post")
        text = "".join(b.text for b in msg.content if b.type == "text")
        log(f"generation used {msg.usage.input_tokens} in / {msg.usage.output_tokens} out tokens")
        return json.loads(text)
    die("Claude did not finish after repeated pause_turn")


def validate_post(post: dict) -> None:
    body = post["body_html"]
    for marker in ("{{IMAGE_1}}", "{{IMAGE_2}}"):
        if marker not in body:
            log(f"warning: {marker} missing from body_html; image will be placed before an <h2>")
    words = len(re.sub(r"<[^>]+>", " ", post["intro_html"] + body + post["cta_html"]).split())
    log(f"word count {words}")
    if words < 650 or words > 1400:
        log("warning: word count is outside the 800-1,100 house range")
    if "139aruba.com/contact" not in post["cta_html"]:
        log("warning: CTA does not link to /contact/")


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

def pexels_photo(query: str) -> dict | None:
    if not PEXELS_KEY:
        return None
    r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": PEXELS_KEY},
                     params={"query": query, "orientation": "landscape", "size": "large", "per_page": 5},
                     timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        log(f"Pexels search failed ({r.status_code}) for '{query}'")
        return None
    photos = r.json().get("photos") or []
    return photos[0] if photos else None


def fetch_pexels_bytes(photo: dict, w: int, h: int) -> bytes:
    url = f"{photo['src']['original']}?auto=compress&cs=tinysrgb&fit=crop&w={w}&h={h}"
    r = requests.get(url, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.content


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def prepare_images(wp: WP, post: dict, topic: dict, dry_run: bool) -> dict:
    """Return {'hero': {...}, 'body': [{...}, ...]} with WordPress media ids and URLs."""
    result = {"hero": None, "body": []}
    used_ids: set[int] = set()
    specs = [("hero", 1200, 900), ("body_1", 1200, 675), ("body_2", 1200, 675)]
    for key, w, h in specs:
        spec = post["images"][key]
        photo = pexels_photo(spec["search_query"])
        if photo and photo["id"] in used_ids:
            photo = None
        if photo:
            used_ids.add(photo["id"])
            filename = f"{slugify(spec['alt'])[:60] or key}-139-Design-Studio.jpg"
            credit = f"Photo by {photo.get('photographer', 'Pexels photographer')} on Pexels"
            if dry_run:
                media = {"id": 0, "source_url": photo["src"]["large2x"]}
                log(f"[dry-run] would upload {filename} ({credit})")
            else:
                data = fetch_pexels_bytes(photo, w, h)
                media = wp.upload_media(filename, data, "image/jpeg", spec["alt"], spec["alt"], credit)
                log(f"uploaded {filename} as media {media['id']}")
            entry = {"id": media["id"], "url": media["source_url"], "alt": spec["alt"], "reused": False}
        elif key == "hero":
            entry = fallback_hero(wp, topic["category_ids"])
            if not entry:
                die("no hero image available: set PEXELS_API_KEY or add a featured image to a post in this category")
            entry["alt"] = spec["alt"] or entry["alt"]
            log(f"hero: reusing media {entry['id']} from an earlier post in the same category")
        else:
            entry = None
        if key == "hero":
            result["hero"] = entry
        elif entry:
            result["body"].append(entry)
    return result


def figure_html(img: dict) -> str:
    return ("<figure style='margin:10px 0 30px 0'><img src='" + img["url"] + "' alt='" +
            img["alt"].replace("'", "&#39;") + "' style='width:100%;height:auto;display:block' /></figure>")


def place_body_images(body_html: str, images: list[dict]) -> str:
    for i, marker in enumerate(("{{IMAGE_1}}", "{{IMAGE_2}}")):
        replacement = figure_html(images[i]) if i < len(images) else ""
        if marker in body_html:
            body_html = body_html.replace(marker, replacement)
        elif replacement:
            # no marker: insert before the (i+2)th <h2>
            h2s = [m.start() for m in re.finditer(r"<h2", body_html)]
            idx = h2s[min(i + 1, len(h2s) - 1)] if h2s else len(body_html)
            body_html = body_html[:idx] + replacement + "\n" + body_html[idx:]
    return re.sub(r"\n{3,}", "\n\n", body_html).strip()


# ---------------------------------------------------------------------------
# Elementor
# ---------------------------------------------------------------------------

def ordinal(n: int) -> str:
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def build_elementor(post: dict, images: dict, category_ids: list[int], body_html: str, when: dt.datetime) -> list:
    if not TEMPLATE_FILE.exists():
        die(f"{TEMPLATE_FILE.name} is missing")
    template = json.loads(TEMPLATE_FILE.read_text(encoding="utf-8"))
    cid = category_ids[0] if category_ids else 15
    cat_name, cat_slug = CATEGORIES[cid]
    posted = (f"<p>Posted {when.strftime('%B')} {ordinal(when.day)}, {when.year} under "
              f"<a href='{SITE}/category/{cat_slug}/'>{cat_name}</a></p>")
    values = {
        "{{TITLE}}": post["title"],
        "{{POSTED_LINE}}": posted,
        "{{INTRO_HTML}}": post["intro_html"].strip(),
        "{{BODY_HTML}}": body_html,
        "{{CTA_TITLE}}": post["cta_heading"],
        "{{CTA_HTML}}": post["cta_html"].strip(),
    }
    hero = images["hero"]

    def walk(node):
        if isinstance(node, dict):
            if "elType" in node:
                node["id"] = secrets.token_hex(4)
            for k, v in list(node.items()):
                if isinstance(v, str) and v in values:
                    node[k] = values[v]
                elif isinstance(v, dict) and v.get("url") == "{{HERO_URL}}":
                    node[k] = {"id": hero["id"], "url": hero["url"], "alt": hero["alt"], "source": "library", "size": ""}
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(template)
    return template


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

def seo_php(post_id: int, seo: dict) -> str:
    payload = json.dumps({
        "title": seo["seo_title"],
        "description": seo["meta_description"],
        "focus": seo["focus_keyphrase"],
        "additional": seo.get("additional_keyphrases", [])[:4],
        "og_title": seo["og_title"],
        "og_description": seo["og_description"],
        "twitter_title": seo["twitter_title"],
        "twitter_description": seo["twitter_description"],
    })
    return f"""
$id = {post_id}; $s = json_decode({json.dumps(payload)}, true); $out = [];
if (class_exists('\\\\AIOSEO\\\\Plugin\\\\Common\\\\Models\\\\Post')) {{
  $m = \\AIOSEO\\Plugin\\Common\\Models\\Post::getPost($id);
  $m->post_id = $id; $m->title = $s['title']; $m->description = $s['description'];
  $add = array_map(function($k){{ return ['keyphrase'=>$k,'score'=>0,'analysis'=>[]]; }}, $s['additional']);
  $m->keyphrases = json_encode(['focus'=>['keyphrase'=>$s['focus'],'score'=>0,'analysis'=>[]],'additional'=>$add]);
  $m->og_title = $s['og_title']; $m->og_description = $s['og_description'];
  $m->twitter_use_og = 0; $m->twitter_title = $s['twitter_title']; $m->twitter_description = $s['twitter_description'];
  $m->save(); $out['seo'] = 'saved';
}}
if (class_exists('\\\\Elementor\\\\Core\\\\Files\\\\CSS\\\\Post')) {{ $css = \\Elementor\\Core\\Files\\CSS\\Post::create($id); $css->update(); $out['css'] = 'regenerated'; }}
do_action('litespeed_purge_post', $id); do_action('litespeed_purge_url', home_url('/news/')); do_action('litespeed_purge_url', home_url('/'));
$out['status'] = get_post_status($id); return $out;
"""


def publish(wp: WP, post: dict, topic: dict, images: dict, when: dt.datetime, dry_run: bool) -> dict:
    body_html = place_body_images(post["body_html"], images["body"])
    elementor = build_elementor(post, images, topic["category_ids"], body_html, when)
    content = "\n".join([
        post["intro_html"].strip(),
        body_html,
        f"<h4>{post['cta_heading']}</h4>",
        post["cta_html"].strip(),
    ])
    payload = {
        "title": post["title"],
        "slug": post["slug"],
        "status": POST_STATUS,
        "date": when.strftime("%Y-%m-%dT%H:%M:%S"),
        "excerpt": post["excerpt"],
        "content": content,
        "author": AUTHOR_ID,
        "categories": topic["category_ids"] or [15],
        "tags": [NEWS_TAG_ID],
        "featured_media": images["hero"]["id"],
        "template": "elementor_header_footer",
        "meta": {
            "_elementor_edit_mode": "builder",
            "_elementor_template_type": "wp-post",
            "_elementor_data": json.dumps(elementor, ensure_ascii=False),
        },
    }
    OUT_DIR.mkdir(exist_ok=True)
    out_file = OUT_DIR / f"{topic['date']}-payload.json"
    out_file.write_text(json.dumps({"post": payload, "seo": post["seo"], "images": images}, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"payload written to {out_file.relative_to(ROOT)}")
    if dry_run:
        return {"id": 0, "link": f"{SITE}/{post['slug']}/", "status": "dry-run"}

    created = wp.post_json("/wp/v2/posts", payload)
    post_id, link = created["id"], created["link"]
    log(f"created post {post_id} ({created['status']}) {link}")
    try:
        out = wp.execute_php(seo_php(post_id, post["seo"]))
        log(f"post-publish step: {json.dumps(out.get('return_value', out))[:300]}")
    except Exception as e:  # noqa: BLE001
        log(f"warning: SEO/CSS step via execute-php failed ({e}); trying the AIOSEO ability")
        try:
            seo = post["seo"]
            wp.run_ability("aioseo-posts/seo-data-update", {
                "postId": post_id, "title": seo["seo_title"], "description": seo["meta_description"],
                "focus_keyphrase": seo["focus_keyphrase"], "additional_keyphrases": seo.get("additional_keyphrases", [])[:4],
                "social": {"og_title": seo["og_title"], "og_description": seo["og_description"],
                           "twitter_title": seo["twitter_title"], "twitter_description": seo["twitter_description"]},
            })
        except Exception as e2:  # noqa: BLE001
            log(f"warning: AIOSEO ability also failed ({e2}); SEO fields must be set by hand")
    return {"id": post_id, "link": link, "status": created["status"]}


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def commit_and_push(message: str) -> None:
    git("add", QUEUE_FILE.name)
    if not git("status", "--porcelain", "--", QUEUE_FILE.name):
        log("queue unchanged, nothing to commit")
        return
    name = os.environ.get("GIT_AUTHOR_NAME") or git("config", "--get", "user.name") or "139 blog automation"
    email = os.environ.get("GIT_AUTHOR_EMAIL") or git("config", "--get", "user.email") or "blog-automation@139aruba.com"
    git("-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-m", message)
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    git("pull", "--rebase", "origin", branch)
    git("push", "origin", branch)
    log(f"pushed queue update to origin/{branch}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Publish today's 139aruba.com blog post")
    ap.add_argument("--date", help="queue date to publish (YYYY-MM-DD); default today in Aruba")
    ap.add_argument("--check", action="store_true", help="only parse the queue and report")
    ap.add_argument("--dry-run", action="store_true", help="generate and build, but publish and push nothing")
    ap.add_argument("--stub", help="JSON file to use instead of calling Claude (testing)")
    ap.add_argument("--no-git", action="store_true", help="update the queue file but do not commit or push")
    args = ap.parse_args()

    now = dt.datetime.now(ARUBA_TZ)
    today = args.date or now.strftime("%Y-%m-%d")
    log(f"date {today} (Aruba now {now.strftime('%Y-%m-%d %H:%M')})")

    queue_text = QUEUE_FILE.read_text(encoding="utf-8")
    rows = parse_queue(queue_text)
    topic = find_topic(rows, today)
    if not topic:
        pending = [r for r in rows if not r["published"] and r["date"] >= today]
        nxt = f"next unpublished row is {pending[0]['date']}: {pending[0]['title']}" if pending else "the queue is empty"
        log(f"no unpublished topic for {today}; {nxt}. Nothing to do.")
        return
    log(f"topic: {topic['title']} | categories {topic['category_ids']}")
    if args.check:
        return

    wp = WP(SITE, WP_USER, WP_APP_PASSWORD)
    if not args.dry_run and not WP_APP_PASSWORD:
        die("WP_APP_PASSWORD is not set")

    if WP_APP_PASSWORD:
        existing = existing_post_for(wp, topic["title"], today)
        if existing:
            if existing["status"] == "publish":
                log(f"post {existing['id']} already published for this topic: {existing['link']}")
                QUEUE_FILE.write_text(remove_from_queue(queue_text, topic, existing["id"], existing["link"]), encoding="utf-8")
                if not args.no_git and not args.dry_run:
                    commit_and_push(f"Queue: {today} already published as post {existing['id']}")
                return
            die(f"a {existing['status']} post already exists for this topic (id {existing['id']}); publish or delete it first")

    if args.stub:
        post = json.loads(Path(args.stub).read_text(encoding="utf-8"))
        log(f"using stub post from {args.stub}")
    else:
        post = generate_post(topic, today, recent_posts(wp))
    validate_post(post)

    images = prepare_images(wp, post, topic, args.dry_run)
    result = publish(wp, post, topic, images, now, args.dry_run)

    print("\n=== RESULT ===")
    print(f"title:   {post['title']}")
    print(f"post id: {result['id']}")
    print(f"status:  {result['status']}")
    print(f"link:    {result['link']}")
    if result["id"]:
        print(f"preview: {SITE}/?p={result['id']}&preview=true")

    if args.dry_run:
        log("dry run: queue and git untouched")
        return
    QUEUE_FILE.write_text(remove_from_queue(queue_text, topic, result["id"], result["link"]), encoding="utf-8")
    log("queue updated")
    if not args.no_git:
        commit_and_push(f"Publish {today}: {post['title']} (post {result['id']})")


if __name__ == "__main__":
    main()
