from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import internal_api, twilio_api, verify_v2, ws
from .config import config
from .db import init_db
from .errors import TwilioError, twilio_error_handler
from .lifecycle import resume_pending


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    resume_pending()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="smspit", lifespan=lifespan)
    app.add_exception_handler(TwilioError, twilio_error_handler)
    app.include_router(twilio_api.router)
    app.include_router(verify_v2.router)
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
