import os
from pathlib import Path


def _load_dotenv() -> None:
    """Minimal .env loader (KEY=VALUE lines) so local dev needs no exports.

    Real environment variables always win; we never overwrite them. Kept
    dependency-free on purpose — this is the only place we read .env.
    """
    env_file = Path(os.environ.get("SMSPIT_ENV_FILE", ".env"))
    if not env_file.is_file():
        return
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


class Config:
    """Environment-driven configuration."""

    port: int = int(os.environ.get("SMSPIT_PORT", "8025"))
    db_path: Path = Path(os.environ.get("SMSPIT_DB_PATH", "./data/smspit.db"))
    # Directory containing the built frontend (served as static files when present).
    static_dir: Path = Path(os.environ.get("SMSPIT_STATIC_DIR", "./static"))
    # Optional dashboard auth: when set, /api requests must carry this token
    # (X-Smspit-Token header or ?token=). Twilio-shaped routes are unaffected.
    dashboard_token: str = os.environ.get("SMSPIT_DASHBOARD_TOKEN", "")
    # Build version, stamped into the image at build time; shown in the dashboard.
    version: str = os.environ.get("SMSPIT_VERSION", "dev")
    # SSRF guard: by default the server refuses to fetch MediaUrls that resolve
    # to private/loopback/link-local addresses (protects shared UAT instances).
    # Set truthy for single-machine local dev that serves media from localhost.
    allow_private_media: bool = os.environ.get("SMSPIT_ALLOW_PRIVATE_MEDIA", "").lower() in (
        "1",
        "true",
        "yes",
    )


config = Config()
