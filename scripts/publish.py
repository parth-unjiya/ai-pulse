"""AI Pulse publisher — combines /tmp/s*.md into HTML, updates index, commits, pushes.

Reads:
  /tmp/articles.json (article list)
  /tmp/s1_headlines.md ... /tmp/s8_trend.md (8 analysis sections)
  $REPO/blog/article-template.html
Writes:
  $REPO/articles/$TARGET_DATE.html
  $REPO/index.html

Env:
  REPO = repo dir
  TARGET_DATE = YYYY-MM-DD
  TARGET_LONG = 'Weekday, Month D, YYYY'
"""
import os
import re
import html
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta

REPO = os.environ.get("REPO", ".")
TARGET_DATE = os.environ.get("TARGET_DATE") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
TARGET_LONG = os.environ.get("TARGET_LONG") or datetime.strptime(TARGET_DATE, "%Y-%m-%d").strftime("%A, %B %-d, %Y")

# Combine sections
sections = ["s1_headlines", "s2_llm", "s3_research", "s4_startup", "s5_tools", "s6_policy", "s7_robotics", "s8_trend"]
parts = []
for s in sections:
    try:
        parts.append(open(f"/tmp/{s}.md").read())
    except Exception as e:
        print(f"WARN: missing /tmp/{s}.md ({e})", file=sys.stderr)

analysis = "\n\n".join(parts)
with open("/tmp/analysis.md", "w") as f:
    f.write(analysis)

word_count = len(analysis.split())
reading_time = max(1, word_count // 200)

articles = json.load(open("/tmp/articles.json"))
article_count = len(articles)
source_count = len(set(a["source"] for a in articles))

# Quality gate — refuse to publish if fetch was clearly broken.
# Below these thresholds the digest would be hallucinated or thin.
MIN_ARTICLES = int(os.environ.get("MIN_ARTICLES", "30"))
MIN_SOURCES = int(os.environ.get("MIN_SOURCES", "10"))

if article_count < MIN_ARTICLES or source_count < MIN_SOURCES:
    print(
        f"ERROR: insufficient data — got {article_count} articles from {source_count} sources, "
        f"need >= {MIN_ARTICLES} articles and >= {MIN_SOURCES} sources. "
        f"Aborting publish so fallback can take over.",
        file=sys.stderr,
    )
    sys.exit(2)


# Markdown -> HTML
def md_inline(t):
    t = html.escape(t, quote=False).replace("&#x27;", "'")
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return t


lines = analysis.split("\n")
out = []
in_list = False
first_section = True

for line in lines:
    s = line.strip()
    if not s:
        if in_list:
            out.append("</ul>"); in_list = False
        continue

    m = re.match(r"^## (.+)$", s)
    if m:
        if in_list:
            out.append("</ul>"); in_list = False
        if not first_section:
            out.append('<hr class="section-divider">')
        first_section = False
        out.append(f'<h2 class="content-section-header">{html.escape(m.group(1))}</h2>')
        continue

    m = re.match(r"^(\d+)\.\s+(.+)$", s)
    if m:
        if in_list:
            out.append("</ul>"); in_list = False
        out.append(
            f'<div class="numbered-item"><span class="item-number">{m.group(1)}</span>'
            f'<span class="item-content">{md_inline(m.group(2))}</span></div>'
        )
        continue

    if s.startswith("→") or s.startswith("→"):
        if in_list:
            out.append("</ul>"); in_list = False
        out.append(f'<p class="arrow-description">{md_inline(s[1:].strip())}</p>')
        continue

    if s.startswith("- ") or s.startswith("* "):
        if not in_list:
            out.append('<ul class="content-list">'); in_list = True
        out.append(f"<li>{md_inline(s[2:].strip())}</li>")
        continue

    if in_list:
        out.append("</ul>"); in_list = False
    out.append(f"<p>{md_inline(s)}</p>")

if in_list:
    out.append("</ul>")

content_html = "\n".join(out)

# Excerpt from first headline
excerpt = "Daily AI news digest."
for line in lines:
    m = re.match(r"^\d+\.\s+\*\*(.+?)\*\*", line.strip())
    if m:
        excerpt = m.group(1)[:160]
        break

# Build HTML
title = f"AI Pulse — {TARGET_LONG}"
# Template is at repo root (for ai-pulse cloud clone) OR in blog/ subdir (local dev)
tpl_paths = [f"{REPO}/article-template.html", f"{REPO}/blog/article-template.html"]
tpl = None
for p in tpl_paths:
    if os.path.exists(p):
        tpl = open(p).read()
        break
if tpl is None:
    raise FileNotFoundError(f"Template not found in: {tpl_paths}")
html_out = tpl
html_out = html_out.replace("{{TITLE}}", html.escape(title, quote=True))
html_out = html_out.replace("{{EXCERPT}}", html.escape(excerpt, quote=True))
html_out = html_out.replace("{{DATE}}", TARGET_DATE)
html_out = html_out.replace("{{DATE_FORMATTED}}", TARGET_LONG)
html_out = html_out.replace("{{READING_TIME}}", str(reading_time))
html_out = html_out.replace("{{ARTICLE_COUNT}}", str(article_count))
html_out = html_out.replace("{{SOURCE_COUNT}}", str(source_count))
html_out = html_out.replace("{{CATEGORY_TAG}}", "Daily Digest")
html_out = html_out.replace("{{CONTENT}}", content_html)

article_path = f"{REPO}/articles/{TARGET_DATE}.html"
with open(article_path, "w") as f:
    f.write(html_out)
print(f"HTML_WRITTEN {article_path}")

# Update index.html
idx = open(f"{REPO}/index.html").read()
card = f"""      <article class="article-card fade-in" data-date="{TARGET_DATE}">
        <div class="card-accent"></div>
        <div class="card-body">
          <span class="category-tag category-digest">Daily Digest</span>
          <h2 class="card-title"><a href="articles/{TARGET_DATE}.html">{html.escape(title, quote=True)}</a></h2>
          <p class="card-excerpt">{html.escape(excerpt, quote=True)}</p>
          <div class="card-footer">
            <time datetime="{TARGET_DATE}">{TARGET_LONG}</time>
            <span class="reading-time">{reading_time} min read</span>
          </div>
        </div>
      </article>"""

# Remove existing card for this date
idx = re.sub(
    rf'\s*<article class="article-card[^"]*" data-date="{TARGET_DATE}">.*?</article>',
    "", idx, flags=re.DOTALL,
)

# Insert card at start of grid
idx = re.sub(
    r'(<section class="articles-grid" id="articles-grid"[^>]*>)',
    lambda m: m.group(1) + "\n" + card,
    idx, count=1,
)

# Sort cards by data-date desc
match = re.search(
    r'(<section class="articles-grid" id="articles-grid"[^>]*>)(.*?)(</section>)',
    idx, flags=re.DOTALL,
)
if match:
    body = match.group(2)
    cards = re.findall(
        r'(<article class="article-card[^"]*" data-date="([^"]+)">.*?</article>)',
        body, flags=re.DOTALL,
    )
    cards.sort(key=lambda c: c[1], reverse=True)
    new_body = "\n" + "\n".join("      " + c[0].strip() for c in cards) + "\n    "
    idx = idx[:match.start()] + match.group(1) + new_body + match.group(3) + idx[match.end():]

with open(f"{REPO}/index.html", "w") as f:
    f.write(idx)
print("INDEX_UPDATED")

# Git commit and push
subprocess.run(["git", "add", "index.html", "articles/"], cwd=REPO, check=True)
subprocess.run(["git", "commit", "-m", f"Add digest for {TARGET_DATE}"], cwd=REPO, check=True)
subprocess.run(["git", "push", "origin", "main"], cwd=REPO, check=True)
print(f"PUSHED https://parth-unjiya.github.io/ai-pulse/articles/{TARGET_DATE}.html")
