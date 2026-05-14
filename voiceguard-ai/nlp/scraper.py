import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List

logger = logging.getLogger("voiceguard")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(val: str) -> str:
    try:
        # feedparser/praw give many formats; try to normalize
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(float(val), tz=timezone.utc).isoformat()
        if isinstance(val, datetime):
            return val.astimezone(timezone.utc).isoformat()
        # try common parse
        return datetime.fromisoformat(val).astimezone(timezone.utc).isoformat()
    except Exception:
        return _now_utc().isoformat()


def scrape_reddit() -> List[Dict]:
    """Scrape Reddit using PRAW. Returns list of unified post dicts."""
    try:
        try:
            import praw
        except Exception:
            logger.warning("[SCRAPER] praw not installed; skipping reddit")
            return []

        client_id = os.getenv("REDDIT_CLIENT_ID")
        client_secret = os.getenv("REDDIT_CLIENT_SECRET")
        user_agent = os.getenv("REDDIT_USER_AGENT")
        if not client_id or not client_secret or not user_agent:
            logger.warning("[SCRAPER] Reddit credentials missing; skipping reddit")
            return []

        reddit = praw.Reddit(client_id=client_id, client_secret=client_secret, user_agent=user_agent)
        subreddits = ["india", "weather", "Kerala", "karnataka", "Mangalore", "indianews"]
        posts: List[Dict] = []
        cutoff = _now_utc() - timedelta(hours=24)

        for sub in subreddits:
            try:
                for submission in reddit.subreddit(sub).new(limit=50):
                    try:
                        ts = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
                        if ts < cutoff:
                            continue
                        url = getattr(submission, "url", "") or ""
                        image_url = None
                        if re.search(r"\.(jpg|jpeg|png)$", url, re.IGNORECASE):
                            image_url = url

                        posts.append(
                            {
                                "id": f"reddit_{submission.id}",
                                "title": submission.title,
                                "text": submission.title + " " + (submission.selftext or ""),
                                "url": url,
                                "image_url": image_url,
                                "source": "reddit",
                                "subreddit": sub,
                                "timestamp": ts.isoformat(),
                                "score": getattr(submission, "score", 0),
                                "num_comments": getattr(submission, "num_comments", 0),
                            }
                        )
                    except Exception:
                        logger.exception("[SCRAPER] Error parsing reddit submission")
            except Exception:
                logger.exception("[SCRAPER] Reddit scrape failed for %s", sub)

        logger.info("[SCRAPER] Reddit fetched %d posts", len(posts))
        return posts
    except Exception:
        logger.exception("[SCRAPER] scrape_reddit failed")
        return []


def scrape_rss() -> List[Dict]:
    """Scrape configured RSS feeds and filter by disaster keywords."""
    try:
        import feedparser
    except Exception:
        logger.warning("[SCRAPER] feedparser not installed; skipping RSS")
        return []

    feeds = [
        "https://feeds.feedburner.com/ndtvnews-india-news",
        "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
        "https://www.thehindu.com/news/national/feeder/default.rss",
        "https://www.deccanherald.com/rss-feeds/national.rss",
    ]

    keywords = set([k.lower() for k in [
        "flood", "cyclone", "disaster", "earthquake", "landslide",
        "storm", "rescue", "evacuate", "emergency", "warning",
        "mangalore", "udupi", "karnataka", "kerala", "coastal",
    ]])

    items: List[Dict] = []
    cutoff = _now_utc() - timedelta(hours=48)
    for url in feeds:
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries[:50]:
                try:
                    title = entry.get("title", "")
                    summary = entry.get("summary", "")
                    link = entry.get("link", "")
                    published = entry.get("published", entry.get("updated", ""))
                    ts = _parse_timestamp(published) if published else _now_utc().isoformat()
                    text = (title + " " + summary).strip()
                    # keyword filter
                    txt_low = text.lower()
                    if not any(k in txt_low for k in keywords):
                        continue

                    image_url = None
                    media = entry.get("media_content") or entry.get("media") or entry.get("enclosures")
                    if media and isinstance(media, (list, tuple)) and media:
                        first = media[0]
                        if isinstance(first, dict):
                            image_url = first.get("url")

                    items.append(
                        {
                            "id": f"rss_{link}",
                            "title": title,
                            "text": text,
                            "url": link,
                            "image_url": image_url,
                            "source": "rss",
                            "source_name": parsed.feed.get("title", "rss"),
                            "timestamp": ts,
                        }
                    )
                except Exception:
                    logger.exception("[SCRAPER] Error parsing RSS entry")
        except Exception:
            logger.exception("[SCRAPER] RSS fetch failed: %s", url)

    logger.info("[SCRAPER] RSS fetched %d items", len(items))
    return items


def load_simulated() -> List[Dict]:
    try:
        import json

        p = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "simulated_posts.json"))
        with open(p, "r", encoding="utf-8") as fh:
            arr = json.load(fh)
            for it in arr:
                it.setdefault("source", "simulated")
            logger.info("[SCRAPER] Loaded %d simulated posts", len(arr))
            return arr
    except Exception:
        logger.exception("[SCRAPER] Failed to load simulated posts")
        return []


def merge_and_deduplicate(all_posts: List[Dict]) -> List[Dict]:
    seen_urls = set()
    seen_titles = set()
    out: List[Dict] = []
    # Sort by timestamp descending
    def _key(p: Dict):
        try:
            return p.get("timestamp", "")
        except Exception:
            return ""

    for p in sorted(all_posts, key=_key, reverse=True):
        url = (p.get("url") or "").strip()
        title = (p.get("title") or p.get("text") or "").strip().lower()
        key_url = url
        if key_url and key_url in seen_urls:
            continue
        if title:
            # simple title dedupe by first 80 chars
            tkey = title[:80]
            if tkey in seen_titles:
                continue
        if key_url:
            seen_urls.add(key_url)
        if title:
            seen_titles.add(title[:80])
        out.append(p)
    logger.info("[SCRAPER] Merged into %d posts", len(out))
    return out


def scrape_all() -> List[Dict]:
    try:
        posts: List[Dict] = []
        # Try Reddit, RSS; if they fail, simulated will be included
        try:
            posts.extend(scrape_reddit())
        except Exception:
            logger.exception("[SCRAPER] reddit failed")
        try:
            posts.extend(scrape_rss())
        except Exception:
            logger.exception("[SCRAPER] rss failed")
        try:
            posts.extend(load_simulated())
        except Exception:
            logger.exception("[SCRAPER] simulated load failed")

        merged = merge_and_deduplicate(posts)
        return merged
    except Exception:
        logger.exception("[SCRAPER] scrape_all failed")
        return []
