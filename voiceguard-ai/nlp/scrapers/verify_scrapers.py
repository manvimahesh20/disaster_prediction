#!/usr/bin/env python3
"""Verify scrapers: RSS, ReliefWeb, Telegram, arXiv

Runs each scraper with example inputs and prints counts + samples.
"""
import os
import json
from dotenv import load_dotenv


load_dotenv()


def print_section(title: str):
    print("\n" + "=" * 10 + f" {title} " + "=" * 10)


def run_rss():
    print_section("RSS")
    try:
        import rss_scraper
        rss_env = os.environ.get("RSS_FEEDS")
        feeds = [f.strip() for f in (rss_env.split(",") if rss_env else ["https://news.google.com/rss/search?q=Kerala+flood"]) if f.strip()]
        results = rss_scraper.fetch_feeds(feeds, limit_per_feed=3)
        print("Feeds:", feeds)
        for url, entries in results.items():
            print(f"{url}: {len(entries)} entries")
            for e in entries[:2]:
                print(json.dumps(e, ensure_ascii=False))
    except Exception as e:
        print("RSS error:", repr(e))


def run_reliefweb():
    print_section("ReliefWeb")
    try:
        import reliefweb_scraper
        q = os.environ.get("RELIEFWEB_QUERY", "Kerala flood")
        reports = reliefweb_scraper.fetch_reliefweb_reports(q, limit=5)
        print("Query:", q, "->", len(reports), "reports")
        for r in reports[:3]:
            print(json.dumps(r, ensure_ascii=False))
    except Exception as e:
        print("ReliefWeb error:", repr(e))


def run_telegram():
    print_section("Telegram")
    try:
        import telegram_scraper
        channels_env = os.environ.get("TELEGRAM_CHANNELS", "keralaupdates")
        channels = [c.strip() for c in channels_env.split(",") if c.strip()]
        print("Channels:", channels)
        for ch in channels:
            try:
                posts = telegram_scraper.fetch_telegram_channel(ch, limit=5)
                print(ch, "->", len(posts), "posts")
                for p in posts[:2]:
                    print(json.dumps(p, ensure_ascii=False))
            except Exception as e:
                print(f"{ch} error:", repr(e))
    except Exception as e:
        print("Telegram module error:", repr(e))


def run_arxiv():
    print_section("arXiv")
    try:
        import arxiv_scraper
        q = os.environ.get("DISASTER_KEYWORDS", "flood OR cyclone OR earthquake")
        papers = arxiv_scraper.fetch_arxiv(q, max_results=5)
        print("Query:", q, "->", len(papers), "papers")
        for p in papers[:3]:
            print(json.dumps(p, ensure_ascii=False))
    except Exception as e:
        print("arXiv error:", repr(e))


def main():
    run_rss()
    run_reliefweb()
    run_telegram()
    run_arxiv()
    print("\nVerification complete.")


if __name__ == "__main__":
    main()
