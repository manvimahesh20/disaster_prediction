"""Aggregate scrapers for disasters and persist to JSONL.

Collects from RSS, NewsAPI, Twitter, Instagram, and arXiv (papers).
Runs one iteration when `run_once()` is called. Use `run_scheduler.py` to run periodically.
"""
import os
import json
import time
from typing import List, Dict

from dotenv import load_dotenv

load_dotenv()

OUT_PATH = os.environ.get("DISASTER_OUTPUT", os.path.join(os.getcwd(), "data", "disaster_articles.jsonl"))
KEYWORDS = os.environ.get("DISASTER_KEYWORDS", "flood OR cyclone OR earthquake").strip()


def _ensure_out_path(path: str):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def _load_seen_ids(path: str) -> set:
    seen = set()
    if not os.path.exists(path):
        return seen
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    if obj.get("id"):
                        seen.add(obj.get("id"))
                    elif obj.get("url"):
                        seen.add(obj.get("url"))
                except Exception:
                    continue
    except Exception:
        pass
    return seen


def _append_items(path: str, items: List[Dict]):
    _ensure_out_path(path)
    with open(path, "a", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def run_once() -> Dict[str, int]:
    """Run one collection iteration across scrapers and persist new items.

    Concurrently fetch data from RSS feeds, ReliefWeb, Telegram channels, and arXiv.
    """
    results: List[Dict] = []
    seen = _load_seen_ids(OUT_PATH)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    executor = ThreadPoolExecutor(max_workers=int(os.environ.get("SCRAPER_WORKERS", "6")))
    futures_map = {}
    # RSS
    rss = os.environ.get("RSS_FEEDS")
    if rss:
        try:
            try:
                from rss_scraper import fetch_feeds
            except Exception:
                from voiceguard_ai.nlp.scrapers.rss_scraper import fetch_feeds
            feeds = [f.strip() for f in rss.split(",") if f.strip()]
            fut = executor.submit(fetch_feeds, feeds, 5)
            futures_map[fut] = ("rss", None)
        except Exception:
            pass

    # ReliefWeb
    relief_q = os.environ.get("RELIEFWEB_QUERY")
    if relief_q:
        try:
            try:
                from reliefweb_scraper import fetch_reliefweb_reports
            except Exception:
                from voiceguard_ai.nlp.scrapers.reliefweb_scraper import fetch_reliefweb_reports
            fut = executor.submit(fetch_reliefweb_reports, relief_q, 20)
            futures_map[fut] = ("reliefweb", None)
        except Exception:
            pass

    # Telegram channels
    tg_channels = os.environ.get("TELEGRAM_CHANNELS")
    if tg_channels:
        try:
            try:
                from telegram_scraper import fetch_telegram_channel
            except Exception:
                from voiceguard_ai.nlp.scrapers.telegram_scraper import fetch_telegram_channel
            channels = [c.strip() for c in tg_channels.split(",") if c.strip()]
            for ch in channels:
                fut = executor.submit(fetch_telegram_channel, ch, 10)
                futures_map[fut] = ("telegram", ch)
        except Exception:
            pass

    # arXiv (papers)
    try:
        try:
            from arxiv_scraper import fetch_arxiv
        except Exception:
            from voiceguard_ai.nlp.scrapers.arxiv_scraper import fetch_arxiv
        fut = executor.submit(fetch_arxiv, KEYWORDS, 10)
        futures_map[fut] = ("arxiv", None)
    except Exception:
        pass

    # Collect results as they finish
    for fut in as_completed(list(futures_map.keys())):
        source_type, meta = futures_map.get(fut, (None, None))
        try:
            data = fut.result()
        except Exception:
            continue

        if source_type == "rss":
            feed_results = data or {}
            for url, entries in feed_results.items():
                for e in entries:
                    item = {
                        "source": "rss",
                        "id": e.get("id") or e.get("link"),
                        "title": e.get("title"),
                        "summary": e.get("summary"),
                        "url": e.get("link"),
                        "published": e.get("published"),
                        "collected_at": time.time(),
                    }
                    if item["id"] not in seen:
                        results.append(item)
                        seen.add(item["id"])

        elif source_type == "reliefweb":
            reports = data or []
            for r in reports:
                item = {
                    "source": "reliefweb",
                    "id": r.get("id"),
                    "title": r.get("title"),
                    "summary": r.get("summary"),
                    "url": r.get("url"),
                    "published": r.get("date"),
                    "collected_at": time.time(),
                }
                if item["id"] and item["id"] not in seen:
                    results.append(item)
                    seen.add(item["id"])

        elif source_type == "telegram":
            posts = data or []
            for p in posts:
                item = {
                    "source": "telegram",
                    "id": p.get("id"),
                    "title": (p.get("text") or "")[:200],
                    "summary": p.get("text"),
                    "url": p.get("url"),
                    "published": p.get("date"),
                    "collected_at": time.time(),
                }
                if item["id"] and item["id"] not in seen:
                    results.append(item)
                    seen.add(item["id"])

        elif source_type == "arxiv":
            papers = data or []
            for p in papers:
                item = {
                    "source": "arxiv",
                    "id": p.get("id"),
                    "title": p.get("title"),
                    "summary": p.get("summary"),
                    "url": p.get("link"),
                    "published": p.get("published"),
                    "collected_at": time.time(),
                }
                if item["id"] and item["id"] not in seen:
                    results.append(item)
                    seen.add(item["id"])

    executor.shutdown(wait=False)
    try:
        papers = fetch_arxiv(KEYWORDS.replace(" OR ", " OR "), max_results=10)
        for p in papers:
            item = {
                "source": "arxiv",
                "id": p.get("id"),
                "title": p.get("title"),
                "summary": p.get("summary"),
                "url": p.get("link"),
                "published": p.get("published"),
                "collected_at": time.time(),
            }
            if item["id"] and item["id"] not in seen:
                results.append(item)
                seen.add(item["id"])
    except Exception:
        pass

    # persist results
    if results:
        _append_items(OUT_PATH, results)

    return {"collected": len(results), "output": OUT_PATH}


if __name__ == "__main__":
    r = run_once()
    print(r)
