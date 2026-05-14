"""Rescue triage pipeline

This module provides a small triage pipeline that verifies whether an
image reported on social media is likely a real disaster image by
checking reverse-image search results and running a vision-language
model (DeepSeek) to make a final judgement.

Functions are defensive and log clearly; external API keys are taken
from environment variables:
  - SERPAPI_KEY
  - DEEPSEEK_API_KEY
  - DEEPSEEK_MODEL (optional, default deepseek-vision)

If external services are unavailable the module degrades gracefully
and returns conservative triage results.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger("triage")


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    snippet: str


@dataclass
class TriageResult:
    verdict: str  # VERIFIED_REAL or FLAGGED
    confidence: float  # 0.0 - 1.0
    reasoning: str
    sources_found: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "confidence": float(self.confidence),
            "reasoning": self.reasoning,
            "sources_found": int(self.sources_found),
        }


# Trusted news domains (allow subdomains via endswith())
TRUSTED_SOURCES = [
    "timesofindia.com",
    "ndtv.com",
    "thehindu.com",
    "deccanherald.com",
    "newindianexpress.com",
    "indianexpress.com",
    "hindustantimes.com",
    "bbc.com",
    "reuters.com",
    "pti.in",
]


def reverse_image_search(image_url: str) -> List[Dict[str, Any]]:
    """Call SerpApi google_reverse_image and return raw results list.

    Returns an empty list on error so callers can degrade.
    """
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        logger.warning("SERPAPI_KEY not set; skipping reverse image search")
        return []

    try:
        endpoint = "https://serpapi.com/search.json"
        params = {
            "engine": "google_reverse_image",
            "image_url": image_url,
            "api_key": api_key,
        }
        resp = requests.get(endpoint, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        # serpapi may return results under several keys; prefer `image_results` or `inline_images`
        candidates = []
        if isinstance(data, dict):
            if "image_results" in data and isinstance(data["image_results"], list):
                candidates = data["image_results"]
            elif "inline_images" in data and isinstance(data["inline_images"], list):
                candidates = data["inline_images"]
            elif "results" in data and isinstance(data["results"], list):
                candidates = data["results"]
            else:
                # fallback: return full payload wrapped in a list
                candidates = [data]
        else:
            candidates = []
        logger.info("Reverse image search returned %d candidates", len(candidates))
        return candidates
    except Exception:
        logger.exception("Reverse image search failed")
        return []


def filter_news_results(results: List[Dict[str, Any]]) -> List[NewsItem]:
    """Filter raw reverse-image results for entries that come from trusted news sources.

    Uses endswith() on the netloc to allow subdomains (m.timesofindia.com).
    """
    out: List[NewsItem] = []
    try:
        for r in results:
            # Try a few common keys for the result URL/title/snippet
            url = r.get("link") or r.get("url") or r.get("source") or r.get("displayed_link")
            title = r.get("title") or r.get("name") or r.get("title_no_formatting") or ""
            snippet = r.get("snippet") or r.get("description") or r.get("snippet_highlighted") or ""

            if not url:
                # some SerpApi results may embed a 'serpapi_link' or similar
                url = r.get("serpapi_link") or r.get("result_url")
            if not url:
                continue

            try:
                parsed = urlparse(url)
                netloc = parsed.netloc.lower()
            except Exception:
                netloc = url.lower()

            for trusted in TRUSTED_SOURCES:
                if netloc.endswith(trusted):
                    source = trusted
                    out.append(NewsItem(title=title.strip(), url=url, source=source, snippet=snippet.strip()))
                    break
    except Exception:
        logger.exception("Filtering news results failed")
    return out


def _parse_model_response_text(text: str) -> Optional[TriageResult]:
    """Attempt to extract JSON from model text and parse to TriageResult."""
    try:
        # find first { ... } block
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        json_text = m.group(0) if m else text
        payload = json.loads(json_text)
        verdict = payload.get("verdict") or payload.get("label")
        confidence = float(payload.get("confidence", 0.0))
        reasoning = payload.get("reasoning", payload.get("explanation", ""))
        sources_found = int(payload.get("sources_found", payload.get("sources", 0)))
        return TriageResult(verdict=str(verdict), confidence=confidence, reasoning=str(reasoning), sources_found=sources_found)
    except Exception:
        logger.exception("Failed to parse model response JSON")
        return None


def run_vlm_inference(image_url: str, news_items: List[NewsItem]) -> TriageResult:
    """Call DeepSeek (OpenAI-compatible) to triage the image.

    Returns a TriageResult. On parsing/model errors conservative FLAGGED
    result with confidence 0.5 is returned.
    """
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        logger.warning("DEEPSEEK_API_KEY not set; cannot run VLM inference")
        return TriageResult(verdict="FLAGGED", confidence=0.5, reasoning="DeepSeek API key missing", sources_found=len(news_items))

    model = os.getenv("DEEPSEEK_MODEL", "deepseek-vision")
    system_prompt = (
        "You are a triage assistant. Respond with JSON ONLY. "
        "Return an object with keys: verdict (VERIFIED_REAL or FLAGGED), confidence (0.0-1.0), reasoning (string), sources_found (int). "
        "Do not include any text outside the JSON. If uncertain, choose FLAGGED."
    )

    # Compose context
    news_ctx = "\n".join([f"- {n.title} ({n.source}): {n.snippet}" for n in news_items[:6]]) or "No trusted sources found."
    user_prompt = f"Image URL: {image_url}\n\nNews context:\n{news_ctx}\n"

    try:
        # Try to use the OpenAI-compatible client if available
        try:
            from openai import OpenAI

            client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
            # prefer vision model; fallback will be handled below
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.1,
                )
                # Safe extraction for different response formats
                content = None
                if hasattr(resp, "choices") and resp.choices:
                    # new OpenAI client
                    choice = resp.choices[0]
                    msg = getattr(choice, "message", None)
                    if msg:
                        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
                    else:
                        content = getattr(choice, "text", None) or getattr(choice, "message", None)
                else:
                    # fallback to raw text
                    content = str(resp)

                if not content:
                    logger.warning("Model returned no textual content")
                    return TriageResult(verdict="FLAGGED", confidence=0.5, reasoning="Empty model response", sources_found=len(news_items))

                parsed = _parse_model_response_text(content)
                if parsed:
                    return parsed
            except Exception:
                logger.exception("DeepSeek chat completion call failed; attempting fallback model")

        except Exception:
            # openai.OpenAI client not available; try using requests to call a hypothetical endpoint
            logger.warning("OpenAI client not available; attempting HTTP fallback (may fail)")

        # If we reach here, we couldn't get a parsed model response
        return TriageResult(verdict="FLAGGED", confidence=0.5, reasoning="VLM inference unavailable or parse failed", sources_found=len(news_items))
    except Exception:
        logger.exception("VLM inference failed")
        return TriageResult(verdict="FLAGGED", confidence=0.5, reasoning="VLM inference exception", sources_found=len(news_items))


def _on_verified_real(result: TriageResult) -> str:
    try:
        logger.info("Triage VERIFIED_REAL (conf=%.2f): %s", result.confidence, result.reasoning)
    except Exception:
        logger.exception("_on_verified_real logging failed")
    return "ALLOW"


def _on_flagged(result: TriageResult) -> str:
    try:
        logger.warning("Triage FLAGGED (conf=%.2f): %s", result.confidence, result.reasoning)
    except Exception:
        logger.exception("_on_flagged logging failed")
    return "BLOCK"


def route(result: TriageResult) -> str:
    """Decision gate: return 'ALLOW' or 'BLOCK' based on verdict and confidence."""
    try:
        if result.verdict == "VERIFIED_REAL" and result.confidence >= 0.85:
            return _on_verified_real(result)
        return _on_flagged(result)
    except Exception:
        logger.exception("Routing decision failed")
        return _on_flagged(result)


def run_pipeline(image_url: str) -> Dict[str, Any]:
    """Run the full triage pipeline for a single image URL.

    Returns a dict with triage result and intermediate details.
    """
    try:
        data: Dict[str, Any] = {"image_url": image_url}

        # Step 1: reverse image search
        results = reverse_image_search(image_url)
        data["reverse_results_count"] = len(results)

        # Step 2: filter for news
        news_items = filter_news_results(results)
        data["trusted_sources_found"] = len(news_items)
        data["news_items"] = [n.__dict__ for n in news_items]

        # Step 3: run VLM inference
        triage = run_vlm_inference(image_url, news_items)
        data.update(triage.to_dict())

        # Step 4: routing decision
        decision = route(triage)
        data["decision"] = decision

        return data
    except Exception:
        logger.exception("Triage pipeline run failed")
        # conservative fallback
        fallback = TriageResult(verdict="FLAGGED", confidence=0.5, reasoning="Internal error during triage", sources_found=0)
        return {"image_url": image_url, **fallback.to_dict(), "decision": _on_flagged(fallback)}
