"""Command Server API process. Run with:  uv run uvicorn app.main:app

The scheduler runs inside this process as a background task; leadership is
decided by a database lease, so running several API processes is safe.
"""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.deps import user_from_token
from app.api.v1 import admin, public, workspace
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.session import async_sessions, create_tables
from app.realtime.gateway import gateway
from scheduler.loop import SchedulerTask


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    create_tables()
    await gateway.start()
    scheduler = SchedulerTask()
    scheduler.start()
    yield
    await scheduler.stop()
    await gateway.stop()


app = FastAPI(
    title="Iron Curtain Command Server",
    version="1.0.0",
    lifespan=lifespan,
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"],
                   allow_headers=["*"])
install_error_handlers(app)

api = APIRouter(prefix="/api/v1")
api.include_router(public.router)
api.include_router(workspace.router)
api.include_router(admin.router)


@api.get("/healthz", tags=["health"])
async def healthz():
    return {"ok": True}


@api.get("/readyz", tags=["health"])
async def readyz():
    try:
        async with async_sessions()() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"ok": False}, status_code=503)
    return {"ok": True}


@api.websocket("/ws")
async def websocket(ws: WebSocket, token: str = Query(), after: int | None = Query(default=None)):
    async with async_sessions()() as session:
        user = await user_from_token(session, token)
    if user is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    await gateway.serve(ws, user, after)


app.include_router(api)

# Serve the built Field Client, so a single port runs the whole event
_dist = get_settings().client_dist
if (_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def client(path: str):
        file = (_dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(_dist.resolve()):
            return FileResponse(file)
        return FileResponse(_dist / "index.html")
