"""业务流水线：入库 → 解析 → 角色映射 → 生成分谱 → 发布 → 按角色取谱。"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import store
from .services import audio as audio_service
from .services import musicxml as mx
from .services.role_detect import ROLE_ORDER, ROLES

PDF_MAGIC = b"%PDF"


class PipelineError(ValueError):
    """业务校验失败（提示信息直接给前端）。"""


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


def _safe_name(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", text or "part") or "part"


def _is_pdf(raw: bytes, filename: str) -> bool:
    return filename.lower().endswith(".pdf") or raw[:4] == PDF_MAGIC


def _save_bytes(path: Path, raw: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(store.DATA_DIR))
    except ValueError:
        return str(path)


def _part_row_to_dict(row) -> dict:
    return {
        "part_id": row["part_id"],
        "index": row["idx"],
        "name": row["name"],
        "abbreviation": row["abbreviation"],
        "staves": row["staves"],
        "voices": json.loads(row["voices"] or "[]"),
        "note_count": row["note_count"],
        "multi_voice": bool(row["multi_voice"]),
        "extractable": bool(row["extractable"]),
        "suggested_role": row["suggested_role"],
        "confidence": row["confidence"],
        "warnings": json.loads(row["warnings"] or "[]"),
    }


# ---------------------------------------------------------------------------
# 入库
# ---------------------------------------------------------------------------

def _next_version_no(conn, score_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version_no), 0) + 1 AS n FROM versions WHERE score_id = ?", (score_id,)
    ).fetchone()
    return int(row["n"])


def create_score(raw: bytes, filename: str, title: str = "", composer: str = "") -> dict:
    if not raw:
        raise PipelineError("上传的文件是空的")
    is_pdf = _is_pdf(raw, filename)

    doc = None
    if not is_pdf:
        try:
            doc = mx.parse_score(raw, filename)
        except mx.MusicXmlError as exc:
            raise PipelineError(str(exc)) from exc

    score_id = _new_id("sc_")
    version_id = _new_id("v_")
    title = (title or (doc.title if doc else "") or Path(filename).stem or "未命名总谱").strip()
    composer = (composer or (doc.composer if doc else "")).strip()
    ts = store.now_iso()

    with store.db() as conn:
        conn.execute(
            "INSERT INTO scores (id, title, composer, created_at) VALUES (?,?,?,?)",
            (score_id, title, composer, ts),
        )
        conn.execute(
            """INSERT INTO versions
               (id, score_id, version_no, status, source_kind, source_name, source_path,
                musicxml_path, source_hash, title, composer, notes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                version_id, score_id, 1,
                "pending_omr" if is_pdf else "draft",
                "pdf" if is_pdf else ("mxl" if raw[:2] == b"PK" else "musicxml"),
                filename, "", "", hashlib.sha256(raw).hexdigest(),
                title, composer,
                "PDF 扫描件已入库，等待 OMR 识别结果回填" if is_pdf else "",
                ts,
            ),
        )

    suffix = ".pdf" if is_pdf else (".mxl" if raw[:2] == b"PK" else ".musicxml")
    src_path = _save_bytes(store.UPLOAD_DIR / version_id / f"source{suffix}", raw)
    with store.db() as conn:
        conn.execute("UPDATE versions SET source_path = ? WHERE id = ?", (_rel(src_path), version_id))

    if doc is not None:
        xml_bytes = mx.extract_musicxml_bytes(raw, filename)
        xml_path = _save_bytes(store.WORK_DIR / version_id / "source.musicxml", xml_bytes)
        with store.db() as conn:
            conn.execute("UPDATE versions SET musicxml_path = ? WHERE id = ?", (_rel(xml_path), version_id))
        _ingest_parts(version_id, doc)

    store.audit("upload", version_id=version_id, detail=f"{filename} ({'PDF' if is_pdf else 'MusicXML'})")
    return version_detail(version_id)


def create_version(score_id: str, raw: bytes, filename: str) -> dict:
    if not raw:
        raise PipelineError("上传的文件是空的")
    if _is_pdf(raw, filename):
        raise PipelineError("PDF 不能直接作为新版本：请先转成 MusicXML（见 PDF 待识别流程）")

    try:
        doc = mx.parse_score(raw, filename)
    except mx.MusicXmlError as exc:
        raise PipelineError(str(exc)) from exc

    with store.db() as conn:
        score = conn.execute("SELECT * FROM scores WHERE id = ?", (score_id,)).fetchone()
        if score is None:
            raise PipelineError("曲目不存在")
        version_no = _next_version_no(conn, score_id)
        version_id = _new_id("v_")
        conn.execute(
            """INSERT INTO versions
               (id, score_id, version_no, status, source_kind, source_name, source_hash,
                title, composer, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                version_id, score_id, version_no, "draft",
                "mxl" if raw[:2] == b"PK" else "musicxml",
                filename, hashlib.sha256(raw).hexdigest(),
                doc.title or score["title"], doc.composer or score["composer"], store.now_iso(),
            ),
        )

    suffix = ".mxl" if raw[:2] == b"PK" else ".musicxml"
    src_path = _save_bytes(store.UPLOAD_DIR / version_id / f"source{suffix}", raw)
    xml_bytes = mx.extract_musicxml_bytes(raw, filename)
    xml_path = _save_bytes(store.WORK_DIR / version_id / "source.musicxml", xml_bytes)
    with store.db() as conn:
        conn.execute(
            "UPDATE versions SET source_path = ?, musicxml_path = ? WHERE id = ?",
            (_rel(src_path), _rel(xml_path), version_id),
        )
    _ingest_parts(version_id, doc)
    store.audit("new-version", version_id=version_id, detail=f"v{version_no} · {filename}")
    return version_detail(version_id)


def attach_musicxml(version_id: str, raw: bytes, filename: str) -> dict:
    """给 PDF 版本回填 OMR/人工转出的 MusicXML。"""
    try:
        doc = mx.parse_score(raw, filename)
    except mx.MusicXmlError as exc:
        raise PipelineError(str(exc)) from exc

    with store.db() as conn:
        version = conn.execute("SELECT * FROM versions WHERE id = ?", (version_id,)).fetchone()
        if version is None:
            raise PipelineError("版本不存在")
        if version["status"] == "published":
            raise PipelineError("该版本已发布，不能回填；请新建版本")
        version_no = version["version_no"]

    xml_bytes = mx.extract_musicxml_bytes(raw, filename)
    xml_path = _save_bytes(store.WORK_DIR / version_id / "converted.musicxml", xml_bytes)
    _save_bytes(store.UPLOAD_DIR / version_id / _safe_name(filename or "converted.musicxml"), raw)
    with store.db() as conn:
        conn.execute(
            """UPDATE versions SET musicxml_path = ?, source_kind = 'pdf+musicxml',
               status = 'draft', title = COALESCE(NULLIF(title,''), ?),
               composer = COALESCE(NULLIF(composer,''), ?), notes = ? WHERE id = ?""",
            (_rel(xml_path), doc.title, doc.composer, "PDF 已回填 MusicXML，请核对声部映射后发布", version_id),
        )
    _ingest_parts(version_id, doc)
    store.audit("omr-attach", version_id=version_id, detail=filename)
    return version_detail(version_id)


def _ingest_parts(version_id: str, doc: mx.ScoreDocument) -> None:
    with store.db() as conn:
        conn.execute("DELETE FROM parts WHERE version_id = ?", (version_id,))
        conn.execute("DELETE FROM assignments WHERE version_id = ?", (version_id,))
        for part in doc.parts:
            conn.execute(
                """INSERT INTO parts
                   (version_id, part_id, idx, name, abbreviation, staves, voices, note_count,
                    multi_voice, extractable, suggested_role, confidence, warnings)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    version_id, part.part_id, part.index, part.name, part.abbreviation,
                    part.staves, json.dumps(part.voices, ensure_ascii=False), part.note_count,
                    int(part.multi_voice), int(part.extractable),
                    part.suggested_role, part.confidence,
                    json.dumps(part.warnings, ensure_ascii=False),
                ),
            )
            # 高置信度建议直接预填，管理员仍需人工确认
            if part.suggested_role and part.confidence >= 0.85 and part.extractable:
                conn.execute(
                    "INSERT OR IGNORE INTO assignments (version_id, role, part_id) VALUES (?,?,?)",
                    (version_id, part.suggested_role, part.part_id),
                )
        if not doc.title:
            conn.execute("UPDATE versions SET title = ? WHERE id = ? AND title = ''", ("未命名总谱", version_id))


# ---------------------------------------------------------------------------
# 映射与发布
# ---------------------------------------------------------------------------

def save_assignments(version_id: str, mapping: dict[str, list[str]]) -> dict:
    with store.db() as conn:
        version = conn.execute("SELECT * FROM versions WHERE id = ?", (version_id,)).fetchone()
        if version is None:
            raise PipelineError("版本不存在")
        if version["status"] == "published":
            raise PipelineError("已发布的版本不能改映射；请新建版本后重新发布")
        valid_parts = {r["part_id"] for r in conn.execute(
            "SELECT part_id FROM parts WHERE version_id = ?", (version_id,))}
        conn.execute("DELETE FROM assignments WHERE version_id = ?", (version_id,))
        for role, part_ids in (mapping or {}).items():
            if role not in ROLES:
                raise PipelineError(f"未知角色：{role}")
            for pid in part_ids or []:
                if pid not in valid_parts:
                    raise PipelineError(f"声部 {pid} 不属于该版本")
                conn.execute(
                    "INSERT OR IGNORE INTO assignments (version_id, role, part_id) VALUES (?,?,?)",
                    (version_id, role, pid),
                )
    store.audit("mapping-save", version_id=version_id, detail=json.dumps(mapping, ensure_ascii=False))
    return version_detail(version_id)


def publish(version_id: str, force: bool = False) -> dict:
    with store.db() as conn:
        version = conn.execute(
            """SELECT v.*, s.title AS score_title FROM versions v
               JOIN scores s ON s.id = v.score_id WHERE v.id = ?""", (version_id,)
        ).fetchone()
        if version is None:
            raise PipelineError("版本不存在")
        if version["status"] == "published":
            raise PipelineError("该版本已发布")
        if not version["musicxml_path"]:
            raise PipelineError("还没有可解析的 MusicXML：PDF 版本请先回填识别结果")
        assignments = conn.execute(
            "SELECT role, part_id FROM assignments WHERE version_id = ?", (version_id,)
        ).fetchall()
        if not assignments:
            raise PipelineError("还没有配置任何角色映射")

    parts = {p["part_id"]: p for p in _parts(version_id)}
    blocked = sorted({
        parts[a["part_id"]]["name"] for a in assignments
        if a["part_id"] in parts and not parts[a["part_id"]]["extractable"]
    })
    if blocked and not force:
        raise PipelineError(
            "以下声部在总谱里是多声部合写在一个 part 中，无法按 part 拆分："
            + "、".join(blocked)
            + "。请先在 MuseScore 里拆成独立 part，或勾选“强制发布（整段保留）”。"
        )

    doc = _load_doc(version_id)
    version_no = version["version_no"]
    title = version["title"] or version["score_title"]
    out_dir = store.ASSET_DIR / version_id
    if out_dir.exists():
        shutil.rmtree(out_dir)

    created = []
    for row in assignments:
        role, part_id = row["role"], row["part_id"]
        if part_id not in parts:
            continue
        role_name = ROLES[role]["name"]
        watermark = f"{role_name} · {title} · v{version_no} · 仅限本声部使用"
        try:
            xml = mx.extract_parts(
                doc, [part_id], watermark=watermark,
                title=title, composer=version["composer"] or "",
            )
        except mx.MusicXmlError as exc:  # pragma: no cover
            raise PipelineError(f"{parts[part_id]['name']} 导出失败：{exc}") from exc
        path = out_dir / role / f"{_safe_name(part_id)}.musicxml"
        _save_bytes(path, xml)
        digest = hashlib.sha256(xml).hexdigest()
        created.append((role, part_id, path, digest, len(xml)))

    with store.db() as conn:
        conn.execute("DELETE FROM assets WHERE version_id = ?", (version_id,))
        for role, part_id, path, digest, size in created:
            conn.execute(
                """INSERT INTO assets (version_id, role, part_id, path, sha256, size, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (version_id, role, part_id, _rel(path), digest, size, store.now_iso()),
            )
        conn.execute(
            "UPDATE versions SET status = 'published', published_at = ? WHERE id = ?",
            (store.now_iso(), version_id),
        )
    store.audit("publish", version_id=version_id, detail=f"v{version_no} · {len(created)} 份分谱")

    # 声部音频改为按需生成（见 ensure_audio）：发布不阻塞，
    # 第一次打开排练播放器时再渲染并缓存。
    return version_detail(version_id)


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------

def _parts(version_id: str) -> list[dict]:
    with store.db() as conn:
        rows = conn.execute(
            "SELECT * FROM parts WHERE version_id = ? ORDER BY idx", (version_id,)
        ).fetchall()
    return [_part_row_to_dict(r) for r in rows]


def _load_doc(version_id: str) -> mx.ScoreDocument:
    with store.db() as conn:
        row = conn.execute("SELECT musicxml_path FROM versions WHERE id = ?", (version_id,)).fetchone()
    if row is None or not row["musicxml_path"]:
        raise PipelineError("该版本没有 MusicXML 源文件")
    path = store.DATA_DIR / row["musicxml_path"]
    if not path.exists():
        raise PipelineError("MusicXML 源文件丢失")
    try:
        return mx.parse_score(path.read_bytes(), path.name)
    except mx.MusicXmlError as exc:
        raise PipelineError(str(exc)) from exc


def version_detail(version_id: str) -> dict:
    with store.db() as conn:
        version = conn.execute(
            """SELECT v.*, s.title AS score_title, s.composer AS score_composer
               FROM versions v JOIN scores s ON s.id = v.score_id WHERE v.id = ?""", (version_id,)
        ).fetchone()
        if version is None:
            raise PipelineError("版本不存在")
        rows = conn.execute(
            "SELECT * FROM parts WHERE version_id = ? ORDER BY idx", (version_id,)
        ).fetchall()
        assigned = conn.execute(
            "SELECT role, part_id FROM assignments WHERE version_id = ?", (version_id,)
        ).fetchall()
        assets = conn.execute(
            "SELECT id, role, part_id, sha256, size FROM assets WHERE version_id = ?", (version_id,)
        ).fetchall()

    role_map: dict[str, list[str]] = {role: [] for role in ROLE_ORDER}
    for row in assigned:
        role_map.setdefault(row["role"], []).append(row["part_id"])

    parts = []
    for row in rows:
        item = _part_row_to_dict(row)
        item["roles"] = sorted(r for r, pids in role_map.items() if item["part_id"] in pids)
        parts.append(item)

    return {
        "version_id": version["id"],
        "score_id": version["score_id"],
        "version_no": version["version_no"],
        "status": version["status"],
        "source_kind": version["source_kind"],
        "source_name": version["source_name"],
        "has_musicxml": bool(version["musicxml_path"]),
        "has_pdf": version["source_kind"].startswith("pdf"),
        "title": version["title"] or version["score_title"],
        "composer": version["composer"] or version["score_composer"],
        "notes": version["notes"],
        "created_at": version["created_at"],
        "published_at": version["published_at"],
        "parts": parts,
        "mapping": {r: p for r, p in role_map.items() if p},
        "unsplittable_parts": [p["name"] for p in parts if not p["extractable"]],
        "asset_count": len(assets),
        "assets": [dict(a) for a in assets],
    }


def list_scores() -> list[dict]:
    with store.db() as conn:
        scores = conn.execute("SELECT * FROM scores ORDER BY created_at DESC").fetchall()
        result = []
        for score in scores:
            versions = conn.execute(
                "SELECT id, version_no, status, published_at, source_kind FROM versions "
                "WHERE score_id = ? ORDER BY version_no DESC", (score["id"],)
            ).fetchall()
            published = next((v for v in versions if v["status"] == "published"), None)
            result.append({
                "score_id": score["id"],
                "title": score["title"],
                "composer": score["composer"],
                "created_at": score["created_at"],
                "latest_version": dict(versions[0]) if versions else None,
                "published_version": dict(published) if published else None,
                "version_count": len(versions),
            })
    return result


def library(role: str) -> dict:
    if role not in ROLES:
        raise PipelineError(f"未知角色：{role}")
    with store.db() as conn:
        versions = conn.execute(
            """SELECT DISTINCT v.*, s.title AS score_title, s.composer AS score_composer
               FROM versions v
               JOIN scores s ON s.id = v.score_id
               JOIN assets a ON a.version_id = v.id AND a.role = ?
               WHERE v.status = 'published'
               ORDER BY v.published_at DESC""", (role,)
        ).fetchall()
        items = []
        for v in versions:
            assets = conn.execute(
                """SELECT a.id, a.part_id, a.sha256, p.name AS part_name, p.abbreviation
                   FROM assets a JOIN parts p ON p.version_id = a.version_id AND p.part_id = a.part_id
                   WHERE a.version_id = ? AND a.role = ? ORDER BY p.idx""", (v["id"], role)
            ).fetchall()
            items.append({
                "version_id": v["id"],
                "score_id": v["score_id"],
                "title": v["title"] or v["score_title"],
                "composer": v["composer"] or v["score_composer"],
                "version_no": v["version_no"],
                "published_at": v["published_at"],
                "assets": [dict(a) for a in assets],
            })
    return {"role": role, "role_name": ROLES[role]["name"], "items": items}


def get_asset(asset_id: int) -> dict:
    with store.db() as conn:
        row = conn.execute(
            """SELECT a.*, v.status, v.version_no, v.title AS version_title
               FROM assets a JOIN versions v ON v.id = a.version_id WHERE a.id = ?""", (asset_id,)
        ).fetchone()
    if row is None:
        raise PipelineError("分谱不存在")
    return dict(row)


def asset_file(asset_id: int) -> tuple[dict, Path]:
    row = get_asset(asset_id)
    path = store.DATA_DIR / row["path"]
    if not path.exists():
        raise PipelineError("分谱文件丢失，请重新发布该版本")
    return row, path


def sign_download(asset_id: int, role: str, ip: str = "", ttl_seconds: int = 600) -> dict:
    row = get_asset(asset_id)
    token = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    with store.db() as conn:
        conn.execute(
            "INSERT INTO tokens (token, asset_id, role, expires_at, created_at) VALUES (?,?,?,?,?)",
            (token, asset_id, role, expires.replace(microsecond=0).isoformat(), store.now_iso()),
        )
    store.audit("sign", role=role, version_id=row["version_id"], part_id=row["part_id"], ip=ip)
    return {"token": token, "url": f"/api/dl/{token}", "expires_at": expires.replace(microsecond=0).isoformat()}


def resolve_token(token: str) -> tuple[dict, Path]:
    with store.db() as conn:
        row = conn.execute("SELECT * FROM tokens WHERE token = ?", (token,)).fetchone()
    if row is None:
        raise PipelineError("下载链接无效")
    if row["expires_at"] < store.now_iso():
        raise PipelineError("下载链接已过期，请回到页面重新获取")
    return asset_file(int(row["asset_id"]))


# ---------------------------------------------------------------------------
# 声部音频（排练用多轨播放）
# ---------------------------------------------------------------------------

def _audio_rows(version_id: str) -> dict[str, dict]:
    with store.db() as conn:
        rows = conn.execute(
            "SELECT * FROM part_audio WHERE version_id = ?", (version_id,)
        ).fetchall()
    return {row["part_id"]: dict(row) for row in rows}


def ensure_audio(version_id: str, *, force: bool = False) -> dict[str, dict]:
    """给每个 part 生成一条独立音轨；已经生成且文件还在的直接复用。

    所有声部都用同一份速度表（`mx.collect_tempos`），并共享同一段总时长，
    这样前端从同一时刻起播就能对齐。
    """
    with store.db() as conn:
        version = conn.execute("SELECT * FROM versions WHERE id = ?", (version_id,)).fetchone()
    if version is None:
        raise PipelineError("版本不存在")
    if not version["musicxml_path"]:
        raise PipelineError("该版本还没有可解析的 MusicXML，无法生成音频")
    if not audio_service.dependencies_available():
        raise PipelineError("服务端缺少音频生成依赖（verovio / mido / lameenc / numpy）")

    parts = _parts(version_id)
    if not parts:
        return {}

    existing = _audio_rows(version_id)
    missing = [
        part for part in parts
        if force
        or part["part_id"] not in existing
        or not (store.DATA_DIR / existing[part["part_id"]]["path"]).exists()
    ]
    if not missing:
        return existing

    doc = _load_doc(version_id)
    tempos = mx.collect_tempos(doc)
    out_dir = store.AUDIO_DIR / version_id
    rendered = 0

    for part in missing:
        try:
            xml = mx.extract_parts(
                doc,
                [part["part_id"]],
                tempos=tempos,
                title=version["title"] or "",
                composer=version["composer"] or "",
            )
            mp3, duration, note_count = audio_service.render_part_audio(xml)
        except Exception as exc:  # 单声部失败不影响其它声部
            print(f"[audio] {part['part_id']} {part['name']} 生成失败：{exc}")
            continue

        path = _save_bytes(out_dir / f"{_safe_name(part['part_id'])}.mp3", mp3)
        with store.db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO part_audio
                   (version_id, part_id, path, mime, sha256, size, duration, note_count, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (version_id, part["part_id"], _rel(path), "audio/mpeg",
                 hashlib.sha256(mp3).hexdigest(), len(mp3), duration, note_count,
                 store.now_iso()),
            )
        rendered += 1

    if rendered:
        store.audit("audio-render", version_id=version_id, detail=f"{rendered} 条声部音轨")
    return _audio_rows(version_id)


def playlist(version_id: str) -> dict:
    """播放列表：一个版本里全部声部的音轨信息（不分角色，所有用户看到的都一样）。"""
    rows = ensure_audio(version_id)
    with store.db() as conn:
        version = conn.execute(
            """SELECT v.*, s.title AS score_title, s.composer AS score_composer
               FROM versions v JOIN scores s ON s.id = v.score_id WHERE v.id = ?""",
            (version_id,),
        ).fetchone()
        if version is None:
            raise PipelineError("版本不存在")
        assigned = conn.execute(
            "SELECT role, part_id FROM assignments WHERE version_id = ?", (version_id,)
        ).fetchall()

    roles_by_part: dict[str, list[str]] = {}
    for row in assigned:
        roles_by_part.setdefault(row["part_id"], []).append(row["role"])

    items = []
    for part in _parts(version_id):
        row = rows.get(part["part_id"])
        items.append({
            "part_id": part["part_id"],
            "name": part["name"],
            "abbreviation": part["abbreviation"],
            "roles": sorted(roles_by_part.get(part["part_id"], [])),
            "suggested_role": part["suggested_role"],
            "staves": part["staves"],
            "note_count": part["note_count"],
            "extractable": part["extractable"],
            "available": row is not None,
            "duration": row["duration"] if row else 0.0,
            "size": row["size"] if row else 0,
            "audio_url": f"/api/audio/{version_id}/{part['part_id']}" if row else None,
        })

    return {
        "version_id": version_id,
        "version_no": version["version_no"],
        "status": version["status"],
        "title": version["title"] or version["score_title"],
        "composer": version["composer"] or version["score_composer"],
        "duration": max([item["duration"] for item in items] or [0.0]),
        "parts": items,
    }


def audio_file(version_id: str, part_id: str) -> tuple[dict, Path]:
    rows = _audio_rows(version_id)
    row = rows.get(part_id)
    if row is None or not (store.DATA_DIR / row["path"]).exists():
        rows = ensure_audio(version_id)  # 懒生成：老数据/首次访问
        row = rows.get(part_id)
    if row is None:
        raise PipelineError("该声部还没有音频（可能没有音符，或生成失败）")
    path = store.DATA_DIR / row["path"]
    if not path.exists():
        raise PipelineError("音频文件丢失，请重新生成")
    return row, path


def recent_audit(limit: int = 50) -> list[dict]:
    with store.db() as conn:
        rows = conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def pdf_path(version_id: str) -> Path:
    with store.db() as conn:
        row = conn.execute("SELECT source_path, source_kind FROM versions WHERE id = ?", (version_id,)).fetchone()
    if row is None or not row["source_path"] or not row["source_kind"].startswith("pdf"):
        raise PipelineError("该版本没有 PDF 原件")
    path = store.DATA_DIR / row["source_path"]
    if not path.exists():
        raise PipelineError("PDF 原件丢失")
    return path


def stats() -> dict:
    with store.db() as conn:
        counts = {t: conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"]
                  for t in ("scores", "versions", "parts", "assets", "audit")}
    return counts
