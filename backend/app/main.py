"""FastAPI 入口：API + 已构建前端静态资源。"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import store
from .api import router
from .seed import seed_demo

BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIST = Path(os.environ.get("CHOIR_WEB_DIST", BASE_DIR.parent / "frontend" / "dist"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    seed_demo()
    print(f"[choirparts] data={store.DATA_DIR}  web={WEB_DIST} (exists={WEB_DIST.exists()})")
    yield


app = FastAPI(title="ChoirParts · 合唱团分谱分发", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

if (WEB_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "not found"}, status_code=404)
    index = WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index, media_type="text/html")
    return JSONResponse(
        {
            "detail": "前端还没构建。请在 frontend/ 下执行 npm run build，或 npm run dev 后在 5173 端口访问。"
        },
        status_code=503,
    )
