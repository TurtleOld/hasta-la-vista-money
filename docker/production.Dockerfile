ARG PYTHON_VERSION=3.13.9
ARG NODE_VERSION=20
ARG UV_VERSION=0.7.13

FROM node:${NODE_VERSION}-alpine AS node-builder
ARG NODE_VERSION
WORKDIR /app
COPY theme/static_src/package.json theme/static_src/package-lock.json ./theme/static_src/
WORKDIR /app/theme/static_src
RUN npm ci
COPY theme/static_src/ ./
WORKDIR /app
COPY hasta_la_vista_money/ ./hasta_la_vista_money/
COPY config/ ./config/
COPY core/ ./core/
COPY static/ ./static/
WORKDIR /app/theme/static_src
RUN npm run build

FROM python:${PYTHON_VERSION}-slim AS py-builder
ARG PYTHON_VERSION
ARG UV_VERSION
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential gcc ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==${UV_VERSION}
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY . .
COPY --from=node-builder /app/static/css/styles.min.css /app/static/css/styles.min.css
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:${PYTHON_VERSION}-slim AS runtime
ARG PYTHON_VERSION
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}"
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN adduser --disabled-password --gecos '' appuser
COPY --from=py-builder /opt/venv /opt/venv
COPY --from=py-builder /app /app
RUN mkdir -p /app/staticfiles /app/logs && \
    chown -R appuser:appuser /app /app/staticfiles /app/logs
USER appuser
COPY --chown=appuser:appuser docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["granian", "--interface", "asgi", "config.asgi:application", "--port", "8001", "--host", "0.0.0.0"]