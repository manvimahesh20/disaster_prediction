"""Simple runner to smoke-test RSS, ReliefWeb, Telegram and arXiv scrapers."""
import os
import traceback

from dotenv import load_dotenv

load_dotenv()


def run_rss():
    rss_env = os.environ.get("RSS_FEEDS")
    if not rss_env:
        print("RSS_FEEDS not set — skipping RSS test")
        return
    feeds = [f.strip() for f in rss_env.split(",") if f.strip()]
    try:
        from rss_scraper import fetch_feeds
    except Exception:
        from voiceguard_ai.nlp.scrapers.rss_scraper import fetch_feeds

    print("Running RSS fetch for:", feeds)
    try:
        results = fetch_feeds(feeds, limit_per_feed=3)
        for url, entries in results.items():
            print(f"Feed {url}: {len(entries)} entries")
            for e in entries:
                print(" -", (e.get("title") or "").replace("\n", " ")[:140])
    except Exception:
        print("RSS fetch failed:")
        traceback.print_exc()


def run_reliefweb():
    q = os.environ.get("RELIEFWEB_QUERY")
    if not q:
        print("RELIEFWEB_QUERY not set — skipping ReliefWeb test")
        return
    try:
        from reliefweb_scraper import fetch_reliefweb_reports
    except Exception:
        from voiceguard_ai.nlp.scrapers.reliefweb_scraper import fetch_reliefweb_reports

    print(f"Running ReliefWeb fetch for: {q}")
    try:
        reports = fetch_reliefweb_reports(q, limit=5)
        print(f"Got {len(reports)} reports")
        for r in reports:
            print(" -", (r.get("title") or "")[:140])
    except Exception:
        print("ReliefWeb fetch failed:")
        traceback.print_exc()


def run_telegram():
    chs = os.environ.get("TELEGRAM_CHANNELS")
    if not chs:
        print("TELEGRAM_CHANNELS not set — skipping Telegram test")
        return
    channels = [c.strip() for c in chs.split(",") if c.strip()]
    try:
        from telegram_scraper import fetch_telegram_channel
    except Exception:
        from voiceguard_ai.nlp.scrapers.telegram_scraper import fetch_telegram_channel

    print("Running Telegram fetch for:", channels)
    try:
        for ch in channels:
            posts = fetch_telegram_channel(ch, limit=5)
            print(f"Channel {ch}: {len(posts)} posts")
            for p in posts:
                print(" -", (p.get("text") or "")[:140].replace("\n", " "))
    except Exception:
        print("Telegram fetch failed:")
        traceback.print_exc()


def run_arxiv():
    try:
        from arxiv_scraper import fetch_arxiv
    except Exception:
        from voiceguard_ai.nlp.scrapers.arxiv_scraper import fetch_arxiv

    print("Running arXiv fetch for disaster keywords")
    try:
        papers = fetch_arxiv("flood OR cyclone OR earthquake", max_results=5)
        print(f"Got {len(papers)} papers")
        for p in papers:
            print(" -", (p.get("title") or "")[:140])
    except Exception:
        print("arXiv fetch failed:")
        traceback.print_exc()


def main():
    print("Scrapers smoke-test starting...\n")
    run_rss()
    print("\n")
    run_reliefweb()
    print("\n")
    run_telegram()
    print("\n")
    run_arxiv()
    print("\nDone.")


if __name__ == "__main__":
    main()
