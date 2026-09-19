from __future__ import annotations

import socket
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ai_workflow.errors import AppError

from ai_workflow_gui import __version__
from ai_workflow_gui.config_store import DEFAULT_CONFIG_PATH
from ai_workflow_gui.routes import admin, knowledge, repos, runs

STATIC_DIR = Path(__file__).resolve().parent / "static"

_CONFLICT_CODES = {
    "state_exists",
    "immutable_conflict",
    "stale_review_gate",
    "stale_state",
    "review_gate_required",
    "review_gate_mismatch",
    "wiki_conflict",
}


def status_for(code: str) -> int:
    if code.endswith("not_found") or code == "invalid_run_id":
        return 404
    if code in _CONFLICT_CODES:
        return 409
    if code.startswith("config_") or code.startswith("invalid_") or code == "repository_required":
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
        return JSONResponse(
            {
                "code": error.code,
                "message": error.message,
                "details": error.details,
            },
            status_code=status_for(error.code),
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
