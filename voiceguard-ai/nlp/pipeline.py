import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import feedparser
import praw
import spacy
from transformers import pipeline as hf_pipeline

from backend.sms import send_sms_alert

logger = logging.getLogger("voiceguard")

LABELS = ["Flood", "Cyclone", "Fire", "Earthquake", "Landslide", "None"]

SEVERITY_KEYWORDS = {
    "HIGH": ["sos", "evacuate", "stranded", "trapped", "emergency", "collapse"],
    "MEDIUM": ["waterlogging", "road blocked", "relief", "rescue", "heavy rain"],
    "LOW": ["light rain", "drizzle", "minor", "alert"],
}

LOCATION_KEYWORDS = {
    "Mangalore": ["mangalore", "mangaluru"],
    "Udupi": ["udupi"],
    "Coastal Karnataka": ["coastal karnataka", "dakshina kannada", "udupi district"],
}

ADVICE_BY_SEVERITY = {
    "HIGH": "Seek immediate safety and follow official evacuation guidance.",
    "MEDIUM": "Avoid travel in affected zones and monitor official updates.",
    "LOW": "Stay alert and keep an emergency kit ready.",
}

# Simple keyword -> label map used as a fast fallback before calling the HF model
KEYWORD_LABEL_MAP = {
    "Flood": ["flood", "flooding", "flash flood", "inundat", "river overflow"],
    "Cyclone": ["cyclone", "storm", "landfall", "windstorm", "cyclonic"],
    "Earthquake": ["earthquake", "tremor", "aftershock", "seismic"],
    "Landslide": ["landslide", "mudslide", "slope failure"],
    "Fire": ["fire", "wildfire", "blaze", "burning"],
}


class PipelineState:
    def __init__(self) -> None:
        self._classifier = None
        self._nlp = None

    def prewarm(self) -> None:
        """Preload heavy models to reduce latency later."""
        try:
            _ = self.classifier()
        except Exception:
            # silently ignore model download/load failures here
            pass
        try:
            _ = self.nlp()
        except Exception:
            pass

    def classifier(self):
        if self._classifier is None:
            self._classifier = hf_pipeline("zero-shot-classification", model="facebook/bart-large-mnli")
        return self._classifier

    def nlp(self):
        if self._nlp is None:
            self._nlp = spacy.load("en_core_web_sm")
        return self._nlp


_state = PipelineState()


def _load_simulated_posts() -> List[Dict[str, Any]]:
    data_path = os.path.join(os.path.dirname(__file__), "..", "data", "simulated_posts.json")
    data_path = os.path.abspath(data_path)
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Failed to load simulated posts")
        return []


def _scrape_reddit() -> List[Dict[str, Any]]:
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    user_agent = os.getenv("REDDIT_USER_AGENT")
    if not client_id or not client_secret or not user_agent:
        logger.warning("Reddit credentials missing, skipping Reddit scrape")
        return []

    reddit = praw.Reddit(client_id=client_id, client_secret=client_secret, user_agent=user_agent)
    posts: List[Dict[str, Any]] = []
    subreddits = ["india", "weather", "Kerala"]

    for sub in subreddits:
        try:
            for submission in reddit.subreddit(sub).new(limit=25):
                posts.append(
                    {
                        "id": f"reddit_{submission.id}",
                        "text": submission.title + " " + (submission.selftext or ""),
                        "source": f"reddit/{sub}",
                        "timestamp": datetime.fromtimestamp(submission.created_utc, tz=timezone.utc).isoformat(),
                    }
                )
        except Exception:
            logger.exception("Reddit scrape failed for %s", sub)

    return posts


def _scrape_rss() -> List[Dict[str, Any]]:
    feeds = {
        "ndtv": "https://feeds.feedburner.com/ndtvnews-top-stories",
        "toi": "https://timesofindia.indiatimes.com/rssfeeds/4719161.cms",
        "imd": "https://mausam.imd.gov.in/rss/imd_alerts.xml",
    }

    items: List[Dict[str, Any]] = []
    for name, url in feeds.items():
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries[:25]:
                text = (entry.get("title", "") + " " + entry.get("summary", "")).strip()
                items.append(
                    {
                        "id": f"rss_{name}_{entry.get('id', entry.get('link', ''))}",
                        "text": text,
                        "source": f"rss/{name}",
                        "timestamp": entry.get("published", datetime.now(timezone.utc).isoformat()),
                    }
                )
        except Exception:
            logger.exception("RSS scrape failed for %s", name)

    return items


def _dedupe(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result: List[Dict[str, Any]] = []
    for post in posts:
        key = post.get("id") or post.get("text", "")
        if key in seen:
            continue
        seen.add(key)
        result.append(post)
    return result


def _classify_disaster(texts: List[str]) -> str:
    if not texts:
        return "None"
    # Fast keyword-based classification first
    joined_full = " ".join(texts).lower()
    for label, keywords in KEYWORD_LABEL_MAP.items():
        for kw in keywords:
            if kw in joined_full:
                return label

    # Fallback to model-based zero-shot classification
    try:
        classifier = _state.classifier()
        joined = joined_full[:1500]
        output = classifier(joined, LABELS)
        return output.get("labels", ["None"])[0]
    except Exception:
        logger.exception("Classification failed")
        return "None"


def _extract_location(texts: List[str]) -> str:
    joined = " ".join(texts)
    for location, keywords in LOCATION_KEYWORDS.items():
        for kw in keywords:
            if kw in joined.lower():
                return location

    try:
        doc = _state.nlp()(joined)
        for ent in doc.ents:
            if ent.label_ in {"GPE", "LOC"}:
                for location, keywords in LOCATION_KEYWORDS.items():
                    for kw in keywords:
                        if kw in ent.text.lower():
                            return location
    except Exception:
        logger.exception("NER failed")

    return "Unknown"


def _score_severity(texts: List[str]) -> str:
    joined = " ".join(texts).lower()
    for level in ["HIGH", "MEDIUM", "LOW"]:
        for kw in SEVERITY_KEYWORDS[level]:
            if kw in joined:
                return level
    return "LOW"


def _build_advice(severity: str) -> str:
    return ADVICE_BY_SEVERITY.get(severity, "Stay alert and follow official guidance.")


def run_pipeline(source: str = "auto", voice_query: Optional[str] = None) -> Dict[str, Any]:
    # Pre-warm heavy models so classification doesn't block later
    _state.prewarm()

    posts = []
    posts.extend(_scrape_reddit())
    posts.extend(_scrape_rss())
    posts.extend(_load_simulated_posts())

    if voice_query:
        posts.append(
            {
                "id": f"voice_{int(datetime.now(timezone.utc).timestamp())}",
                "text": voice_query,
                "source": "voice",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    posts = _dedupe(posts)
    texts = [p["text"] for p in posts if p.get("text")]

    disaster_type = _classify_disaster(texts)
    location = _extract_location(texts)
    severity = _score_severity(texts)
    advice = _build_advice(severity)

    if severity in {"MEDIUM", "HIGH"}:
        send_sms_alert(severity, location, advice)

    result = {
        "posts_analyzed": len(texts),
        "disaster_type": disaster_type,
        "location": location,
        "severity": severity,
        "advice": advice,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
    }
    return result
