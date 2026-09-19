from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import socket
import threading
import time
import uuid
import webbrowser
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ai_workflow.errors import AppError

from ai_workflow_gui import __version__
from ai_workflow_gui.agent_runner import AgentDriver
from ai_workflow_gui.config_store import DEFAULT_CONFIG_PATH
from ai_workflow_gui.routes import admin, knowledge, repos, runs

STATIC_DIR = Path(__file__).resolve().parent / "static"

logger = logging.getLogger("ai_workflow_gui")

_CONFLICT_CODES = {
    "state_exists",
    "immutable_conflict",
    "stale_review_gate",
    "stale_state",
    "review_gate_required",
    "review_gate_mismatch",
    "wiki_conflict",
    "driver_busy",
    "driver_gate_pending",
}


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    target = log_dir / "gui.log"
    if any(
        isinstance(handler, RotatingFileHandler) and handler.baseFilename == str(target)
        for handler in logger.handlers
    ):
        return
    handler = RotatingFileHandler(target, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def status_for(code: str) -> int:
    if code.endswith("not_found") or code == "invalid_run_id":
        return 404
    if code in _CONFLICT_CODES:
        return 409
    if (
        code.startswith("config_")
        or code.startswith("invalid_")
        or code == "repository_required"
        or code == "agent_spawn_failed"
    ):
        return 400
    return 500


def create_app(
    *,
    config_path: Path | None = None,
    home: Path | None = None,
    allowed_hosts: tuple[str, ...] | None = None,
) -> FastAPI:
    app = FastAPI(title="ai-workflow GUI", version=__version__)
    app.state.config_path = config_path or DEFAULT_CONFIG_PATH
    app.state.home = home or Path.home()
    app.state.driver = AgentDriver(
        log_dir=app.state.home / ".ai-workflow-gui" / "agent-logs"
    )
    setup_logging(app.state.home / ".ai-workflow-gui" / "logs")

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        request_id = uuid.uuid4().hex[:8]
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "rid=%s %s %s crashed", request_id, request.method, request.url.path
            )
            raise
        if request.url.path.startswith("/api"):
            logger.info(
                "rid=%s %s %s -> %s %.0fms",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                (time.perf_counter() - start) * 1000,
            )
        response.headers["X-Request-Id"] = request_id
        return response

    if allowed_hosts is not None:

        @app.middleware("http")
        async def host_guard(request: Request, call_next):
            host = (request.headers.get("host") or "").lower()
            if host not in allowed_hosts:
                return JSONResponse(
                    {"code": "host_not_allowed", "message": "host header rejected"},
                    status_code=403,
                )
            return await call_next(request)

    app.include_router(repos.router)
    app.include_router(repos.settings_router)
    app.include_router(runs.router)
    app.include_router(knowledge.router)
    app.include_router(admin.router)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, error: AppError):
        logger.warning(
            "rid=%s app_error code=%s message=%s",
            getattr(request.state, "request_id", "-"),
            error.code,
            error.message,
        )
        return JSONResponse(
            {
                "code": error.code,
                "message": error.message,
                "details": error.details,
                "request_id": getattr(request.state, "request_id", None),
            },
            status_code=status_for(error.code),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, error: Exception):
        request_id = getattr(request.state, "request_id", "-")
        logger.exception("rid=%s unhandled %s", request_id, type(error).__name__)
        return JSONResponse(
            {
                "code": "internal_error",
                "message": "internal error; see gui.log",
                "request_id": request_id,
            },
            status_code=500,
        )

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

        @app.exception_handler(StarletteHTTPException)
        async def spa_fallback(request: Request, error: StarletteHTTPException):
            index = STATIC_DIR / "index.html"
            if (
                error.status_code == 404
                and request.method == "GET"
                and not request.url.path.startswith("/api")
                and index.is_file()
            ):
                return FileResponse(index)
            return JSONResponse(
                {"code": "http_error", "message": str(error.detail)},
                status_code=error.status_code,
            )

    return app


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    import uvicorn

    port = free_port()
    app = create_app(
        allowed_hosts=(f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}")
    )
    url = f"http://127.0.0.1:{port}"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
