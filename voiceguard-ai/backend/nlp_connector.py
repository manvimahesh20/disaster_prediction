import asyncio
import json
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger("voiceguard")

HIGH_KEYWORDS = ["sos", "evacuate", "stranded", "trapped", "emergency", "collapse"]


def _load_posts() -> List[Dict[str, Any]]:
    data_path = os.path.join(os.path.dirname(__file__), "..", "data", "simulated_posts.json")
    data_path = os.path.abspath(data_path)
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("[NLP] Failed to load simulated posts")
        return []


def _is_high(text: str) -> bool:
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in HIGH_KEYWORDS)


def _build_mock_result(source: str) -> Dict[str, Any]:
    posts = _load_posts()
    high_posts = [p for p in posts if _is_high(p.get("text", ""))]
    if high_posts:
        selected = random.choice(high_posts)
        logger.info("[NLP] Mock pick: %s", selected.get("id", "unknown"))
    elif posts:
        selected = random.choice(posts)
        logger.info("[NLP] Mock pick fallback: %s", selected.get("id", "unknown"))
    else:
        logger.warning("[NLP] No posts found for mock")

    return {
        "disaster_type": "Flood",
        "location": "Mangalore",
        "severity": "HIGH",
        "advice": "Evacuate low-lying areas immediately. Call NDRF: 011-24363260",
        "posts_analyzed": 7,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
    }


async def run_nlp_check(source: str = "auto", query: str = None) -> Dict[str, Any]:
    """Run the main NLP pipeline (async wrapper).

    This function delegates to `nlp.pipeline.run_pipeline` in a thread so
    it doesn't block the event loop.
    """
    try:
        loop = asyncio.get_event_loop()
        try:
            from nlp.pipeline import run_pipeline
        except Exception:
            try:
                from voiceguard_ai.nlp.pipeline import run_pipeline
            except Exception:
                logger.exception("[NLP] Could not import run_pipeline")
                return {
                    "disaster_type": "None",
                    "location": "Unknown",
                    "severity": "LOW",
                    "advice": "Pipeline not available.",
                    "posts_analyzed": 0,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": source,
                }

        # run in thread
        result = await loop.run_in_executor(None, lambda: run_pipeline(source=source, voice_query=query))
        return result
    except Exception:
        logger.exception("[NLP] run_nlp_check failed")
        return {
            "disaster_type": "None",
            "location": "Unknown",
            "severity": "LOW",
            "advice": "NLP check failed.",
            "posts_analyzed": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
        }


def parse_voice_query(query: str) -> str:
    """Simple intent detection for voice queries.

    Returns one of: what_to_do, which_areas, how_many, how_bad, general
    """
    if not query:
        return "general"
    q = query.lower()
    if any(kw in q for kw in ["what to do", "what should i do", "advice", "how to"]):
        return "what_to_do"
    if any(kw in q for kw in ["which areas", "which areas are", "which places", "where are"]):
        return "which_areas"
    if any(kw in q for kw in ["how many", "how many reports", "count", "reports"]):
        return "how_many"
    if any(kw in q for kw in ["how bad", "severity", "how severe", "danger"]):
        return "how_bad"
    return "general"


def verify_image(image_url: str) -> Dict[str, Any]:
    """Run the triage pipeline for a single image URL and return structured result.

    Returns a dict with keys: verdict, confidence, reasoning, sources_found.
    """
    try:
        try:
            from triage_pipeline import run_pipeline as run_triage
        except Exception:
            from voiceguard_ai.nlp.triage_pipeline import run_pipeline as run_triage
        res = run_triage(image_url)
        return {
            "verdict": res.get("verdict"),
            "confidence": res.get("confidence"),
            "reasoning": res.get("reasoning"),
            "sources_found": res.get("sources_found", 0),
        }
    except Exception:
        logger.exception("verify_image failed")
        return {"verdict": "FLAGGED", "confidence": 0.5, "reasoning": "triage error", "sources_found": 0}
