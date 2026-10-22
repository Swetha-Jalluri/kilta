"""FastAPI bridge: the stand-in for Alexa+ as the MCP client.

POST /api/turn, GET /api/events (SSE), GET /api/health, POST /api/reset.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .agent import KiltaAgent
from .chain import FallbackModel, build_chain
from .config import REPO_ROOT, Settings
from .events import EventBus, sse_format
from .models import TurnRequest, TurnResponse
from .prompt import build_system_prompt

log = logging.getLogger("kilta.bridge")

RUNTIME_DIRS = ("sessions", "state")


def clear_runtime_data(data_dir) -> None:
    """The same thing `make reset` does. Refuses to touch a folder that isn't Kilta's data."""
    if not (data_dir / "household.json").exists():
        raise RuntimeError(f"{data_dir} does not look like the Kilta data folder")
    for name in RUNTIME_DIRS:
        shutil.rmtree(data_dir / name, ignore_errors=True)


def create_app(settings: Settings | None = None, chain: FallbackModel | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    bus = EventBus()
    chain = chain or build_chain(settings)
    kilta = KiltaAgent(settings, chain, bus, build_system_prompt(settings.docs_dir))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        kilta.close()

    app = FastAPI(title="Kilta bridge", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.kilta = kilta
    app.state.bus = bus

    @app.post("/api/turn", response_model=TurnResponse)
    async def turn(request: TurnRequest) -> TurnResponse:
        return await kilta.turn(request)

    @app.get("/api/events")
    async def events(replay: int = Query(default=0, ge=0, le=200)) -> StreamingResponse:
        async def stream() -> AsyncIterator[str]:
            yield ": connected\n\n"
            subscription = bus.subscribe(replay)
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(anext(subscription), timeout=15)
                    except TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield sse_format(event)
            finally:
                await subscription.aclose()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/health")
    async def health() -> dict:
        mcp = await kilta.health()
        models = [link.name for link in chain.links]
        status = "ok" if mcp["reachable"] else "degraded"
        return {
            "status": status,
            "mcp": mcp,
            "models": models,
            "last_model": chain.last_used,
            "demo_mode": settings.demo_mode,
            "state": kilta.state,
            "session_id": kilta.session_id,
        }

    @app.post("/api/reset")
    async def reset() -> dict:
        if not settings.demo_mode:
            raise HTTPException(status_code=403, detail="reset is only available in demo mode")
        async with kilta.lock:
            clear_runtime_data(settings.data_dir)
            kilta.reset()
        return {"ok": True, "message": "Demo data restored and conversation cleared."}

    return app


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    import os

    uvicorn.run(
        create_app(),
        host=os.environ.get("KILTA_BRIDGE_HOST", "127.0.0.1"),
        port=int(os.environ.get("KILTA_BRIDGE_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
