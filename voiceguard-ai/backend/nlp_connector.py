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


async def run_nlp_check(source: str = "auto") -> Dict[str, Any]:
    try:
        # Attempt to run the mock pipeline but run image triage for posts that include images.
        # This keeps behaviour backwards-compatible while adding image verification.
        loop = asyncio.get_event_loop()
        posts = await loop.run_in_executor(None, _load_posts)

        # Lazy import triage runner to avoid hard dependency unless needed
        try:
            try:
                # prefer local import
                from triage_pipeline import run_pipeline as run_triage
            except Exception:
                from voiceguard_ai.nlp.triage_pipeline import run_pipeline as run_triage
        except Exception:
            run_triage = None

        # Filter out posts flagged by triage
        filtered_posts: List[Dict[str, Any]] = []
        for p in posts:
            try:
                if p.get("image_url") and run_triage:
                    triage_res = run_triage(p.get("image_url"))
                    verdict = triage_res.get("verdict")
                    reason = triage_res.get("reasoning") or triage_res.get("reason")
                    # If flagged, save to misinformation log and skip
                    if verdict != "VERIFIED_REAL":
                        try:
                            from .memory_store import save_flagged

                            save_flagged(p, reason or "triage flagged")
                        except Exception:
                            logger.exception("Failed to save flagged post")
                        continue
                filtered_posts.append(p)
            except Exception:
                logger.exception("Triage failure for post: %s", p.get("id"))

        # Build result from filtered posts (preserve prior behaviour)
        high_posts = [p for p in filtered_posts if _is_high(p.get("text", ""))]
        if high_posts:
            selected = random.choice(high_posts)
            logger.info("[NLP] Mock pick: %s", selected.get("id", "unknown"))
        elif filtered_posts:
            selected = random.choice(filtered_posts)
            logger.info("[NLP] Mock pick fallback: %s", selected.get("id", "unknown"))
        else:
            logger.warning("[NLP] No posts left after triage/filters")
            return {
                "disaster_type": "None",
                "location": "Unknown",
                "severity": "LOW",
                "advice": "No posts available after triage.",
                "posts_analyzed": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": source,
            }

        # Compose mock result based on the selected post
        result = {
            "disaster_type": "Flood",
            "location": selected.get("location", "Mangalore"),
            "severity": "HIGH" if _is_high(selected.get("text", "")) else "LOW",
            "advice": "Evacuate low-lying areas immediately. Call NDRF: 011-24363260",
            "posts_analyzed": len(filtered_posts),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
        }
        return result
    except Exception:
        logger.exception("[NLP] Mock run failed")
        return {
            "disaster_type": "None",
            "location": "Unknown",
            "severity": "LOW",
            "advice": "Mock NLP failed.",
            "posts_analyzed": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
        }


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
