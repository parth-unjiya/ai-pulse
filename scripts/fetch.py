"""AI Pulse news fetcher — outputs /tmp/articles.json.

Fetches from 100+ sources in parallel, dedupes, filters to TARGET_DATE.
Designed to stay under 90s even with all feeds active.

Usage:
    python3 fetch.py            # fresh fetch, write /tmp/articles.json
    python3 fetch.py --merge    # merge with existing /tmp/articles.json (multi-pass)
"""
import json, os, re, sys, subprocess
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Auto-install missing deps (defensive)
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
UA = "python:ai-pulse:v2.1 (by parth-unjiya on github)"
TIMEOUT = 12  # per-feed HTTP timeout
MERGE_MODE = "--merge" in sys.argv

# ──────────────────────────────────────────────────────────────────────────
# RSS FEEDS — 100+ sources covering AI/tech news, research, company blogs,
# newsletters, robotics, and more. Priority is used for ranking when capping.
# Format: (name, url, category, priority)
# ──────────────────────────────────────────────────────────────────────────
RSS = [
    # ─── General AI & Tech News (25) ───
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "General AI", 10),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "General AI", 10),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/", "General AI", 10),
    ("The Decoder", "https://the-decoder.com/feed/", "General AI", 9),
    ("Wired AI", "https://www.wired.com/feed/tag/ai/latest/rss", "General AI", 9),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab", "General AI", 8),
    ("Engadget", "https://www.engadget.com/rss.xml", "General AI", 7),
    ("CNBC Tech", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910", "General AI", 7),
    ("9to5Google AI", "https://9to5google.com/guides/artificial-intelligence/feed/", "General AI", 7),
    ("9to5Mac AI", "https://9to5mac.com/guides/artificial-intelligence/feed/", "General AI", 7),
    ("AI Business", "https://aibusiness.com/rss.xml", "General AI", 7),
    ("Tom's Hardware", "https://www.tomshardware.com/feeds/all", "General AI", 6),
    ("SiliconANGLE AI", "https://siliconangle.com/category/ai/feed/", "General AI", 6),
    ("The Register AI", "https://www.theregister.com/data_centre/ai_ml/headlines.atom", "General AI", 7),
    ("ZDNet AI", "https://www.zdnet.com/topic/artificial-intelligence/rss.xml", "General AI", 6),
    ("Forbes AI", "https://www.forbes.com/ai/feed/", "General AI", 7),
    ("Fortune AI", "https://fortune.com/section/artificial-intelligence/feed/", "General AI", 7),
    ("Axios", "https://api.axios.com/feed/", "General AI", 7),
    ("Business Insider AI", "https://www.businessinsider.com/sai/rss", "General AI", 6),
    ("Inverse Innovation", "https://www.inverse.com/innovation/rss", "General AI", 5),
    ("AI Magazine", "https://aimagazine.com/rss", "General AI", 5),
    ("Analytics India Mag", "https://analyticsindiamag.com/feed/", "General AI", 5),
    ("Analytics Vidhya", "https://www.analyticsvidhya.com/feed/", "General AI", 5),
    ("Geeky Gadgets AI", "https://www.geeky-gadgets.com/category/artificial-intelligence-news/feed/", "General AI", 4),
    ("Times of AI", "https://www.timesofai.com/feed", "General AI", 4),

    # ─── Major Company / Lab Blogs (30) ───
    ("OpenAI Blog", "https://openai.com/blog/rss.xml", "Company", 10),
    ("OpenAI News", "https://openai.com/news/rss.xml", "Company", 10),
    ("Google AI", "https://blog.google/technology/ai/rss/", "Company", 10),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", "Company", 10),
    ("NVIDIA Blog", "https://blogs.nvidia.com/feed/", "Company", 8),
    ("NVIDIA Developer", "https://developer.nvidia.com/blog/feed", "Company", 7),
    ("Meta AI", "https://ai.meta.com/blog/rss/", "Company", 9),
    ("Microsoft AI", "https://blogs.microsoft.com/ai/feed/", "Company", 9),
    ("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/", "Company", 8),
    ("AWS ML", "https://aws.amazon.com/blogs/machine-learning/feed/", "Company", 8),
    ("Azure AI", "https://azure.microsoft.com/en-us/blog/topics/ai-machine-learning/feed/", "Company", 7),
    ("IBM Research", "https://research.ibm.com/blog/feed/atom", "Company", 7),
    ("Apple ML", "https://machinelearning.apple.com/rss.xml", "Company", 8),
    ("Hugging Face Blog", "https://huggingface.co/blog/feed.xml", "Company", 9),
    ("Cohere", "https://cohere.com/blog/rss.xml", "Company", 7),
    ("Mistral AI", "https://mistral.ai/news/feed/", "Company", 8),
    ("Stability AI", "https://stability.ai/news?format=rss", "Company", 7),
    ("Anthropic News", "https://www.anthropic.com/news/rss.xml", "Company", 10),
    ("Anthropic Research", "https://www.anthropic.com/research/rss.xml", "Company", 9),
    ("Together AI", "https://www.together.ai/blog/rss.xml", "Company", 7),
    ("Replicate", "https://replicate.com/blog.rss", "Company", 6),
    ("LangChain", "https://blog.langchain.dev/rss/", "Company", 7),
    ("Pinecone", "https://www.pinecone.io/blog/rss.xml", "Company", 6),
    ("Weaviate", "https://weaviate.io/blog/rss.xml", "Company", 6),
    ("Perplexity", "https://www.perplexity.ai/hub/blog/rss.xml", "Company", 7),
    ("Inflection", "https://inflection.ai/feed", "Company", 6),
    ("Adept", "https://www.adept.ai/blog/rss.xml", "Company", 6),
    ("Runway ML", "https://runwayml.com/blog/rss/", "Company", 7),
    ("ElevenLabs", "https://elevenlabs.io/blog/rss.xml", "Company", 6),
    ("OpenRouter", "https://openrouter.ai/blog/rss.xml", "Company", 5),

    # ─── Research (15) ───
    ("ArXiv cs.AI", "https://export.arxiv.org/rss/cs.AI", "Research", 8),
    ("ArXiv cs.LG", "https://export.arxiv.org/rss/cs.LG", "Research", 8),
    ("ArXiv cs.CL", "https://export.arxiv.org/rss/cs.CL", "Research", 8),
    ("ArXiv cs.CV", "https://export.arxiv.org/rss/cs.CV", "Research", 7),
    ("ArXiv cs.RO", "https://export.arxiv.org/rss/cs.RO", "Research", 7),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/", "Research", 9),
    ("The Gradient", "https://thegradient.pub/rss/", "Research", 7),
    ("BAIR Blog", "https://bair.berkeley.edu/blog/feed.xml", "Research", 7),
    ("Stanford AI Lab", "https://ai.stanford.edu/blog/feed.xml", "Research", 7),
    ("Lil'Log", "https://lilianweng.github.io/index.xml", "Research", 7),
    ("MarkTechPost", "https://www.marktechpost.com/feed/", "Research", 6),
    ("Towards Data Science", "https://towardsdatascience.com/feed", "Research", 6),
    ("Papers with Code", "https://paperswithcode.com/feeds/all.xml", "Research", 7),
    ("Distill", "https://distill.pub/rss.xml", "Research", 6),
    ("AI Trends", "https://www.aitrends.com/feed/", "Research", 5),

    # ─── Newsletters / Substack (20) ───
    ("Import AI", "https://importai.substack.com/feed", "Newsletter", 8),
    ("Ben's Bites", "https://www.bensbites.com/feed", "Newsletter", 7),
    ("AlphaSignal", "https://alphasignal.ai/rss.xml", "Newsletter", 7),
    ("Last Week in AI", "https://lastweekin.ai/feed", "Newsletter", 7),
    ("Sebastian Raschka", "https://magazine.sebastianraschka.com/feed", "Newsletter", 8),
    ("Simon Willison", "https://simonwillison.net/atom/everything/", "Newsletter", 8),
    ("One Useful Thing", "https://www.oneusefulthing.org/feed", "Newsletter", 8),
    ("Unsupervised Learning", "https://newsletter.unsupervisedlearning.com/feed", "Newsletter", 6),
    ("The Algorithmic Bridge", "https://www.thealgorithmicbridge.com/feed", "Newsletter", 7),
    ("AI Snake Oil", "https://www.aisnakeoil.com/feed", "Newsletter", 7),
    ("Eugene Yan", "https://eugeneyan.com/rss/", "Newsletter", 7),
    ("Chip Huyen", "https://huyenchip.com/feed.xml", "Newsletter", 7),
    ("Jay Alammar", "https://jalammar.github.io/feed.xml", "Newsletter", 7),
    ("Sebastian Ruder", "https://www.ruder.io/rss/", "Newsletter", 7),
    ("AI Breakdown", "https://aibreakdown.substack.com/feed", "Newsletter", 6),
    ("The AI Edge", "https://newsletter.theaiedge.io/feed", "Newsletter", 6),
    ("Latent Space", "https://www.latent.space/feed", "Newsletter", 7),
    ("AI Supremacy", "https://aisupremacy.substack.com/feed", "Newsletter", 6),
    ("Pragmatic Engineer", "https://blog.pragmaticengineer.com/rss/", "Newsletter", 6),
    ("The AI Daily Brief", "https://www.theaidailybrief.com/feed", "Newsletter", 6),

    # ─── Robotics & Hardware (8) ───
    ("IEEE Spectrum", "https://spectrum.ieee.org/feeds/feed.rss", "Robotics", 8),
    ("The Robot Report", "https://www.therobotreport.com/feed/", "Robotics", 7),
    ("Robohub", "https://robohub.org/feed/", "Robotics", 6),
    ("Robotics & Automation News", "https://roboticsandautomationnews.com/feed/", "Robotics", 5),
    ("AnandTech", "https://www.anandtech.com/rss/", "Robotics", 5),
    ("HotHardware", "https://hothardware.com/news.aspx?rss=1", "Robotics", 5),
    ("ServeTheHome", "https://www.servethehome.com/feed/", "Robotics", 5),
    ("Wccftech", "https://wccftech.com/feed/", "Robotics", 5),

    # ─── Policy & Ethics (5) ───
    ("AI Now Institute", "https://ainowinstitute.org/feed", "Policy", 7),
    ("Center for AI Safety", "https://www.safe.ai/blog?format=rss", "Policy", 6),
    ("Stanford HAI", "https://hai.stanford.edu/news/rss.xml", "Policy", 7),
    ("AI Policy Exchange", "https://aipolicyexchange.org/feed", "Policy", 5),
    ("Tech Policy Press", "https://www.techpolicy.press/feed/", "Policy", 6),

    # ─── Community / Aggregators (5) ───
    ("Hacker News AI", "https://hnrss.org/newest?q=AI+OR+LLM+OR+%22artificial+intelligence%22&points=50", "Community", 7),
    ("Hacker News ML", "https://hnrss.org/newest?q=machine+learning+OR+neural+network&points=50", "Community", 6),
    ("Product Hunt AI", "https://www.producthunt.com/feed?category=artificial-intelligence", "Tools", 6),
    ("Dev.to AI", "https://dev.to/feed/tag/ai", "Community", 5),
    ("Dev.to ML", "https://dev.to/feed/tag/machinelearning", "Community", 5),
]

# Reddit subs (15) — Reddit JSON API
REDDIT_SUBS = [
    "MachineLearning", "artificial", "LocalLLaMA", "singularity", "ChatGPT",
    "OpenAI", "StableDiffusion", "learnmachinelearning", "deeplearning",
    "MLOps", "computervision", "LanguageTechnology", "Anthropic",
    "AutoGenAI", "ArtificialInteligence",
]


def clean_desc(t):
    t = re.sub(r"<[^>]+>", "", t or "").strip()
    t = re.sub(r"\s+", " ", t)
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
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        if r.status_code != 200:
            return src, []
        f = feedparser.parse(r.content)
        out = []
        for e in f.entries[:8]:
            pub = parse_pub(e)
            if pub and not (DAY_START <= pub < DAY_END):
                continue
            link = e.get("link", "")
            title = (e.get("title") or "").strip()
            if not title or not link:
                continue
            out.append({
                "title": title,
                "link": link,
                "description": clean_desc(e.get("summary") or e.get("description") or ""),
                "pub_date": pub.isoformat() if pub else None,
                "source": src, "category": cat, "priority": pri,
            })
        return src, out
    except Exception:
        return src, []


def fetch_reddit(sub):
    try:
        r = requests.get(
            f"https://www.reddit.com/r/{sub}/top.json?t=day&limit=15",
            headers={"User-Agent": UA}, timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return f"Reddit r/{sub}", []
        data = r.json()
        out = []
        for p in data.get("data", {}).get("children", [])[:25]:
            d = p.get("data", {})
            if d.get("score", 0) < 30:
                continue
            if len(out) >= 6:
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
            headers={"User-Agent": UA}, timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return "HF Papers", []
        papers = r.json()[:8]
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


def fetch_google_news():
    """Google News AI search — high-volume general AI news aggregator."""
    try:
        url = "https://news.google.com/rss/search?q=artificial+intelligence+when:1d&hl=en-US&gl=US&ceid=US:en"
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        f = feedparser.parse(r.content)
        out = []
        for e in f.entries[:25]:
            pub = parse_pub(e)
            if pub and not (DAY_START <= pub < DAY_END):
                continue
            out.append({
                "title": (e.get("title") or "").strip(),
                "link": e.get("link", ""),
                "description": clean_desc(e.get("summary") or ""),
                "pub_date": pub.isoformat() if pub else None,
                "source": "Google News", "category": "General AI", "priority": 6,
            })
        return "Google News", out
    except Exception:
        return "Google News", []


# ──────────────────────────────────────────────────────────────────────────
# Run all fetchers in parallel
# ──────────────────────────────────────────────────────────────────────────
articles = []

# Load existing articles if merging (multi-pass mode)
if MERGE_MODE and os.path.exists("/tmp/articles.json"):
    try:
        with open("/tmp/articles.json") as f:
            articles = json.load(f)
        print(f"  [merge] loaded {len(articles)} existing articles", file=sys.stderr)
    except Exception:
        pass

with ThreadPoolExecutor(max_workers=25) as ex:
    futures = []
    for src, url, cat, pri in RSS:
        futures.append(ex.submit(fetch_rss, src, url, cat, pri))
    for sub in REDDIT_SUBS:
        futures.append(ex.submit(fetch_reddit, sub))
    futures.append(ex.submit(fetch_hf_papers))
    futures.append(ex.submit(fetch_google_news))

    for fut in as_completed(futures, timeout=90):
        try:
            src, items = fut.result()
            if items:
                articles.extend(items)
            print(f"  {src}: {len(items)}", file=sys.stderr)
        except Exception as ex:
            print(f"  [error] {ex}", file=sys.stderr)

# ──────────────────────────────────────────────────────────────────────────
# Dedupe by URL + title
# ──────────────────────────────────────────────────────────────────────────
seen_urls, seen_titles, unique = set(), set(), []
for a in articles:
    url_n = a["link"].split("?")[0].rstrip("/").lower()
    t_n = re.sub(r"[^\w\s]", "", a["title"].lower()).strip()
    if not t_n:
        continue
    if url_n in seen_urls or t_n in seen_titles:
        continue
    seen_urls.add(url_n)
    seen_titles.add(t_n)
    unique.append(a)

# Sort by priority and cap at 200 (was 50; we want comprehensive coverage)
unique.sort(key=lambda a: -a["priority"])
unique = unique[:200]

with open("/tmp/articles.json", "w") as f:
    json.dump(unique, f)

src_count = len(set(a["source"] for a in unique))
print(f"FETCHED {len(unique)} articles from {src_count} sources")
