import logging
import os
import re
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Dict, List

logger = logging.getLogger("voiceguard")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(val: str) -> str:
    try:
        if isinstance(val, (int, float)):
            return datetime.fromtimestamp(float(val), tz=timezone.utc).isoformat()
        if isinstance(val, datetime):
            return val.astimezone(timezone.utc).isoformat()
        # try RFC822 / common formats
        from email.utils import parsedate_to_datetime

        try:
            dt = parsedate_to_datetime(val)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            return datetime.fromisoformat(val).astimezone(timezone.utc).isoformat()
    except Exception:
        return _now_utc().isoformat()


def _severity_from_keywords(text: str) -> (str, int):
    t = (text or "").lower()
    high = ["deaths", "stranded", "evacuate", "emergency", "sos", "collapse", "fatal"]
    med = ["flooding", "damaged", "displaced", "warning", "alert", "blocked", "flood"]
    low = ["advisory", "monitoring", "preparedness", "prepared"]
    for kw in high:
        if kw in t:
            return "HIGH", 90
    for kw in med:
        if kw in t:
            return "MEDIUM", 60
    for kw in low:
        if kw in t:
            return "LOW", 30
    return "LOW", 10


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
                    txt_low = text.lower()
                    if not any(k in txt_low for k in keywords):
                        continue

                    image_url = None
                    media = entry.get("media_content") or entry.get("media") or entry.get("enclosures")
                    if media and isinstance(media, (list, tuple)) and media:
                        first = media[0]
                        if isinstance(first, dict):
                            image_url = first.get("url")

                    items.append({
                        "id": "rss_" + hashlib.md5((link or title).encode("utf-8")).hexdigest(),
                        "title": title,
                        "text": text,
                        "url": link,
                        "image_url": image_url,
                        "source": "rss",
                        "source_name": parsed.feed.get("title", "rss"),
                        "timestamp": ts,
                        "score": 10,
                        "disaster_hint": None,
                    })
                except Exception:
                    logger.exception("[SCRAPER] Error parsing RSS entry")
        except Exception:
            logger.exception("[SCRAPER] RSS fetch failed: %s", url)

    logger.info("[SCRAPER] RSS fetched %d items", len(items))
    return items


def scrape_gdacs() -> List[Dict]:
    """Scrape GDACS RSS feed and return unified posts list."""
    try:
        try:
            import feedparser
        except Exception:
            logger.warning("[SCRAPER] feedparser not installed; skipping GDACS")
            return []

        url = "https://www.gdacs.org/xml/rss.xml"
        parsed = feedparser.parse(url)
        items: List[Dict] = []
        keywords_country = ["india", "karnataka", "kerala", "mangalore", "udupi", "coastal"]

        for entry in parsed.entries[:200]:
            try:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                link = entry.get("link", "")
                published = entry.get("published", entry.get("updated", ""))
                ts = _parse_timestamp(published) if published else _now_utc().isoformat()
                text = (title + " " + summary).strip()
                low = text.lower()
                if not any(k in low for k in keywords_country) and "india" not in low:
                    continue

                ev = None
                for code, mapped in [("FL", "Flood"), ("TC", "Cyclone"), ("EQ", "Earthquake"), ("WF", "Fire"), ("DR", "Landslide")]:
                    if code.lower() in low or mapped.lower() in low:
                        ev = mapped
                        break

                sev = "LOW"
                if "red" in low:
                    sev = "HIGH"
                elif "orange" in low:
                    sev = "MEDIUM"

                score = 90 if sev == "HIGH" else 60 if sev == "MEDIUM" else 30

                pid = "gdacs_" + hashlib.md5((link or title).encode("utf-8")).hexdigest()
                items.append({
                    "id": pid,
                    "title": title[:200],
                    "text": text,
                    "url": link,
                    "image_url": None,
                    "source": "gdacs",
                    "timestamp": ts,
                    "score": score,
                    "disaster_hint": ev,
                    "gdacs_severity": sev,
                })
            except Exception:
                logger.exception("[SCRAPER] Error parsing GDACS entry")

        logger.info("[SCRAPER] GDACS fetched %d items", len(items))
        return items
    except Exception:
        logger.exception("[SCRAPER] scrape_gdacs failed")
        return []


def scrape_reliefweb() -> List[Dict]:
    """Use ReliefWeb API to fetch disasters and reports for India."""
    try:
        import requests
        from html import unescape
        import re as _re

        base = "https://api.reliefweb.int/v1"
        results: List[Dict] = []

        # Disasters endpoint
        try:
            url = f"{base}/disasters"
            params = {
                "appname": "voiceguardai",
                "filter[operator]": "AND",
                "filter[conditions][0][field]": "country.iso3",
                "filter[conditions][0][value]": "IND",
                "filter[conditions][1][field]": "status",
                "filter[conditions][1][value]": "ongoing",
                "fields[include][]": ["name", "glide", "date", "type", "status"],
                "sort[]": "date:desc",
                "limit": 10,
            }
            r = requests.get(url, params=params, timeout=10)
            if r.status_code != 200:
                logger.warning("[SCRAPER] ReliefWeb disasters endpoint returned %s", r.status_code)
            else:
                data = r.json().get("data", [])
                for item in data:
                    try:
                        f = item.get("fields", {})
                        title = f.get("name") or ""
                        dtype = None
                        tarr = f.get("type") or []
                        if isinstance(tarr, list) and tarr:
                            dtype = tarr[0].get("name") if isinstance(tarr[0], dict) else tarr[0]
                        date = f.get("date", {}).get("created") if isinstance(f.get("date"), dict) else f.get("date")
                        ts = _parse_timestamp(date) if date else _now_utc().isoformat()
                        sev, score = _severity_from_keywords(title)
                        pid = "reliefweb_" + hashlib.md5((title + (ts or "")).encode("utf-8")).hexdigest()
                        results.append({
                            "id": pid,
                            "title": title,
                            "text": title,
                            "url": item.get("href") or "",
                            "image_url": None,
                            "source": "reliefweb",
                            "timestamp": ts,
                            "score": score,
                            "disaster_hint": dtype,
                        })
                    except Exception:
                        logger.exception("[SCRAPER] Error parsing ReliefWeb disaster item")
        except Exception:
            logger.exception("[SCRAPER] ReliefWeb disasters fetch failed")

        # Reports endpoint
        try:
            url = f"{base}/reports"
            params = {
                "appname": "voiceguardai",
                "filter[operator]": "AND",
                "filter[conditions][0][field]": "country.iso3",
                "filter[conditions][0][value]": "IND",
                "filter[conditions][1][field]": "theme.name",
                "filter[conditions][1][value]": "Disaster Management",
                "fields[include][]": ["title", "body-html", "date", "source", "url"],
                "sort[]": "date:desc",
                "limit": 10,
            }
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200:
                data = r.json().get("data", [])
                for item in data:
                    try:
                        f = item.get("fields", {})
                        title = f.get("title") or ""
                        body = f.get("body-html") or ""
                        # strip basic html tags
                        text = _re.sub(r"<[^>]+>", "", body)
                        text = unescape(text)
                        date = f.get("date", {}).get("created") if isinstance(f.get("date"), dict) else f.get("date")
                        ts = _parse_timestamp(date) if date else _now_utc().isoformat()
                        src = (f.get("source") or [])
                        source_name = src[0].get("name") if isinstance(src, list) and src and isinstance(src[0], dict) else (src or "reliefweb")
                        sev, score = _severity_from_keywords(title + " " + text)
                        pid = "reliefwebr_" + hashlib.md5((title + (ts or "")).encode("utf-8")).hexdigest()
                        results.append({
                            "id": pid,
                            "title": title,
                            "text": (title + " " + text).strip(),
                            "url": (f.get("url") or ""),
                            "image_url": None,
                            "source": "reliefweb",
                            "source_name": source_name,
                            "timestamp": ts,
                            "score": score,
                            "disaster_hint": None,
                        })
                    except Exception:
                        logger.exception("[SCRAPER] Error parsing ReliefWeb report item")
            else:
                logger.warning("[SCRAPER] ReliefWeb reports endpoint returned %s", r.status_code)
        except Exception:
            logger.exception("[SCRAPER] ReliefWeb reports fetch failed")

        logger.info("[SCRAPER] ReliefWeb fetched %d items", len(results))
        return results
    except Exception:
        logger.exception("[SCRAPER] scrape_reliefweb failed")
        return []


def scrape_bluesky() -> List[Dict]:
    """Fetch recent Bluesky posts matching disaster keywords. Uses atproto when available,
    otherwise falls back to public search XRPC endpoint."""
    try:
        import requests
        queries = [
            "flood Karnataka",
            "cyclone India",
            "disaster Mangalore",
            "flood Udupi",
            "earthquake India",
            "disaster relief India",
        ]
        keywords = set([k.lower() for k in [
            "flood", "cyclone", "earthquake", "disaster", "emergency", "evacuate", "rescue", "sos",
            "mangalore", "udupi", "karnataka", "kerala",
        ]])
        out: List[Dict] = []

        # try atproto client if installed
        try:
            from atproto import Client
            handle = os.getenv("BLUESKY_HANDLE")
            pwd = os.getenv("BLUESKY_PASSWORD")
            client = Client()
            # If credentials are not provided, skip the atproto client and use the public API fallback.
            if not handle or not pwd:
                raise Exception("No Bluesky credentials; skip atproto client")

            try:
                client.login(handle, pwd)
            except Exception:
                logger.info("[SCRAPER] Bluesky login failed; continuing with public API")

            for q in queries:
                try:
                    # atproto client expects a Params-like mapping, not a plain string.
                    # Pass a dict with `query` and `limit` to satisfy the client model.
                    # atproto client expects parameter name 'q' for the query
                    params = {"q": q, "limit": 25}
                    resp = client.app.bsky.feed.search_posts(params)
                    posts = getattr(resp, "posts", []) or (resp.get("posts") if isinstance(resp, dict) else [])
                    for p in posts:
                        try:
                            post = p.get("post") if isinstance(p, dict) and "post" in p else p
                            text = post.get("text") or post.get("content") or ""
                            if not any(k in (text or "").lower() for k in keywords):
                                continue
                            created = post.get("createdAt") or post.get("created_at")
                            ts = _parse_timestamp(created) if created else _now_utc().isoformat()
                            pid = "bluesky_" + hashlib.md5((post.get("uri") or text).encode("utf-8")).hexdigest()
                            image_url = None
                            embeds = post.get("embed") or {}
                            if isinstance(embeds, dict):
                                imgs = embeds.get("images") or embeds.get("images")
                                if imgs and isinstance(imgs, list):
                                    image_url = imgs[0].get("url") if isinstance(imgs[0], dict) else None
                            score = (post.get("likeCount", 0) or 0) + (post.get("repostCount", 0) or 0)
                            out.append({
                                "id": pid,
                                "title": (text[:100] if text else "Bluesky post"),
                                "text": text,
                                "url": post.get("uri") or "",
                                "image_url": image_url,
                                "source": "bluesky",
                                "timestamp": ts,
                                "score": min(100, int(score)),
                                "disaster_hint": None,
                            })
                        except Exception:
                            logger.exception("[SCRAPER] Error parsing Bluesky post (client)")
                except Exception:
                    logger.exception("[SCRAPER] Bluesky client search failed for %s", q)
        except Exception:
            # fallback to public API
            public = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
            for q in queries:
                try:
                    r = requests.get(public, params={"q": q, "limit": 25}, timeout=8)
                    if r.status_code != 200:
                        continue
                    data = r.json()
                    posts = data.get("posts") or data.get("data") or []
                    for p in posts:
                        try:
                            post = p.get("post") if isinstance(p, dict) and "post" in p else p
                            text = post.get("text") or post.get("record", {}).get("text") if isinstance(post, dict) else ""
                            if not any(k in (text or "").lower() for k in keywords):
                                continue
                            created = post.get("createdAt") or post.get("created_at") or (post.get("record") or {}).get("createdAt")
                            ts = _parse_timestamp(created) if created else _now_utc().isoformat()
                            pid = "bluesky_" + hashlib.md5((post.get("uri") or text).encode("utf-8")).hexdigest()
                            image_url = None
                            rec = post.get("record") if isinstance(post, dict) else {}
                            embed = rec.get("embed") if isinstance(rec, dict) else None
                            if embed and isinstance(embed, dict):
                                imgs = embed.get("images") or []
                                if imgs:
                                    image_url = imgs[0].get("image") if isinstance(imgs[0], dict) else None
                            score = 0
                            out.append({
                                "id": pid,
                                "title": (text[:100] if text else "Bluesky post"),
                                "text": text,
                                "url": post.get("uri") or "",
                                "image_url": image_url,
                                "source": "bluesky",
                                "timestamp": ts,
                                "score": min(100, int(score)),
                                "disaster_hint": None,
                            })
                        except Exception:
                            logger.exception("[SCRAPER] Error parsing Bluesky post (public)")
                except Exception:
                    logger.exception("[SCRAPER] Bluesky public API search failed for %s", q)

        logger.info("[SCRAPER] Bluesky fetched %d posts", len(out))
        # filter last 24 hours
        cutoff = _now_utc() - timedelta(hours=24)
        recent = []
        for p in out:
            try:
                dt = datetime.fromisoformat(p.get("timestamp")) if isinstance(p.get("timestamp"), str) else _now_utc()
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= cutoff:
                    recent.append(p)
            except Exception:
                recent.append(p)
        return recent
    except Exception:
        logger.exception("[SCRAPER] scrape_bluesky failed")
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

        # GDACS
        try:
            gd = scrape_gdacs()
            posts.extend(gd)
        except Exception:
            logger.exception("[SCRAPER] GDACS failed, skip")

        # ReliefWeb
        try:
            rw = scrape_reliefweb()
            posts.extend(rw)
        except Exception:
            logger.exception("[SCRAPER] ReliefWeb failed, skip")

        # Bluesky
        try:
            bs = scrape_bluesky()
            posts.extend(bs)
        except Exception:
            logger.exception("[SCRAPER] Bluesky failed, skip")

        # RSS (keep existing)
        try:
            posts.extend(scrape_rss())
        except Exception:
            logger.exception("[SCRAPER] rss failed, skip")

        # Always include simulated posts as safety net
        try:
            posts.extend(load_simulated())
        except Exception:
            logger.exception("[SCRAPER] simulated load failed")

        merged = merge_and_deduplicate(posts)
        # counts for logging
        def _count_src(tag: str):
            return sum(1 for p in posts if p.get("source") == tag)

        logger.info("[SCRAPER] Total posts collected: %d | GDACS: %d | ReliefWeb: %d | Bluesky: %d | RSS: %d | Simulated: %d",
                    len(merged), _count_src("gdacs"), _count_src("reliefweb"), _count_src("bluesky"), _count_src("rss"), _count_src("simulated"))
        return merged
    except Exception:
        logger.exception("[SCRAPER] scrape_all failed; returning simulated only")
        return load_simulated()


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
