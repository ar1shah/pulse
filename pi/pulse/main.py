"""FastAPI app: serves ui/, broadcasts a snapshot on /ws every 100 ms, GET /api/snapshot.

Run with `python -m pulse.main` (from pi/) or `uvicorn pulse.main:create_app --factory`.
Data source comes from env PULSE_SOURCE (sim | live | replay), see sources.py.
"""
import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .fusion import Fusion
from .sources import Source, make_source

log = logging.getLogger("pulse.main")

UI_DIR = Path(__file__).resolve().parents[2] / "ui"
TICK_S = 0.1
HOST = "0.0.0.0"
PORT = 8000
# Chromium kiosk caches hard; no-cache makes it revalidate (cheap 304s) so a deploy shows up on reload.
NO_CACHE = {"Cache-Control": "no-cache"}


class _UiFiles(StaticFiles):
    def file_response(self, *args: Any, **kwargs: Any):
        response = super().file_response(*args, **kwargs)
        response.headers.update(NO_CACHE)
        return response


class Pulse:
    """Owns the source and fusion, runs the 10 Hz tick, and fans snapshots out to websocket clients."""

    def __init__(self, source: Source) -> None:
        self.source = source
        self.fusion = Fusion(source.name)
        self.latest: dict[str, Any] | None = None
        self.latest_json: str | None = None
        self._clients: set[asyncio.Queue[str]] = set()

    def tick(self) -> None:
        now = time.time()
        ld_frame, ld_status = self.source.ld2450(now)
        c1_reading, c1_status = self.source.c1001(now)
        snap = self.fusion.update(now, ld_frame, ld_status, c1_reading, c1_status).to_dict()
        self.latest = snap
        self.latest_json = json.dumps(snap)
        for q in self._clients:
            if q.full():
                q.get_nowait()      # a slow client gets the newest snapshot, never a backlog
            q.put_nowait(self.latest_json)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        next_at = loop.time()
        while True:
            try:
                self.tick()
            except Exception:
                log.exception("tick failed; carrying on")
            next_at += TICK_S
            delay = next_at - loop.time()
            if delay < 0:           # fell behind: resume the cadence instead of bursting
                next_at, delay = loop.time(), 0
            await asyncio.sleep(delay)

    def handle_message(self, raw: str) -> None:
        """Apply one client message. Anything unknown or invalid is logged and ignored."""
        try:
            msg = json.loads(raw)
        except ValueError:
            log.warning("ignored non-JSON client message: %.200r", raw)
            return
        kind = msg.get("type") if isinstance(msg, dict) else None
        if kind == "set_gate":
            if not self.fusion.set_gate(msg.get("max_range_m"), msg.get("max_angle_deg")):
                log.warning("ignored invalid set_gate: %.200r", msg)
        elif kind == "reset_contacts":
            self.fusion.reset_contacts()
            log.info("contacts reset")
        else:
            log.warning("ignored unknown client message: %.200r", msg)

    async def serve_client(self, ws: WebSocket) -> None:
        await ws.accept()
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        if self.latest_json is not None:
            q.put_nowait(self.latest_json)
        self._clients.add(q)

        async def send_loop() -> None:
            while True:
                await ws.send_text(await q.get())

        async def receive_loop() -> None:
            while True:
                event = await ws.receive()
                if event["type"] == "websocket.disconnect":
                    return
                text = event.get("text")
                if text is None and event.get("bytes") is not None:
                    text = event["bytes"].decode("utf-8", "replace")
                if text is not None:
                    self.handle_message(text)

        tasks = [asyncio.create_task(send_loop()), asyncio.create_task(receive_loop())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            self._clients.discard(q)
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(BaseException):    # a dead client is routine, never an error
                    await t
            with contextlib.suppress(Exception):
                await ws.close()


def create_app(source: Source | None = None) -> FastAPI:
    pulse = Pulse(source if source is not None else make_source())

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            pulse.source.start()
        except Exception:
            log.exception("source failed to start; serving anyway")
        task = asyncio.create_task(pulse.run())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            with contextlib.suppress(Exception):
                pulse.source.stop()

    app = FastAPI(title="Pulse", lifespan=lifespan)
    app.state.pulse = pulse

    def page(name: str) -> FileResponse:
        path = UI_DIR / name
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"{name} not built yet")
        return FileResponse(path, headers=NO_CACHE)

    @app.get("/api/snapshot")
    def snapshot() -> dict[str, Any]:
        if pulse.latest is None:
            pulse.tick()
        return pulse.latest  # type: ignore[return-value]

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await pulse.serve_client(ws)

    @app.get("/")
    def index() -> FileResponse:
        return page("index.html")

    @app.get("/debug")
    def debug() -> FileResponse:
        return page("debug.html")

    @app.get("/command")
    def command() -> FileResponse:
        return page("command.html")

    app.mount("/", _UiFiles(directory=UI_DIR), name="ui")
    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
