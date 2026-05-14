import asyncio
import logging
from typing import Any, Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .memory_store import get_history, get_result, save_result
from .nlp_connector import run_nlp_check
from .scheduler import init_scheduler
from .nlp_connector import verify_image as verify_image_fn
from .memory_store import get_flagged_log

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voiceguard")

app = FastAPI(title="VoiceGuard AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class VoiceCheckRequest(BaseModel):
    query: str


class ImageVerifyRequest(BaseModel):
    image_url: str


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._connections)
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                logger.exception("WebSocket send failed")


manager = ConnectionManager()


@app.on_event("startup")
async def startup_event() -> None:
    init_scheduler(manager)
    logger.info("Scheduler started")


@app.get("/")
async def root() -> Dict[str, Any]:
    return {"status": "ok", "service": "VoiceGuard AI"}


@app.get("/check-now")
async def check_now() -> Dict[str, Any]:
    try:
        result = await run_nlp_check(source="manual")
        save_result(result)
        await manager.broadcast(result)
        return result
    except Exception:
        logger.exception("Manual check failed")
        return {"error": "Manual check failed"}


@app.post("/voice-check")
async def voice_check(payload: VoiceCheckRequest) -> Dict[str, Any]:
    try:
        result = await run_nlp_check(source="voice")
        save_result(result)
        await manager.broadcast(result)
        voice_response = (
            f"Disaster alert: {result.get('disaster_type')} detected in "
            f"{result.get('location')}. Severity: {result.get('severity')}. "
            f"{result.get('advice')}"
        )
        response = dict(result)
        response["voice_response"] = voice_response
        return response
    except Exception:
        logger.exception("Voice check failed")
        return {"error": "Voice check failed"}


@app.get("/history")
async def history() -> Dict[str, Any]:
    try:
        return get_history()
    except Exception:
        logger.exception("History fetch failed")
        return []


@app.get("/status")
async def status() -> Dict[str, Any]:
    try:
        result = get_result()
        return {
            "status": "ok",
            "last_check": result.get("timestamp"),
            "severity": result.get("severity", "UNKNOWN"),
        }
    except Exception:
        logger.exception("Status fetch failed")
        return {"status": "error"}


@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        logger.exception("WebSocket error")
        await manager.disconnect(websocket)


@app.post("/verify-image")
async def verify_image(payload: ImageVerifyRequest) -> Dict[str, Any]:
    try:
        res = verify_image_fn(payload.image_url)
        return res
    except Exception:
        logger.exception("Image verification failed")
        return {"error": "Image verification failed"}


@app.get("/misinformation-log")
async def misinformation_log() -> List[Dict[str, Any]]:
    try:
        return get_flagged_log()
    except Exception:
        logger.exception("Misinformation log fetch failed")
        return []
