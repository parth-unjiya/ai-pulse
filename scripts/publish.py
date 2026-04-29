"""AI Pulse publisher (CMS-style flow).

Writes the day's article as a markdown source file with YAML frontmatter,
then runs build.py to regenerate ALL HTMLs from the current template.
This means design changes (in _layouts/article.html) automatically apply
to every article on the next run — no per-article migration needed.

Reads:
  /tmp/articles.json (article list — for counts and quality gate)
  /tmp/s1_headlines.md ... /tmp/s8_trend.md (8 analysis sections)
  $REPO/_layouts/article.html (master template)

Writes:
  $REPO/articles/data/$TARGET_DATE.md   (source — committed)
  $REPO/articles/$TARGET_DATE.html      (built — committed)
  $REPO/index.html, manifest.json, feed.xml, sitemap.xml (built — committed)

Env:
  REPO = repo dir
  TARGET_DATE = YYYY-MM-DD
  TARGET_LONG = 'Weekday, Month D, YYYY'
  MIN_ARTICLES (default 30), MIN_SOURCES (default 10)
"""
import os
import re
import sys
import json
import subprocess
from datetime import datetime, timezone, timedelta

REPO = os.environ.get("REPO", ".")
TARGET_DATE = os.environ.get("TARGET_DATE") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
TARGET_LONG = os.environ.get("TARGET_LONG") or datetime.strptime(TARGET_DATE, "%Y-%m-%d").strftime("%A, %B %-d, %Y")

# ──────────────────────────────────────────────────────────────────────
# Quality gate
# ──────────────────────────────────────────────────────────────────────
articles = json.load(open("/tmp/articles.json"))
article_count = len(articles)
source_count = len(set(a["source"] for a in articles))

MIN_ARTICLES = int(os.environ.get("MIN_ARTICLES", "30"))
MIN_SOURCES = int(os.environ.get("MIN_SOURCES", "10"))

if article_count < MIN_ARTICLES or source_count < MIN_SOURCES:
    print(
        f"ERROR: insufficient data — {article_count} articles from {source_count} sources, "
        f"need >= {MIN_ARTICLES} articles and >= {MIN_SOURCES} sources. "
        f"Aborting publish so fallback can take over.",
        file=sys.stderr,
    )
    sys.exit(2)


# ──────────────────────────────────────────────────────────────────────
# Combine the 8 analysis sections into one markdown body
# ──────────────────────────────────────────────────────────────────────
sections = [
    "s1_headlines", "s2_llm", "s3_research", "s4_startup",
    "s5_tools", "s6_policy", "s7_robotics", "s8_trend",
]
parts = []
for s in sections:
    p = f"/tmp/{s}.md"
    if os.path.exists(p):
        parts.append(open(p).read().strip())
    else:
        print(f"WARN: missing /tmp/{s}.md", file=sys.stderr)

body_md = "\n\n".join(parts)
word_count = len(body_md.split())
reading_time = max(1, word_count // 200)


# ──────────────────────────────────────────────────────────────────────
# Pick excerpt = first headline text (strip markdown)
# ──────────────────────────────────────────────────────────────────────
excerpt = "Daily AI news digest."
for line in body_md.split("\n"):
    m = re.match(r"^\d+\.\s+\*\*(.+?)\*\*", line.strip())
    if m:
        excerpt = m.group(1)[:160]
        break


# ──────────────────────────────────────────────────────────────────────
# Write source markdown with YAML frontmatter
# ──────────────────────────────────────────────────────────────────────
data_dir = f"{REPO}/articles/data"
os.makedirs(data_dir, exist_ok=True)

title = f"AI Pulse — {TARGET_LONG}"
fm = (
    "---\n"
    f"date: {TARGET_DATE}\n"
    f'title: "{title}"\n'
    f'excerpt: "{excerpt.replace(chr(34), chr(39))}"\n'
    f"article_count: {article_count}\n"
    f"source_count: {source_count}\n"
    f"reading_time: {reading_time}\n"
    "---\n\n"
)
md_path = f"{data_dir}/{TARGET_DATE}.md"
with open(md_path, "w") as f:
    f.write(fm + body_md + "\n")
print(f"WROTE_SOURCE {md_path}")


# ──────────────────────────────────────────────────────────────────────
# Run build.py to regenerate ALL HTMLs from current template
# ──────────────────────────────────────────────────────────────────────
build_path = f"{REPO}/scripts/build.py"
subprocess.run(
    [sys.executable, build_path, REPO],
    check=True,
)


# ──────────────────────────────────────────────────────────────────────
# Git commit and push
# ──────────────────────────────────────────────────────────────────────
# Pull latest BEFORE committing to avoid non-fast-forward push failures
# (the cloud Claude scheduler and local fallback can race)
subprocess.run(
    ["git", "pull", "--rebase", "--autostash", "origin", "main"],
    cwd=REPO, check=False,
)

subprocess.run(
    ["git", "add", "articles/", "index.html", "manifest.json", "feed.xml", "sitemap.xml", "_layouts/", "css/", "js/"],
    cwd=REPO, check=True,
)
diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO).returncode
if diff == 0:
    print("No changes to commit.")
    sys.exit(0)

subprocess.run(["git", "commit", "-m", f"Add digest for {TARGET_DATE}"], cwd=REPO, check=True)

# Push with retry — if first push fails with non-FF, rebase + retry once
push = subprocess.run(["git", "push", "origin", "main"], cwd=REPO)
if push.returncode != 0:
    print("Push failed; pulling + rebasing then retrying...", file=sys.stderr)
    subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=REPO, check=False)
    push2 = subprocess.run(["git", "push", "origin", "main"], cwd=REPO)
    if push2.returncode != 0:
        # Roll back the local commit so we don't leave orphaned state
        print("Push failed again; rolling back local commit.", file=sys.stderr)
        subprocess.run(["git", "reset", "--soft", "HEAD~1"], cwd=REPO, check=False)
        sys.exit(3)
print(f"PUSHED https://parth-unjiya.github.io/ai-pulse/articles/{TARGET_DATE}.html")
