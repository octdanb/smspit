import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import internal_api, lookup_v2, messaging_v1, phone_numbers, twilio_api, verify_v2, ws
from .config import config
from .db import init_db
from .errors import TwilioError, twilio_error_handler
from .lifecycle import resume_pending
from .retention import purge_loop


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
        if config.dashboard_token and path.startswith("/api") and path != "/api/health":
            token = request.headers.get("X-Smspit-Token") or request.query_params.get("token")
            if token != config.dashboard_token:
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

    # Serve the built frontend when present (production container); in dev, Vite serves it.
    static_dir = config.static_dir
    if (static_dir / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = static_dir / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
