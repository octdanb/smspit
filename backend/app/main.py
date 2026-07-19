import asyncio
from contextlib import asynccontextmanager, suppress
from hmac import compare_digest

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import internal_api, lookup_v2, messaging_v1, phone_numbers, twilio_api, verify_v2, ws
from .config import config
from .db import init_db
from .errors import TwilioError, twilio_error_handler
from .lifecycle import resume_pending
from .retention import purge_loop

# Always reachable even on a token-protected instance: probes and the app
# under test need health, and the version banner loads before the token gate.
_OPEN_API_PATHS = {"/api/health", "/api/version"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    resume_pending()
    purge_task = asyncio.create_task(purge_loop())
    yield
    purge_task.cancel()
    with suppress(asyncio.CancelledError):
        await purge_task


def create_app() -> FastAPI:
    app = FastAPI(title="smspit", lifespan=lifespan)
    app.add_exception_handler(TwilioError, twilio_error_handler)

    @app.middleware("http")
    async def dashboard_auth(request: Request, call_next):
        # Optional token on the internal API only; Twilio-shaped routes keep
        # their own auth story, and /api/health stays open for probes.
        path = request.url.path
        if config.dashboard_token and path.startswith("/api") and path not in _OPEN_API_PATHS:
            token = request.headers.get("X-Smspit-Token") or request.query_params.get("token")
            if not token or not compare_digest(token, config.dashboard_token):
                return JSONResponse(status_code=401, content={"detail": "Dashboard token required"})
        return await call_next(request)

    app.include_router(twilio_api.router)
    app.include_router(phone_numbers.router)
    app.include_router(messaging_v1.router)
    app.include_router(verify_v2.router)
    app.include_router(lookup_v2.router)
    app.include_router(internal_api.router)
    app.include_router(ws.router)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "service": "smspit"}

    @app.get("/api/version")
    def version() -> dict:
        return {"version": config.version}

    # Serve the built frontend when present (production container); in dev, Vite serves it.
    static_dir = config.static_dir
    if (static_dir / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        static_root = static_dir.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = (static_dir / path).resolve()
            # Containment check: a "../" path must not escape the static root.
            if path and candidate.is_relative_to(static_root) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
