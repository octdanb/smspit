# Stage 1: build the React dashboard
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime serving API + static dashboard
FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir .
COPY --from=frontend /build/dist ./static

ENV SMSPIT_STATIC_DIR=/app/static \
    SMSPIT_DB_PATH=/data/smspit.db

EXPOSE 8025
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8025"]
