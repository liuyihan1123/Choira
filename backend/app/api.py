"""HTTP 接口层。"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response

from . import pipeline, store
from .services.role_detect import ROLE_ORDER, ROLES

MAX_UPLOAD = 30 * 1024 * 1024  # 30MB

router = APIRouter(prefix="/api")

MUSICXML_MIME = "application/vnd.recordare.musicxml+xml"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def _read_upload(upload: UploadFile) -> bytes:
    raw = await upload.read()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="文件超过 30MB 限制")
    return raw


@router.get("/health")
def health():
    return {"ok": True, "service": "choirparts", "version": "0.1.0"}


@router.get("/meta")
def meta():
    return {
        "roles": [
            {"code": code, **ROLES[code]} for code in ROLE_ORDER
        ],
        "stats": pipeline.stats(),
        "limits": {"upload_mb": MAX_UPLOAD // (1024 * 1024)},
    }


@router.get("/scores")
def list_scores():
    return {"items": pipeline.list_scores()}


@router.post("/scores")
async def create_score(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    composer: str = Form(""),
):
    raw = await _read_upload(file)
    try:
        detail = pipeline.create_score(raw, file.filename or "upload", title, composer)
    except pipeline.PipelineError as exc:
        raise _fail(exc)
    return detail


@router.post("/scores/{score_id}/versions")
async def add_version(score_id: str, file: UploadFile = File(...)):
    raw = await _read_upload(file)
    try:
        return pipeline.create_version(score_id, raw, file.filename or "upload")
    except pipeline.PipelineError as exc:
        raise _fail(exc)


@router.get("/versions/{version_id}")
def version_detail(version_id: str):
    try:
        return pipeline.version_detail(version_id)
    except pipeline.PipelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/versions/{version_id}/assignments")
def save_assignments(version_id: str, payload: dict = Body(...)):
    mapping = payload.get("mapping") or {}
    if not isinstance(mapping, dict):
        raise HTTPException(status_code=400, detail="mapping 必须是 {角色: [part_id]}")
    try:
        return pipeline.save_assignments(version_id, mapping)
    except pipeline.PipelineError as exc:
        raise _fail(exc)


@router.post("/versions/{version_id}/publish")
def publish(version_id: str, payload: dict = Body(default={})):
    try:
        return pipeline.publish(version_id, force=bool(payload.get("force")))
    except pipeline.PipelineError as exc:
        raise _fail(exc)


@router.post("/versions/{version_id}/attach-musicxml")
async def attach_musicxml(version_id: str, file: UploadFile = File(...)):
    raw = await _read_upload(file)
    try:
        return pipeline.attach_musicxml(version_id, raw, file.filename or "converted.musicxml")
    except pipeline.PipelineError as exc:
        raise _fail(exc)


@router.get("/versions/{version_id}/pdf")
def version_pdf(version_id: str):
    try:
        path = pipeline.pdf_path(version_id)
    except pipeline.PipelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return FileResponse(path, media_type="application/pdf", filename=path.name,
                        content_disposition_type="inline")


@router.get("/library/{role}")
def library(role: str):
    try:
        return pipeline.library(role)
    except pipeline.PipelineError as exc:
        raise _fail(exc)


@router.get("/assets/{asset_id}")
def asset_xml(asset_id: int, request: Request, role: str = Query("")):
    try:
        row, path = pipeline.asset_file(asset_id)
    except pipeline.PipelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    store.audit("view", role=role, version_id=row["version_id"], part_id=row["part_id"],
                ip=_client_ip(request))
    return Response(
        content=path.read_bytes(),
        media_type=MUSICXML_MIME,
        headers={
            "X-Part-Id": row["part_id"],
            "X-Version": str(row["version_no"]),
            "Cache-Control": "no-store",
        },
    )


@router.post("/assets/{asset_id}/sign")
def sign(asset_id: int, request: Request, role: str = Query("")):
    try:
        return pipeline.sign_download(asset_id, role, ip=_client_ip(request))
    except pipeline.PipelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/dl/{token}")
def download(token: str):
    try:
        row, path = pipeline.resolve_token(token)
    except pipeline.PipelineError as exc:
        raise HTTPException(status_code=410, detail=str(exc))
    store.audit("download", role="", version_id=row["version_id"], part_id=row["part_id"],
                detail=f"asset#{row['id']}")
    filename = f"{row['part_id']}-v{row['version_no']}.musicxml"
    return FileResponse(path, media_type=MUSICXML_MIME, filename=filename)


@router.get("/audit")
def audit(limit: int = Query(50, ge=1, le=500)):
    return {"items": pipeline.recent_audit(limit)}


@router.get("/stats")
def stats():
    return pipeline.stats()


# ---------------------------------------------------------------------------
# 排练播放：每个声部一条独立音轨
# ---------------------------------------------------------------------------

def _range_response(request: Request, path: Path, media_type: str) -> Response:
    """返回音频，支持 Range（浏览器拖动进度、Safari 播放都需要）。"""
    size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"}
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", request.headers.get("range", "").strip())
    if match and (match.group(1) or match.group(2)):
        if match.group(1):
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else size - 1
        else:  # bytes=-N 取末尾 N 字节
            start = max(size - int(match.group(2)), 0)
            end = size - 1
        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        end = min(end, size - 1)
        with path.open("rb") as handle:
            handle.seek(start)
            chunk = handle.read(end - start + 1)
        return Response(
            content=chunk,
            status_code=206,
            media_type=media_type,
            headers={
                **headers,
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Content-Length": str(len(chunk)),
            },
        )
    return FileResponse(path, media_type=media_type, headers=headers)


@router.get("/play/{version_id}")
def play(version_id: str, request: Request):
    try:
        data = pipeline.playlist(version_id)
    except pipeline.PipelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    store.audit("listen", version_id=version_id, ip=_client_ip(request),
                detail=f"{len([p for p in data['parts'] if p['available']])} 条声部音轨")
    return data


@router.get("/audio/{version_id}/{part_id}")
def part_audio(version_id: str, part_id: str, request: Request):
    try:
        row, path = pipeline.audio_file(version_id, part_id)
    except pipeline.PipelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _range_response(request, path, row.get("mime") or "audio/mpeg")
