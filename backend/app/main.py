from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import config
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="smspit", lifespan=lifespan)

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
