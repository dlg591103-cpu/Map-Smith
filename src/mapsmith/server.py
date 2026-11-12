"""FastAPI 服务（T22 第二段）：SSE、上传、CRS 确认、静态前端与产物下载。

前端源码在 `web/`，构建产物 `web/dist/` 随仓库提交；本模块只负责 HTTP 接口。
契约见 `docs/Spec/T22-一句话入口与loop接入.md` 第 6 节。
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from . import flow
from .agents.llm import LLMError, LLMNotConfigured, configured
from .config import Settings, get_settings
from .io.models import CrsNotDeclared, DataError, FieldMissing
from .io.uploads import parse_upload

APP_VERSION = "V0.1"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_SUFFIXES = {".csv", ".geojson", ".json", ".zip"}
ALLOWED_FILENAMES = {"web_map.png", "web_map.pdf"}
UPLOAD_REGISTRY: dict[str, flow.UploadRecord] = {}

app = FastAPI(title="MapSmith", version=APP_VERSION)


class ChatBody(BaseModel):
    message: str = ""
    upload_id: str | None = None


class FormBody(BaseModel):
    place: str = ""
    time: str = ""
    metric: str = ""
    map_type: str = "point"
    method: str = "quantile"
    n: int = 5
    palette_scheme: str = "YlOrRd"
    palette_reverse: bool = False
    label_field: str | None = None
    show_label: bool = False
    upload_id: str | None = None


class CrsBody(BaseModel):
    crs: str


def _settings() -> Settings:
    return get_settings()


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _friendly_error(exc: BaseException) -> str:
    if isinstance(exc, (LLMNotConfigured, LLMError, CrsNotDeclared, FieldMissing, DataError)):
        return str(exc)
    return f"{type(exc).__name__}：{exc}"


def _upload_record(upload_id: str | None) -> flow.UploadRecord | None:
    if not upload_id:
        return None
    record = UPLOAD_REGISTRY.get(upload_id)
    if record is None:
        raise DataError("上传记录不存在或已过期，请重新上传文件")
    return record


def _crs_required_event(record: flow.UploadRecord) -> dict[str, Any]:
    return {
        "upload_id": record.upload_id,
        "name": record.name,
        "suggested": record.suggested_crs or "EPSG:4326",
        "options": [record.suggested_crs or "EPSG:4326", "EPSG:4490", "EPSG:4326"],
    }


def _result_payload(run: flow.FlowRun, request_id: str) -> dict[str, Any]:
    result = run.result
    render_result = run.render_result
    png = f"/api/output/{request_id}/web_map.png" if result.png is not None else None
    pdf_path = getattr(render_result, "pdf_path", None)
    pdf = f"/api/output/{request_id}/web_map.pdf" if pdf_path is not None else None
    return {
        "status": result.status,
        "round_no": result.round_no,
        "elapsed": result.elapsed,
        "summary": result.summary,
        "notes": list(result.notes),
        "review": result.review,
        "spec": result.spec,
        "decision": result.decision,
        "questions": list(result.questions),
        "png": png,
        "pdf": pdf,
    }


def _stream(worker_body: Any) -> StreamingResponse:
    """把同步 worker 的阶段事件、结果与错误转成 SSE。"""
    events: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()

    def worker() -> None:
        try:
            for event, data in worker_body(events):
                events.put((event, data))
        except Exception as exc:  # noqa: BLE001 - 对外只暴露中文原因
            events.put(("error", {"message": _friendly_error(exc)}))
        finally:
            events.put(("done", {}))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    def generate() -> Iterator[str]:
        while True:
            event, data = events.get()
            yield _sse(event, data)
            if event == "done":
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "llm_configured": configured(_settings()), "version": APP_VERSION}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    name = Path(file.filename or "upload").name
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{suffix or '（无扩展名）'}；支持 CSV / GeoJSON / Shapefile(zip)",
        )

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 20 MB 上限")

    current = _settings()
    upload_id = "u_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    folder = Path(current.output_dir) / "uploads" / upload_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(content)

    try:
        layer = parse_upload(path)
    except DataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record = flow.UploadRecord(
        upload_id=upload_id,
        path=path,
        name=name,
        kind=layer.kind,
        crs_status=str(layer.meta.get("crs_status") or ""),
        suggested_crs=layer.meta.get("suggested_crs"),
    )
    UPLOAD_REGISTRY[upload_id] = record
    return {
        "upload_id": upload_id,
        "name": name,
        "kind": layer.kind,
        "crs_status": record.crs_status,
        "suggested_crs": record.suggested_crs,
        "summary": layer.summary,
    }


@app.post("/api/upload/{upload_id}/crs")
def confirm_crs(upload_id: str, body: CrsBody) -> dict[str, Any]:
    record = UPLOAD_REGISTRY.get(upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail="上传记录不存在或已过期")

    try:
        layer = parse_upload(record.path, crs=body.crs)
    except DataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record.confirmed_crs = body.crs
    record.kind = layer.kind
    record.crs_status = str(layer.meta.get("crs_status") or "declared")
    return {
        "upload_id": record.upload_id,
        "kind": record.kind,
        "crs_status": record.crs_status,
        "confirmed_crs": record.confirmed_crs,
        "summary": layer.summary,
    }


@app.post("/api/chat")
def chat(body: ChatBody) -> StreamingResponse:
    current = _settings()
    request_id = flow.new_request_id()

    def worker(events: queue.Queue[tuple[str, dict[str, Any]]]) -> Iterator[tuple[str, dict[str, Any]]]:
        record = _upload_record(body.upload_id)
        if record is not None and record.crs_status == "missing" and not record.confirmed_crs:
            yield "crs_required", _crs_required_event(record)
            return
        if not configured(current):
            raise LLMNotConfigured(
                "未配置模型：请设置 MAPSMITH_LLM_BASE_URL / MAPSMITH_LLM_API_KEY / "
                "MAPSMITH_LLM_MODEL，或在高级表单中出图。"
            )

        run = flow.run_one_sentence(
            body.message,
            upload=record,
            output_dir=current.output_dir,
            request_id=request_id,
            settings=current,
            on_stage=lambda stage, label: events.put(("stage", {"stage": stage, "label": label})),
        )
        yield "result", _result_payload(run, request_id)

    return _stream(worker)


@app.post("/api/form")
def form(body: FormBody) -> StreamingResponse:
    current = _settings()
    request_id = flow.new_request_id()

    def worker(events: queue.Queue[tuple[str, dict[str, Any]]]) -> Iterator[tuple[str, dict[str, Any]]]:
        record = _upload_record(body.upload_id)
        if record is not None and record.crs_status == "missing" and not record.confirmed_crs:
            yield "crs_required", _crs_required_event(record)
            return

        run = flow.run_form(
            body.model_dump(),
            upload=record,
            output_dir=current.output_dir,
            request_id=request_id,
            settings=current,
            on_stage=lambda stage, label: events.put(("stage", {"stage": stage, "label": label})),
        )
        yield "result", _result_payload(run, request_id)

    return _stream(worker)


@app.get("/api/output/{request_id}/{filename}")
def output(request_id: str, filename: str) -> FileResponse:
    if not re.fullmatch(r"r_[A-Za-z0-9_]+", request_id):
        raise HTTPException(status_code=404, detail="产物不存在")
    if filename not in ALLOWED_FILENAMES:
        raise HTTPException(status_code=404, detail="产物不存在")

    root = (Path(_settings().output_dir) / "web").resolve()
    path = (root / request_id / filename).resolve()
    if root not in path.parents:
        raise HTTPException(status_code=403, detail="不允许访问该路径")
    if not path.exists():
        raise HTTPException(status_code=404, detail="产物不存在")

    media = "image/png" if filename.endswith(".png") else "application/pdf"
    return FileResponse(path, media_type=media, filename=filename)


def _dist_dir() -> Path:
    return Path(_settings().project_root) / "web" / "dist"


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    target = _dist_dir() / "index.html"
    if not target.exists():
        return HTMLResponse(
            "<h1>MapSmith 前端未构建</h1><p>请先执行：cd web && npm install && npm run build</p>",
            status_code=503,
        )
    return HTMLResponse(target.read_text(encoding="utf-8"))


@app.get("/{full_path:path}")
def static_file(full_path: str) -> FileResponse:
    root = _dist_dir().resolve()
    target = (root / full_path).resolve()
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="页面不存在")
    return FileResponse(target)