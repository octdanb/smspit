import os
from pathlib import Path


class Config:
    """Environment-driven configuration."""

    port: int = int(os.environ.get("SMSPIT_PORT", "8025"))
    db_path: Path = Path(os.environ.get("SMSPIT_DB_PATH", "./data/smspit.db"))
    # Directory containing the built frontend (served as static files when present).
    static_dir: Path = Path(os.environ.get("SMSPIT_STATIC_DIR", "./static"))


config = Config()
