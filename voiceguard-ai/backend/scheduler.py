import logging
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .memory_store import save_result
from .nlp_connector import run_nlp_check
from .sms import send_sms_alert


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
        save_result(result)
        if _manager is not None:
            await _manager.broadcast(result)
        if result.get("severity") in {"MEDIUM", "HIGH"}:
            send_sms_alert(result.get("severity", ""), result.get("location", ""), result.get("advice", ""))
        logger.info("[Scheduler] Check complete - severity: %s", result.get("severity"))
    except Exception:
        logger.exception("Scheduled NLP run failed")
