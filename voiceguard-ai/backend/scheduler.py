import asyncio
import logging
from typing import Any, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from nlp.pipeline import run_pipeline

logger = logging.getLogger("voiceguard")

scheduler: Optional[AsyncIOScheduler] = None
_manager = None


def init_scheduler(manager: Any) -> None:
    global scheduler, _manager
    _manager = manager
    if scheduler is None:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(_run_and_broadcast, "interval", minutes=5)
        scheduler.start()


async def _run_and_broadcast() -> None:
    try:
        result = await run_nlp_check(source="auto")
        if _manager is not None:
            await _manager.broadcast(result)
    except Exception:
        logger.exception("Scheduled NLP run failed")


async def run_nlp_check(source: str = "auto", voice_query: Optional[str] = None) -> Dict[str, Any]:
    loop = asyncio.get_event_loop()
    # Run CPU-heavy pipeline in a thread to avoid blocking.
    result = await loop.run_in_executor(None, run_pipeline, source, voice_query)
    return result
