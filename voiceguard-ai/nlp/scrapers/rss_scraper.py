from typing import List, Dict
import feedparser
from concurrent.futures import ThreadPoolExecutor, as_completed


def _parse_one(url: str, limit_per_feed: int, timeout: int):
    feed = feedparser.parse(url, request_timeout=timeout)
    entries = []
    for e in feed.entries[:limit_per_feed]:
        entries.append(
            {
                "id": e.get("id") or e.get("link"),
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "published": e.get("published", e.get("updated", None)),
                "summary": e.get("summary", ""),
            }
        )
    return url, entries


def fetch_feeds(feed_urls: List[str], limit_per_feed: int = 10, timeout: int = 7) -> Dict[str, List[Dict]]:
    """Fetch and parse multiple RSS/Atom feeds concurrently.

    Returns a mapping of feed_url -> list of entries with title, link, published, summary.
    """
    out: Dict[str, List[Dict]] = {}
    if not feed_urls:
        return out

    max_workers = min(8, len(feed_urls))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_parse_one, url, limit_per_feed, timeout): url for url in feed_urls}
        for fut in as_completed(futures):
            try:
                url, entries = fut.result()
                out[url] = entries
            except Exception:
                out[futures[fut]] = []
    return out
