"""AI Pulse notifier — updates Google Doc and sends Telegram message.

Env:
  TARGET_DATE, TARGET_LONG
  TELEGRAM_TOKEN, TELEGRAM_CHAT
  DOC_ID
  SA_JSON_PATH (default /tmp/sa.json)
"""
import os
import re
import sys
import requests
from datetime import datetime, timezone, timedelta

TARGET_DATE = os.environ.get("TARGET_DATE") or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
TARGET_LONG = os.environ.get("TARGET_LONG") or datetime.strptime(TARGET_DATE, "%Y-%m-%d").strftime("%A, %B %-d, %Y")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT = os.environ.get("TELEGRAM_CHAT")
DOC_ID = os.environ.get("DOC_ID")
SA_PATH = os.environ.get("SA_JSON_PATH", "/tmp/sa.json")

analysis = open("/tmp/analysis.md").read()

# Google Doc update
if DOC_ID and os.path.exists(SA_PATH):
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            SA_PATH, scopes=["https://www.googleapis.com/auth/documents"],
        )
        docs = build("docs", "v1", credentials=creds)
        sep = "=" * 60
        text = f"{sep}\nAI Daily Digest — {TARGET_LONG}\n{sep}\n\n{analysis}\n\n\n"
        docs.documents().batchUpdate(
            documentId=DOC_ID,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": text}}]},
        ).execute()
        print("DOC_UPDATED")
    except Exception as e:
        print(f"DOC_ERROR: {e}", file=sys.stderr)
else:
    print("DOC_SKIPPED (no DOC_ID or SA)")

# Telegram
if TELEGRAM_TOKEN and TELEGRAM_CHAT:
    try:
        import json
        articles = json.load(open("/tmp/articles.json"))
        article_count = len(articles)
        source_count = len(set(a["source"] for a in articles))

        top3 = open("/tmp/s1_headlines.md").read()
        trend = open("/tmp/s8_trend.md").read()
        # Strip markdown
        top3 = re.sub(r"\*\*(.+?)\*\*", r"\1", top3)
        trend = re.sub(r"\*\*(.+?)\*\*", r"\1", trend).replace("## TREND ANALYSIS", "").strip()

        msg = (
            f"🤖 AI Daily Digest — {TARGET_LONG}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔥 {top3.strip()}\n\n"
            f"💡 TREND OF THE DAY\n\n{trend}\n\n"
            f"🌐 https://parth-unjiya.github.io/ai-pulse/articles/{TARGET_DATE}.html\n"
            f"📰 {article_count} articles from {source_count} sources"
        )
        if len(msg) > 4000:
            msg = msg[:3950] + "\n[... truncated]"

        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT, "text": msg},
            timeout=30,
        )
        print(f"TELEGRAM_STATUS: {r.status_code}")
    except Exception as e:
        print(f"TELEGRAM_ERROR: {e}", file=sys.stderr)
else:
    print("TELEGRAM_SKIPPED (no token)")
