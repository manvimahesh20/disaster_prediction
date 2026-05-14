import json
import sys
from typing import Any, Dict

import requests

BASE_URL = "http://127.0.0.1:8000"


def _print_result(name: str, ok: bool, detail: str) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name} - {detail}")


def _get(path: str) -> Dict[str, Any]:
    response = requests.get(f"{BASE_URL}{path}", timeout=10)
    response.raise_for_status()
    return response.json()


def _post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(f"{BASE_URL}{path}", json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


def main() -> int:
    try:
        result = _get("/check-now")
        _print_result("Check Now", True, json.dumps(result))
    except Exception as exc:
        _print_result("Check Now", False, str(exc))

    try:
        result = _post("/voice-check", {"query": "Any flood alerts in Mangalore?"})
        voice_response = result.get("voice_response", "")
        ok = bool(voice_response)
        _print_result("Voice Check", ok, voice_response or "missing voice_response")
    except Exception as exc:
        _print_result("Voice Check", False, str(exc))

    try:
        history = _get("/history")
        last_three = history[-3:]
        _print_result("History", True, json.dumps(last_three))
    except Exception as exc:
        _print_result("History", False, str(exc))

    try:
        status = _get("/status")
        _print_result("Status", True, json.dumps(status))
    except Exception as exc:
        _print_result("Status", False, str(exc))

    try:
        result = _get("/check-now")
        severity = result.get("severity")
        ok = severity in {"HIGH", "MEDIUM"}
        detail = f"severity={severity} (SMS would fire if HIGH/MEDIUM)"
        _print_result("SMS Trigger", ok, detail)
    except Exception as exc:
        _print_result("SMS Trigger", False, str(exc))

    return 0


if __name__ == "__main__":
    sys.exit(main())
