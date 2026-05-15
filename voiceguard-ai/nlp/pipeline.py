import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import feedparser
import spacy

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    try:
        # Attempt to download the small English model automatically
        import spacy.cli
        print("spaCy model en_core_web_sm not found — downloading now...")
        spacy.cli.download("en_core_web_sm")
        nlp = spacy.load("en_core_web_sm")
    except Exception:
        print("Failed to download/load en_core_web_sm. Run: python -m spacy download en_core_web_sm")
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
    """Classify a single text using HF zero-shot (facebook/bart-large-mnli) with
    a keyword fallback.

    Returns: {disaster_type, confidence, is_disaster, all_scores}
    """
    default = {"disaster_type": "none", "confidence": 0.0, "is_disaster": False, "all_scores": {l: 0.0 for l in DISASTER_LABELS}}
    try:
        if not text:
            return default

        # Lazy load HF pipeline
        try:
            from transformers import pipeline as hf_pipeline
        except Exception:
            hf_pipeline = None

        labels = ["Flood", "Cyclone", "Fire", "Earthquake", "Landslide", "None"]
        txt = text[:1024]

        # allow forcing no HF model for fast dev runs
        if os.getenv("VG_NO_HF") == "1":
            hf_pipeline = None

        if hf_pipeline is not None:
            try:
                zclf = hf_pipeline("zero-shot-classification", model="facebook/bart-large-mnli")
                out = zclf(txt, labels)
                scores = {}
                for lab, score in zip(out.get("labels", []), out.get("scores", [])):
                    scores[lab.lower()] = float(score)
                # pick best non-none
                best_label = out.get("labels", [])[0].lower() if out.get("labels") else "none"
                best_score = out.get("scores", [0.0])[0] if out.get("scores") else 0.0
                if best_label == "none" or float(best_score) < 0.4:
                    return {"disaster_type": "none", "confidence": round(float(best_score), 3), "is_disaster": False, "all_scores": scores}
                return {"disaster_type": best_label, "confidence": round(float(best_score), 3), "is_disaster": True, "all_scores": scores}
            except Exception:
                logger.exception("[NLP] HF zero-shot failed, falling back to keywords")

        # Keyword fallback
        txt_low = txt.lower()
        for k, variants in KEYWORD_LABEL_MAP.items():
            for v in variants:
                if v in txt_low:
                    return {"disaster_type": k, "confidence": 0.6, "is_disaster": True, "all_scores": {k: 0.6}}

        return default
    except Exception:
        logger.exception("classify_disaster failed")
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

    # default to Karnataka when unknown as per system flow
    return "Karnataka"


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
    """Run the full pipeline:

    - Scrape all sources via `scraper.scrape_all()`
    - Classify each post, extract locations, score severity
    - Run triage on posts with images and remove flagged posts
    - Aggregate results and return structured dict
    """
    from .scraper import scrape_all
    try:
        # Pre-warm heavy models so classification doesn't block later
        # Allow skipping prewarm in dev via env var VG_SKIP_PREWARM=1
        if os.getenv("VG_SKIP_PREWARM") != "1":
            _state.prewarm()
    except Exception:
        pass

    try:
        posts = scrape_all()
    except Exception:
        logger.exception("[NLP] scrape_all failed")
        posts = []

    # include voice query as a synthetic post if provided
    if voice_query:
        posts.append(
            {
                "id": f"voice_{int(datetime.now(timezone.utc).timestamp())}",
                "text": voice_query,
                "source": "voice",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    # Deduplicate by id/title/url
    posts = _dedupe(posts)

    # Attempt to lazy-load triage runner
    try:
        try:
            from triage_pipeline import run_pipeline as run_triage
        except Exception:
            from voiceguard_ai.nlp.triage_pipeline import run_pipeline as run_triage
    except Exception:
        run_triage = None

    included_posts = []
    flagged_count = 0
    disaster_counter = {}
    locations_set = set()
    sources_set = set()
    highest_severity_level = "LOW"
    severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}

    for p in posts:
        try:
            text = (p.get("text") or "").strip()
            if not text:
                continue

            # classify
            cls = classify_disaster(text)
            d_type = cls.get("disaster_type", "none")

            # location
            loc_struct = extract_location(text)
            primary_loc = loc_struct.get("primary_location") or loc_struct.get("canonical_names", ["Unknown"])[0]

            # severity
            sev_struct = score_severity(text)
            sev_level = sev_struct.get("level", "LOW")

            # triage images if available
            if p.get("image_url") and run_triage:
                try:
                    tri = run_triage(p.get("image_url"))
                    if tri.get("verdict") != "VERIFIED_REAL":
                        flagged_count += 1
                        # save flagged in memory store
                        try:
                            from backend.memory_store import save_flagged
                        except Exception:
                            save_flagged = None
                        try:
                            if save_flagged:
                                save_flagged(p, tri.get("reasoning") or tri.get("reason") or "triage_flagged")
                        except Exception:
                            logger.exception("[NLP] failed to save flagged post")
                        continue
                except Exception:
                    logger.exception("[NLP] triage failed for image")

            included_posts.append(p)

            # aggregates
            disaster_counter[d_type] = disaster_counter.get(d_type, 0) + 1
            locations_set.add(primary_loc)
            sources_set.add(p.get("source", "unknown"))
            # highest severity
            if severity_rank.get(sev_level, 0) > severity_rank.get(highest_severity_level, 0):
                highest_severity_level = sev_level

        except Exception:
            logger.exception("[NLP] Post processing failed")

    # Determine overall disaster type (most common)
    if disaster_counter:
        overall_type = max(disaster_counter, key=disaster_counter.get)
    else:
        overall_type = "none"

    highest_location = None
    # choose a representative location from included posts with highest severity
    try:
        if included_posts:
            # find post with highest severity
            def _post_sev(p):
                try:
                    return severity_rank.get(score_severity(p.get("text",""))['level'], 0)
                except Exception:
                    return 0

            top = max(included_posts, key=_post_sev)
            top_loc = extract_location(top.get("text", ""))
            highest_location = top_loc.get("primary_location")
    except Exception:
        highest_location = None

    posts_analyzed = len(included_posts)
    posts_flagged = flagged_count
    advice = _build_advice(highest_severity_level)
    # Build sources breakdown
    source_counts = {"gdacs": 0, "reliefweb": 0, "bluesky": 0, "rss": 0, "simulated": 0, "voice": 0, "other": 0}
    for p in included_posts:
        s = (p.get("source") or "").lower()
        if s.startswith("gdacs") or s == "gdacs":
            source_counts["gdacs"] += 1
        elif s.startswith("reliefweb") or s == "reliefweb":
            source_counts["reliefweb"] += 1
        elif s.startswith("bluesky") or s == "bluesky":
            source_counts["bluesky"] += 1
        elif s.startswith("rss") or s == "rss":
            source_counts["rss"] += 1
        elif s == "simulated":
            source_counts["simulated"] += 1
        elif s == "voice":
            source_counts["voice"] += 1
        else:
            source_counts["other"] += 1

    result = {
        "disaster_type": overall_type,
        "location": highest_location or (list(locations_set)[0] if locations_set else "Karnataka"),
        "severity": highest_severity_level,
        "advice": advice,
        "posts_analyzed": posts_analyzed,
        "posts_flagged": posts_flagged,
        "sources": source_counts,
        "all_locations": list(locations_set),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
    }

    # Send SMS for MEDIUM/HIGH (include posts_analyzed and disaster_type when available)
    try:
        if result.get("severity") in {"MEDIUM", "HIGH"}:
            try:
                send_sms_alert(
                    result.get("severity"),
                    result.get("location"),
                    result.get("advice"),
                    int(result.get("posts_analyzed", 0)),
                    result.get("disaster_type", "Unknown"),
                )
            except Exception:
                logger.exception("[NLP] send_sms_alert failed")
    except Exception:
        logger.exception("[NLP] send_sms_alert wrapper failed")

    return result
