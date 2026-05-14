import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import feedparser
import praw
import spacy

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    print("Run: python -m spacy download en_core_web_sm")
    nlp = None

from backend.sms import send_sms_alert

logger = logging.getLogger("voiceguard")

DISASTER_LABELS = [
    "flood",
    "cyclone",
    "earthquake",
    "landslide",
    "wildfire",
    "storm",
    "tsunami",
    "not a disaster",
]

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

COASTAL_KARNATAKA_LOCATIONS = {
    "mangalore":        "Mangalore, Dakshina Kannada",
    "udupi":            "Udupi",
    "dakshina kannada": "Dakshina Kannada",
    "kundapur":         "Kundapur, Udupi",
    "manipal":          "Manipal, Udupi",
    "karwar":           "Karwar, Uttara Kannada",
    "uttara kannada":   "Uttara Kannada",
    "coastal karnataka":"Coastal Karnataka",
    "karnataka":        "Karnataka",
    "kerala":           "Kerala",
    "india":            "India",
}

ADVICE_BY_SEVERITY = {
    "HIGH": "Seek immediate safety and follow official evacuation guidance.",
    "MEDIUM": "Avoid travel in affected zones and monitor official updates.",
    "LOW": "Stay alert and keep an emergency kit ready.",
}

# Severity keyword sets (module-level constants)
HIGH_KEYWORDS = [
    "sos", "evacuate", "evacuation", "stranded", "rescue",
    "trapped", "collapse", "collapsed", "critical", "emergency",
    "mayday", "helpme", "deaths", "killed", "missing persons",
    "immediate danger", "life threatening", "need help urgently",
]

MEDIUM_KEYWORDS = [
    "waterlogging", "water logging", "road blocked", "blocked road",
    "flooded", "flooding", "overflowing", "overflow", "submerged",
    "cyclone", "landslide", "warning issued", "red alert",
    "orange alert", "affected", "damaged", "disrupted",
    "power outage", "bridge closed", "highway closed",
]

LOW_KEYWORDS = [
    "light rain", "drizzle", "slight rain", "advisory",
    "yellow alert", "watch", "caution", "forecast",
    "possibility of rain", "cloudy", "moderate rain",
    "weather update", "IMD alert", "be prepared",
]


def score_severity(text: str) -> dict:
    """Score severity by keyword matching.

    Returns a dict with keys: level, score, color, matched_keywords,
    should_alert, action. Always returns all keys.
    """
    default = {
        "level": "NONE",
        "score": 0,
        "color": "green",
        "matched_keywords": [],
        "should_alert": False,
        "action": "No action required. Continue monitoring.",
    }

    try:
        if not text or len(text.strip()) < 3:
            return default

        txt = text.lower()

        # helper: check presence of keyword allowing simple plural forms
        def contains_keyword(hay: str, needle: str) -> bool:
            if needle in hay:
                return True
            # token-aware fallback: match keyword word sequence allowing simple plural
            hay_tokens = re.findall(r"\w+", hay)
            needle_tokens = re.findall(r"\w+", needle)
            if not needle_tokens:
                return False
            for i in range(0, len(hay_tokens) - len(needle_tokens) + 1):
                ok = True
                for j, kt in enumerate(needle_tokens):
                    t = hay_tokens[i + j]
                    if t == kt:
                        continue
                    # allow simple plural match (roads <-> road)
                    if t.endswith("s") and t[:-1] == kt:
                        continue
                    if kt.endswith("s") and kt[:-1] == t:
                        continue
                    ok = False
                    break
                if ok:
                    return True
            return False

        # Check HIGH
        high_matches: List[str] = []
        for kw in HIGH_KEYWORDS:
            if contains_keyword(txt, kw):
                if kw not in high_matches:
                    high_matches.append(kw)
        if high_matches:
            return {
                "level": "HIGH",
                "score": 3,
                "color": "red",
                "matched_keywords": high_matches,
                "should_alert": True,
                "action": "Trigger immediate SMS alert and voice broadcast. Notify NDRF.",
            }

        # Check MEDIUM
        med_matches: List[str] = []
        for kw in MEDIUM_KEYWORDS:
            if contains_keyword(txt, kw):
                if kw not in med_matches:
                    med_matches.append(kw)
        if med_matches:
            return {
                "level": "MEDIUM",
                "score": 2,
                "color": "orange",
                "matched_keywords": med_matches,
                "should_alert": True,
                "action": "Send SMS warning to registered users. Update dashboard.",
            }

        # Check LOW
        low_matches: List[str] = []
        for kw in LOW_KEYWORDS:
            if contains_keyword(txt, kw):
                if kw not in low_matches:
                    low_matches.append(kw)
        if low_matches:
            return {
                "level": "LOW",
                "score": 1,
                "color": "yellow",
                "matched_keywords": low_matches,
                "should_alert": False,
                "action": "Log advisory. Monitor for escalation.",
            }

        return default
    except Exception:
        logger.exception("score_severity error")
        return default

# Simple keyword -> label map (lowercase keys)
KEYWORD_LABEL_MAP = {
    "flood": ["flood", "flooding", "flash flood", "inundat", "river overflow"],
    "cyclone": ["cyclone", "storm", "landfall", "windstorm", "cyclonic"],
    "earthquake": ["earthquake", "tremor", "aftershock", "seismic"],
    "landslide": ["landslide", "mudslide", "slope failure"],
    "wildfire": ["fire", "wildfire", "blaze", "burning"],
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
            try:
                # Lazy import to avoid heavy dependency at module import time
                from sentence_transformers import CrossEncoder

                self._classifier = CrossEncoder("cross-encoder/nli-deberta-v3-large")
            except Exception:
                logger.exception("Failed to load CrossEncoder model")
                self._classifier = None
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


def classify_disaster(text: str) -> Dict[str, Any]:
    """Classify a single text using CrossEncoder NLI model.

    Returns a dict with keys: disaster_type, confidence, is_disaster, all_scores.
    """
    default = {"disaster_type": "none", "confidence": 0.0, "is_disaster": False, "all_scores": {l: 0.0 for l in DISASTER_LABELS}}
    try:
        if not text:
            return default

        txt = text[:512]
        pairs = [[txt, f"This text is about a {label}."] for label in DISASTER_LABELS]
        clf = _state.classifier()
        if clf is None:
            return default

        preds = clf.predict(pairs)
        scores = {}
        for label, arr in zip(DISASTER_LABELS, preds):
            try:
                entail = float(arr[1])
            except Exception:
                # fallback to last index if unexpected
                entail = float(arr[-1]) if len(arr) > 0 else 0.0
            scores[label] = float(entail)

        top_label = max(scores, key=scores.get)
        top_score = scores[top_label]
        is_dis = (top_label != "not a disaster") and (top_score > 0.5)
        return {"disaster_type": top_label if is_dis else "none", "confidence": round(top_score, 3), "is_disaster": bool(is_dis), "all_scores": scores}
    except Exception:
        logger.exception("CrossEncoder classification failed")
        return default


def _classify_disaster(texts: List[str]) -> str:
    """Compatibility wrapper: accepts list of texts and returns top label string (or 'none')."""
    joined = " ".join(texts)
    res = classify_disaster(joined)
    return res.get("disaster_type", "none")


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


def extract_location(text: str) -> dict:
    """Extract locations using spaCy NER and map to target regions.

    Returns a dict with keys (always present):
      - locations_found: list of raw entity strings spaCy found
      - matched_targets: list of matched keys from COASTAL_KARNATAKA_LOCATIONS
      - canonical_names: list of mapped canonical names
      - is_target_region: bool
      - primary_location: first canonical name or 'Unknown region'

    Edge cases:
      - If `nlp` is None or text too short -> return empty-like result with is_target_region False
      - spaCy errors are caught and logged
    """
    default = {
        "locations_found": [],
        "matched_targets": [],
        "canonical_names": [],
        "is_target_region": False,
        "primary_location": "Unknown region",
    }

    if nlp is None:
        return default

    if not text or len(text.strip()) < 3:
        return default

    try:
        doc = nlp(text)
    except Exception:
        logger.exception("spaCy NER failed")
        return default

    raw_entities: List[str] = []
    for ent in doc.ents:
        if ent.label_ in {"GPE", "LOC"}:
            ent_text = ent.text.strip()
            if ent_text:
                raw_entities.append(ent_text)

    # Deduplicate preserving order (case-insensitive)
    deduped: List[str] = []
    seen = set()
    for e in raw_entities:
        key = e.strip().lower()
        if key not in seen:
            seen.add(key)
            deduped.append(e.strip())

    matched_targets: List[str] = []
    canonical_names: List[str] = []
    seen_matched = set()
    for e in deduped:
        e_clean = e.lower()
        for k, v in COASTAL_KARNATAKA_LOCATIONS.items():
            if k in e_clean:
                if k not in seen_matched:
                    seen_matched.add(k)
                    matched_targets.append(k)
                    canonical_names.append(v)

    is_target = len(matched_targets) > 0
    primary = canonical_names[0] if canonical_names else "Unknown region"

    return {
        "locations_found": deduped,
        "matched_targets": matched_targets,
        "canonical_names": canonical_names,
        "is_target_region": is_target,
        "primary_location": primary,
    }


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
