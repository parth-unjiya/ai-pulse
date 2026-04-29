"""AI Pulse — Static Site Builder.

Reads:
  _layouts/article.html             # master template
  articles/data/*.md                # source content (YAML frontmatter + markdown body)

Writes:
  articles/*.html                   # rendered articles (one per .md)
  index.html                        # homepage with article cards
  manifest.json                     # all articles list (used by article-nav.js)
  feed.xml                          # RSS feed
  sitemap.xml                       # XML sitemap

Usage:
  python3 scripts/build.py [REPO]

Run from a repo root or pass REPO path. This is the ONLY place that turns
data into HTML — change the layout once, run this, every page updates.
"""
import os
import re
import sys
import json
import html
from datetime import datetime, timezone, timedelta

REPO = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("REPO", os.getcwd())
DATA_DIR = f"{REPO}/articles/data"
ARTICLES_DIR = f"{REPO}/articles"
LAYOUTS_DIR = f"{REPO}/_layouts"
BASE_URL = "https://parth-unjiya.github.io/ai-pulse"


# ═══════════════════════════════════════════════════════════════════════
# Front-matter parser (minimal YAML — we only use simple key: value)
# ═══════════════════════════════════════════════════════════════════════
def parse_md(path):
    """Return (meta_dict, body_str). Frontmatter is delimited by --- on its own line."""
    with open(path) as f:
        text = f.read()
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return {}, text
    # Find closing --- as a standalone line (not embedded in body)
    m = re.search(r"^---\s*$", text[4:], re.MULTILINE)
    if not m:
        return {}, text
    fm_end = 4 + m.start()
    fm = text[4:fm_end].strip()
    body = text[fm_end + m.end() - m.start():].lstrip("\n")
    meta = {}
    for line in fm.split("\n"):
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        # Try numeric coercion
        if val.isdigit():
            val = int(val)
        meta[key] = val
    return meta, body


# ═══════════════════════════════════════════════════════════════════════
# Markdown → HTML (subset: headers, bold, italic, numbered, arrows, bullets)
# ═══════════════════════════════════════════════════════════════════════
def md_inline(text):
    """Convert inline markdown: bold, italic, escape html."""
    text = html.escape(text, quote=False).replace("&#x27;", "'")
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    return text


def md_to_html(md):
    """Convert our markdown digest format to the styled HTML used in articles."""
    lines = md.split("\n")
    out = []
    in_list = False
    first_section = True

    for raw in lines:
        s = raw.strip()
        if not s:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue

        # ## Section header
        m = re.match(r"^## (.+)$", s)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            if not first_section:
                out.append('<hr class="section-divider">')
            first_section = False
            out.append(f'<h2 class="content-section-header">{html.escape(m.group(1))}</h2>')
            continue

        # 1. Numbered headline (with optional bold)
        m = re.match(r"^(\d+)\.\s+(.+)$", s)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(
                f'<div class="numbered-item">'
                f'<span class="item-number">{m.group(1)}</span>'
                f'<span class="item-content">{md_inline(m.group(2))}</span>'
                f"</div>"
            )
            continue

        # → arrow follow-up
        if s.startswith("→"):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f'<p class="arrow-description">{md_inline(s[1:].strip())}</p>')
            continue

        # - / * bullet
        if s.startswith("- ") or s.startswith("* "):
            if not in_list:
                out.append('<ul class="content-list">')
                in_list = True
            out.append(f"<li>{md_inline(s[2:].strip())}</li>")
            continue

        # paragraph
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{md_inline(s)}</p>")

    if in_list:
        out.append("</ul>")

    return "\n          ".join(out)


# ═══════════════════════════════════════════════════════════════════════
# Article rendering
# ═══════════════════════════════════════════════════════════════════════
def render_article(meta, body, template):
    """Substitute placeholders in template with data from meta + rendered body."""
    date = meta.get("date", "")
    title = meta.get("title", f"AI Pulse — {date}")
    excerpt = meta.get("excerpt", "Daily AI news digest.")[:160]
    article_count = meta.get("article_count", 0)
    source_count = meta.get("source_count", 0)
    reading_time = meta.get("reading_time") or max(1, len(body.split()) // 200)
    category_tag = meta.get("category_tag", "Daily Digest")

    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        date_formatted = date_obj.strftime("%A, %B %-d, %Y")
    except Exception:
        date_formatted = date

    content_html = md_to_html(body)

    out = template
    out = out.replace("{{TITLE}}", html.escape(title, quote=True))
    out = out.replace("{{EXCERPT}}", html.escape(excerpt, quote=True))
    out = out.replace("{{DATE}}", date)
    out = out.replace("{{DATE_FORMATTED}}", date_formatted)
    out = out.replace("{{READING_TIME}}", str(reading_time))
    out = out.replace("{{ARTICLE_COUNT}}", str(article_count))
    out = out.replace("{{SOURCE_COUNT}}", str(source_count))
    out = out.replace("{{CATEGORY_TAG}}", html.escape(str(category_tag), quote=True))
    out = out.replace("{{CONTENT}}", content_html)
    return out


# ═══════════════════════════════════════════════════════════════════════
# Index page rebuild
# ═══════════════════════════════════════════════════════════════════════
def build_index_card(date, title, excerpt, reading_time):
    try:
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        date_formatted = date_obj.strftime("%A, %B %-d, %Y")
    except Exception:
        date_formatted = date
    return (
        f'      <article class="article-card fade-in" data-date="{date}">\n'
        f'        <div class="card-accent"></div>\n'
        f'        <div class="card-body">\n'
        f'          <span class="category-tag category-digest">Daily Digest</span>\n'
        f'          <h2 class="card-title"><a href="articles/{date}.html">{html.escape(title, quote=True)}</a></h2>\n'
        f'          <p class="card-excerpt">{html.escape(excerpt, quote=True)}</p>\n'
        f'          <div class="card-footer">\n'
        f'            <time datetime="{date}">{date_formatted}</time>\n'
        f'            <span class="reading-time">{reading_time} min read</span>\n'
        f"          </div>\n"
        f"        </div>\n"
        f"      </article>"
    )


def update_index(articles):
    """Rebuild articles-grid in index.html with all current articles."""
    idx_path = f"{REPO}/index.html"
    if not os.path.exists(idx_path):
        return
    with open(idx_path) as f:
        idx = f.read()

    # Strip old empty-state if present
    idx = re.sub(
        r'\s*<div[^>]*id="empty-state"[^>]*>.*?</section>',
        "\n    </section>",
        idx,
        flags=re.DOTALL,
    )

    # Rebuild grid body — sorted newest first
    cards = []
    for a in articles:
        cards.append(build_index_card(a["date"], a["title"], a["excerpt"], a["reading_time"]))
    new_body = "\n" + "\n".join(cards) + "\n    "

    pattern = r'(<section class="articles-grid" id="articles-grid"[^>]*>)(.*?)(</section>)'
    m = re.search(pattern, idx, flags=re.DOTALL)
    if m:
        idx = idx[: m.start()] + m.group(1) + new_body + m.group(3) + idx[m.end():]
    else:
        # Insert grid section if missing
        # Try to find a hero/main and append; otherwise just write into body
        pass

    with open(idx_path, "w") as f:
        f.write(idx)


# ═══════════════════════════════════════════════════════════════════════
# Manifest, RSS, Sitemap
# ═══════════════════════════════════════════════════════════════════════
def write_manifest(articles):
    items = [
        {
            "date": a["date"],
            "title": a["title"],
            "excerpt": a["excerpt"],
            "article_count": a.get("article_count", 0),
            "source_count": a.get("source_count", 0),
        }
        for a in articles
    ]
    with open(f"{REPO}/manifest.json", "w") as f:
        json.dump(
            {"articles": items, "updated": datetime.now(timezone.utc).isoformat()},
            f,
            indent=2,
        )


def write_feed(articles):
    def rfc822(d):
        try:
            dt = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt.strftime("%a, %d %b %Y 00:00:00 +0000")
        except Exception:
            return ""

    items = []
    for a in articles[:30]:
        items.append(
            f"""    <item>
      <title>{html.escape(a['title'])}</title>
      <link>{BASE_URL}/articles/{a['date']}.html</link>
      <guid isPermaLink="true">{BASE_URL}/articles/{a['date']}.html</guid>
      <pubDate>{rfc822(a['date'])}</pubDate>
      <description>{html.escape(a['excerpt'])}</description>
    </item>"""
        )

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>AI Pulse — Daily AI News Digest</title>
    <link>{BASE_URL}/</link>
    <atom:link href="{BASE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
    <description>Daily AI news digest covering LLMs, research, startups, tools, policy, robotics.</description>
    <language>en-us</language>
    <lastBuildDate>{datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""
    with open(f"{REPO}/feed.xml", "w") as f:
        f.write(rss)


def write_sitemap(articles):
    urls = [
        f'  <url><loc>{BASE_URL}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>'
    ]
    for a in articles:
        urls.append(
            f'  <url><loc>{BASE_URL}/articles/{a["date"]}.html</loc><lastmod>{a["date"]}</lastmod><priority>0.8</priority></url>'
        )
    sm = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    with open(f"{REPO}/sitemap.xml", "w") as f:
        f.write(sm)


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════
def main():
    if not os.path.isdir(DATA_DIR):
        print(f"ERROR: data dir not found: {DATA_DIR}", file=sys.stderr)
        sys.exit(1)

    template_path = f"{LAYOUTS_DIR}/article.html"
    if not os.path.exists(template_path):
        print(f"ERROR: template not found: {template_path}", file=sys.stderr)
        sys.exit(1)
    with open(template_path) as f:
        template = f.read()

    # Read all article data files
    articles = []
    known_dates = set()
    skipped = 0
    for fn in sorted(os.listdir(DATA_DIR), reverse=True):
        if not fn.endswith(".md"):
            continue
        date = fn[:-3]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            continue
        meta, body = parse_md(f"{DATA_DIR}/{fn}")

        # Validation: require non-empty body with at least one ## section
        if not body.strip() or "##" not in body:
            print(f"  ⚠️ skipping {fn} (empty body or no ## sections)", file=sys.stderr)
            skipped += 1
            continue

        meta["date"] = date  # canonical
        if "title" not in meta:
            try:
                d = datetime.strptime(date, "%Y-%m-%d")
                meta["title"] = f"AI Pulse — {d.strftime('%B %-d, %Y')}"
            except Exception:
                meta["title"] = f"AI Pulse — {date}"
        if "reading_time" not in meta:
            meta["reading_time"] = max(1, len(body.split()) // 200)

        rendered = render_article(meta, body, template)
        out_path = f"{ARTICLES_DIR}/{date}.html"
        with open(out_path, "w") as f:
            f.write(rendered)
        known_dates.add(date)

        articles.append({
            "date": date,
            "title": meta["title"],
            "excerpt": meta.get("excerpt", ""),
            "reading_time": meta["reading_time"],
            "article_count": meta.get("article_count", 0),
            "source_count": meta.get("source_count", 0),
        })

    # Articles already sorted descending (filenames sort that way after reverse=True)
    print(f"BUILT {len(articles)} articles" + (f" ({skipped} skipped)" if skipped else ""))

    # Orphan cleanup: delete any articles/YYYY-MM-DD.html with no matching .md source
    removed = 0
    for fn in os.listdir(ARTICLES_DIR):
        if not fn.endswith(".html"):
            continue
        date = fn[:-5]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            continue
        if date not in known_dates:
            try:
                os.remove(f"{ARTICLES_DIR}/{fn}")
                removed += 1
                print(f"  🗑️  removed orphan {fn}", file=sys.stderr)
            except OSError:
                pass
    if removed:
        print(f"ORPHANS_REMOVED ({removed})")

    update_index(articles)
    print("INDEX_UPDATED")

    write_manifest(articles)
    print(f"MANIFEST_WRITTEN ({len(articles)} entries)")

    write_feed(articles)
    print("FEED_WRITTEN")

    write_sitemap(articles)
    print("SITEMAP_WRITTEN")


if __name__ == "__main__":
    main()
