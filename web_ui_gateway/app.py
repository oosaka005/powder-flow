from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from web_ui_gateway.sila_client import PowderCharacterizerClient


STATIC_DIR = Path(__file__).resolve().parent / "static"


class ManualRequest(BaseModel):
    vibration_level: int = Field(ge=0, le=5)
    vibration_seconds: float = Field(ge=0)
    dose_count: int = Field(ge=0, le=99)
    use_auger: bool


class PreviewRequest(BaseModel):
    focus_mode: str
    lens_position: float


class SaveRequest(BaseModel):
    update_material_database: bool = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.characterizer = None
    try:
        yield
    finally:
        client = app.state.characterizer
        if client is not None:
            client.close()


app = FastAPI(title="Powder Characterizer Web UI Gateway", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _client(request: Request) -> PowderCharacterizerClient:
    if request.app.state.characterizer is None:
        try:
            request.app.state.characterizer = PowderCharacterizerClient()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return request.app.state.characterizer


def _run(call):
    try:
        return call()
    except Exception as exc:
        text = str(exc)
        status = 409 if "already running" in text.lower() else 502
        raise HTTPException(status_code=status, detail=text) from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health(request: Request) -> dict[str, Any]:
    state = _run(lambda: _client(request).current_run())
    return {"status": "ok", "characterizer": state.get("status")}


@app.get("/api/settings")
def get_settings(request: Request) -> dict[str, Any]:
    return _run(lambda: _client(request).get_settings())


@app.put("/api/settings")
def update_settings(settings: dict[str, Any], request: Request) -> dict[str, bool]:
    _run(lambda: _client(request).update_settings(settings))
    return {"saved": True}


@app.get("/api/materials")
def materials(request: Request) -> Any:
    return _run(lambda: _client(request).get_material_database())


@app.get("/api/runs/current")
def current_run(request: Request) -> dict[str, Any]:
    return _run(lambda: _client(request).current_run())


@app.post("/api/runs/automated", status_code=202)
def run_automated(request: Request) -> dict[str, str]:
    return _run(lambda: _client(request).run_automated())


@app.post("/api/runs/single/{stage}", status_code=202)
def run_single(stage: str, request: Request) -> dict[str, str]:
    allowed = {"calibration", "bulk_density", "tapped_density", "angle_of_repose"}
    if stage not in allowed:
        raise HTTPException(status_code=400, detail="Unknown single-test stage.")
    return _run(lambda: _client(request).run_single(stage))


@app.post("/api/runs/manual", status_code=202)
def run_manual(payload: ManualRequest, request: Request) -> dict[str, str]:
    return _run(
        lambda: _client(request).run_manual(
            vibration_level=payload.vibration_level,
            vibration_seconds=payload.vibration_seconds,
            dose_count=payload.dose_count,
            use_auger=payload.use_auger,
        )
    )


@app.post("/api/runs/clear-clog")
def clear_clog(request: Request) -> dict[str, Any]:
    return _run(lambda: _client(request).clear_clog())


@app.post("/api/runs/abort")
def abort(request: Request) -> dict[str, bool]:
    _run(lambda: _client(request).abort())
    return {"aborting": True}


@app.post("/api/results/save")
def save(payload: SaveRequest, request: Request) -> dict[str, bool]:
    _run(
        lambda: _client(request).save_results(payload.update_material_database)
    )
    return {"saved": True}


@app.post("/api/results/discard")
def discard(request: Request) -> dict[str, bool]:
    _run(lambda: _client(request).discard_results())
    return {"discarded": True}


@app.post("/api/camera/preview")
def camera_preview(payload: PreviewRequest, request: Request) -> Response:
    data, media_type, filename = _run(
        lambda: _client(request).camera_preview(
            payload.focus_mode, payload.lens_position
        )
    )
    return Response(
        data,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.post("/api/camera/repose-preview")
def repose_preview(request: Request) -> Response:
    data, media_type, filename = _run(lambda: _client(request).repose_preview())
    return Response(
        data,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/api/runs/{run_id}/artifacts/{filename}")
def artifact(run_id: str, filename: str, request: Request) -> Response:
    data, media_type = _run(lambda: _client(request).artifact(run_id, filename))
    return Response(data, media_type=media_type)


@app.websocket("/ws/run")
async def run_updates(websocket: WebSocket) -> None:
    await websocket.accept()
    client: PowderCharacterizerClient | None = None
    previous = None
    try:
        while True:
            if client is None:
                if websocket.app.state.characterizer is None:
                    websocket.app.state.characterizer = await asyncio.to_thread(
                        PowderCharacterizerClient
                    )
                client = websocket.app.state.characterizer
            state = await asyncio.to_thread(client.current_run)
            if state != previous:
                await websocket.send_json(state)
                previous = state
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"status": "gateway_error", "error": str(exc)})
        await websocket.close()
