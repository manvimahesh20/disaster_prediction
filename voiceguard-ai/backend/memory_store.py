import logging
from threading import Lock
from typing import Dict, List

logger = logging.getLogger("voiceguard")

_latest_result: Dict[str, object] = {}
_history: List[Dict[str, object]] = []
_lock = Lock()


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
        logger.info("[Memory] Cleared")
    except Exception:
        logger.exception("[Memory] Clear failed")
