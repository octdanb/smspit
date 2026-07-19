# Stage 1: build the React dashboard with pnpm (pinned via packageManager)
FROM node:22-alpine AS frontend
ENV CI=true
RUN corepack enable
WORKDIR /build
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm run build

# Stage 2: Python runtime serving API + static dashboard
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    SMSPIT_STATIC_DIR=/app/static \
    SMSPIT_DB_PATH=/data/smspit.db

# Install dependencies from the lockfile first (cached across code changes),
# then the project itself — reproducible, unlike a loose `pip install .`.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev
COPY --from=frontend /build/dist ./static

# Run as an unprivileged user; /data is a volume it must own.
RUN useradd --system --uid 10001 smspit \
    && mkdir -p /data \
    && chown -R smspit:smspit /app /data
USER smspit

ARG SMSPIT_VERSION=dev
ENV SMSPIT_VERSION=$SMSPIT_VERSION

LABEL org.opencontainers.image.title="smspit" \
      org.opencontainers.image.description="Mailpit, but for SMS — a Twilio-emulating SMS testing tool" \
      org.opencontainers.image.source="https://github.com/octdanb/octavenz-smspit" \
      org.opencontainers.image.licenses="MIT"

EXPOSE 8025
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8025/api/health').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8025"]
