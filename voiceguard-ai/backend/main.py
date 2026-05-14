import asyncio
import logging
from typing import Any, Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .scheduler import init_scheduler, run_nlp_check

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
    result = await run_nlp_check(source="manual")
    await manager.broadcast(result)
    return result


@app.post("/voice-check")
async def voice_check(payload: VoiceCheckRequest) -> Dict[str, Any]:
    result = await run_nlp_check(source="voice", voice_query=payload.query)
    await manager.broadcast(result)
    return result


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
