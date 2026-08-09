FROM node:22-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    YIOPS_ENVIRONMENT=production

WORKDIR /app

COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/app/ /app/backend/app/
COPY backend/migrations/ /app/backend/migrations/
COPY evals/scenarios/ /app/evals/scenarios/
COPY backend/docker-entrypoint.sh /app/backend/docker-entrypoint.sh
RUN pip install --no-cache-dir /app/backend \
    && groupadd --system yiops \
    && useradd --system --gid yiops --home-dir /app yiops \
    && mkdir -p /app/.runtime /app/logs \
    && chmod +x /app/backend/docker-entrypoint.sh \
    && chown -R yiops:yiops /app

COPY --from=frontend-build --chown=yiops:yiops /build/frontend/dist/ /app/frontend/dist/

USER yiops
WORKDIR /app/backend

EXPOSE 8100 8110

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/api/v1/health/ready', timeout=3)"]

CMD ["./docker-entrypoint.sh"]
