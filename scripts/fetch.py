"""AI Pulse news fetcher — outputs /tmp/articles.json.

Parallelized feed fetching to stay under 60s.
"""
import json, re, sys, subprocess
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Auto-install missing deps (defensive, in case pip install failed silently before)
try:
    import feedparser
    import requests
except ImportError:
    print("Installing missing deps...", file=sys.stderr)
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "feedparser", "requests"], check=True)
    import feedparser
    import requests

TARGET = (datetime.now(timezone.utc) - timedelta(days=1)).date()
DAY_START = datetime(TARGET.year, TARGET.month, TARGET.day, tzinfo=timezone.utc)
DAY_END = DAY_START + timedelta(days=1)
UA = "python:ai-pulse:v2.0 (by parth-unjiya on github)"

RSS = [
    ("TechCrunch", "https://techcrunch.com/category/artificial-intelligence/feed/", "General AI", 10),
    ("The Verge", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "General AI", 10),
    ("VentureBeat", "https://venturebeat.com/category/ai/feed/", "General AI", 10),
    ("The Decoder", "https://the-decoder.com/feed/", "General AI", 10),
    ("Wired AI", "https://www.wired.com/feed/tag/ai/latest/rss", "General AI", 9),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab", "General AI", 8),
    ("Engadget", "https://www.engadget.com/rss.xml", "General AI", 7),
    ("ArXiv cs.AI", "https://export.arxiv.org/rss/cs.AI", "Research", 8),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/", "Research", 9),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml", "Research", 9),
    ("MarkTechPost", "https://www.marktechpost.com/feed/", "Research", 7),
    ("OpenAI Blog", "https://openai.com/blog/rss.xml", "Company", 10),
    ("Google AI", "https://blog.google/technology/ai/rss/", "Company", 10),
    ("NVIDIA Blog", "https://blogs.nvidia.com/feed/", "Company", 8),
    ("IEEE Spectrum", "https://spectrum.ieee.org/feeds/feed.rss", "Robotics", 8),
    ("Hacker News", "https://hnrss.org/newest?q=AI+OR+LLM&points=50", "Community", 7),
    ("Import AI", "https://importai.substack.com/feed", "Newsletter", 8),
    ("Ben's Bites", "https://www.bensbites.com/feed", "Newsletter", 7),
    ("Simon Willison", "https://simonwillison.net/atom/everything/", "Newsletter", 8),
    ("Sebastian Raschka", "https://magazine.sebastianraschka.com/feed", "Newsletter", 7),
]


def clean_desc(t):
    t = re.sub(r"<[^>]+>", "", t or "").strip()
    return t[:300] + "..." if len(t) > 300 else t


def parse_pub(e):
    for k in ("published_parsed", "updated_parsed"):
        p = getattr(e, k, None)
        if p:
            return datetime(*p[:6], tzinfo=timezone.utc)
    return None


def fetch_rss(src, url, cat, pri):
    """Fetch one RSS feed. Returns (src, list_of_articles)."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        f = feedparser.parse(r.content)
        out = []
        for e in f.entries[:5]:
            pub = parse_pub(e)
            if pub and not (DAY_START <= pub < DAY_END):
                continue
            out.append({
                "title": (e.get("title") or "").strip(),
                "link": e.get("link", ""),
                "description": clean_desc(e.get("summary") or e.get("description") or ""),
                "pub_date": pub.isoformat() if pub else None,
                "source": src, "category": cat, "priority": pri,
            })
        return src, out
    except Exception as ex:
        return src, []


def fetch_reddit(sub):
    try:
        r = requests.get(
            f"https://www.reddit.com/r/{sub}/top.json?t=day&limit=15",
            headers={"User-Agent": UA}, timeout=10,
        )
        data = r.json()
        out = []
        for p in data.get("data", {}).get("children", [])[:20]:
            d = p.get("data", {})
            if d.get("score", 0) < 30:
                continue
            if len(out) >= 5:
                break
            created = datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc)
            if not (DAY_START <= created < DAY_END):
                continue
            out.append({
                "title": d.get("title", "").strip(),
                "link": "https://reddit.com" + d.get("permalink", ""),
                "description": (d.get("selftext") or "")[:300],
                "pub_date": created.isoformat(),
                "source": f"Reddit r/{sub}", "category": "Community", "priority": 6,
            })
        return f"Reddit r/{sub}", out
    except Exception:
        return f"Reddit r/{sub}", []


def fetch_hf_papers():
    try:
        r = requests.get(
            "https://huggingface.co/api/daily_papers",
            headers={"User-Agent": UA}, timeout=10,
        )
        papers = r.json()[:5]
        out = []
        for p in papers:
            paper = p.get("paper", p)
            out.append({
                "title": paper.get("title", "").strip(),
                "link": "https://huggingface.co/papers/" + paper.get("id", ""),
                "description": (paper.get("summary") or "")[:300],
                "pub_date": None,
                "source": "HF Papers", "category": "Research", "priority": 8,
            })
        return "HF Papers", out
    except Exception:
        return "HF Papers", []


articles = []
sources_used = set()

# Parallel fetch: all RSS + Reddit + HF in parallel
with ThreadPoolExecutor(max_workers=15) as ex:
    futures = []
    for src, url, cat, pri in RSS:
        futures.append(ex.submit(fetch_rss, src, url, cat, pri))
    for sub in ["MachineLearning", "LocalLLaMA", "ChatGPT", "OpenAI", "artificial"]:
        futures.append(ex.submit(fetch_reddit, sub))
    futures.append(ex.submit(fetch_hf_papers))

    for fut in as_completed(futures, timeout=60):
        src, items = fut.result()
        if items:
            sources_used.add(src)
            articles.extend(items)
        print(f"  {src}: {len(items)}", file=sys.stderr)

# Dedup
seen_urls, seen_titles, unique = set(), set(), []
for a in articles:
    url_n = a["link"].split("?")[0].rstrip("/").lower()
    t_n = re.sub(r"[^\w\s]", "", a["title"].lower()).strip()
    if url_n in seen_urls or t_n in seen_titles:
        continue
    seen_urls.add(url_n)
    seen_titles.add(t_n)
    unique.append(a)

unique.sort(key=lambda a: -a["priority"])
unique = unique[:50]

with open("/tmp/articles.json", "w") as f:
    json.dump(unique, f)
print(f"FETCHED {len(unique)} articles from {len(sources_used)} sources")
