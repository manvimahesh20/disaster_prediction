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
        try:
            interval_min = int(os.getenv("SCHEDULER_INTERVAL", "5"))
        except Exception:
            interval_min = 5
        scheduler.add_job(_run_and_broadcast, "interval", minutes=interval_min)
        scheduler.start()


async def _run_and_broadcast() -> None:
    try:
        # read previous severity
        from .memory_store import get_result

        prev = get_result()
        prev_sev = prev.get("severity")

        result = await run_nlp_check(source="auto")
        save_result(result)
        if _manager is not None:
            await _manager.broadcast(result)

        # log source counts and locations
        try:
            srcs = result.get("sources", []) or []
            locs = result.get("all_locations", []) or []
            logger.info("[Scheduler] sources=%s locations=%s", srcs, locs)
        except Exception:
            pass

        # if severity changed from previous, always send SMS
        cur_sev = result.get("severity")
        try:
            if cur_sev in {"MEDIUM", "HIGH"} and (prev_sev != cur_sev):
                send_sms_alert(cur_sev, result.get("location", ""), result.get("advice", ""))
            elif cur_sev in {"MEDIUM", "HIGH"} and prev_sev is None:
                send_sms_alert(cur_sev, result.get("location", ""), result.get("advice", ""))
        except Exception:
            logger.exception("[Scheduler] SMS send failed")

        logger.info("[Scheduler] Check complete - severity: %s", result.get("severity"))
    except Exception:
        logger.exception("Scheduled NLP run failed")


def force_check() -> None:
    """Trigger a scheduler run immediately."""
    if scheduler is not None:
        try:
            scheduler.add_job(_run_and_broadcast)
        except Exception:
            logger.exception("[Scheduler] force_check failed")
