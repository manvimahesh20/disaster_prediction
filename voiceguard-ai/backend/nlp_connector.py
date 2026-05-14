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
        # TODO: swap this mock with Member 2's run_nlp_pipeline() function
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _build_mock_result, source)
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
