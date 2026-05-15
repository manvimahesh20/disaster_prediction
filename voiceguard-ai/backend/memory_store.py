import logging
from threading import Lock
from typing import Dict, List

logger = logging.getLogger("voiceguard")

_latest_result: Dict[str, object] = {}
_history: List[Dict[str, object]] = []
_lock = Lock()
_misinformation_log: List[Dict[str, object]] = []


def save_result(result: Dict[str, object]) -> None:
    try:
        if not isinstance(result, dict):
            logger.error("[Memory] Invalid result type")
            return
        with _lock:
            _latest_result.clear()
            _latest_result.update(result)
            _history.append(dict(result))
            if len(_history) > 10:
                _history[:] = _history[-10:]
        logger.info("[Memory] Result saved")
    except Exception:
        logger.exception("[Memory] Save failed")


def get_result() -> Dict[str, object]:
    try:
        with _lock:
            return dict(_latest_result)
    except Exception:
        logger.exception("[Memory] Get failed")
        return {}


def get_history() -> List[Dict[str, object]]:
    try:
        with _lock:
            return list(_history)
    except Exception:
        logger.exception("[Memory] History failed")
        return []


def clear() -> None:
    try:
        with _lock:
            _latest_result.clear()
            _history.clear()
            _misinformation_log.clear()
        logger.info("[Memory] Cleared")
    except Exception:
        logger.exception("[Memory] Clear failed")


def save_flagged(post: Dict[str, object], reason: str) -> None:
    """Save a flagged post into the misinformation log with a timestamp and reason."""
    try:
        entry = dict(post)
        entry["flagged_reason"] = reason
        entry["flagged_timestamp"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        with _lock:
            _misinformation_log.append(entry)
            # keep the log bounded
            if len(_misinformation_log) > 500:
                _misinformation_log[:] = _misinformation_log[-500:]
        logger.info("[Memory] Flagged post saved: %s", entry.get("id"))
    except Exception:
        logger.exception("[Memory] Save flagged failed")


def get_flagged_log() -> List[Dict[str, object]]:
    try:
        with _lock:
            return list(_misinformation_log)
    except Exception:
        logger.exception("[Memory] Get flagged log failed")
        return []
