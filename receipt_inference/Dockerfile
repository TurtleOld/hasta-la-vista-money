FROM python:3.12-slim AS llama-builder

ARG LLAMA_CPP_REF=master

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp

RUN git clone --depth 1 --branch "$LLAMA_CPP_REF" \
    https://github.com/ggml-org/llama.cpp.git

RUN cmake -S /tmp/llama.cpp -B /tmp/llama.cpp/build \
    -DBUILD_SHARED_LIBS=OFF \
    -DGGML_NATIVE=OFF \
    -DGGML_OPENMP=ON \
    -DLLAMA_BUILD_SERVER=ON && \
    cmake --build /tmp/llama.cpp/build --target llama-server -j"$(nproc)"

FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install uv==0.7.13 \
    && adduser --disabled-password --gecos '' appuser

ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:/usr/local/bin:/home/appuser/.local/bin:$PATH"

WORKDIR /app/receipt_inference

RUN mkdir -p /opt/venv /models && \
    chown -R appuser:appuser /app /opt/venv /models

COPY --from=llama-builder /tmp/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server

COPY --chown=appuser:appuser receipt_inference/pyproject.toml ./pyproject.toml

USER appuser

RUN --mount=type=cache,target=/tmp/uv-cache,uid=1000,gid=1000 \
    UV_CACHE_DIR=/tmp/uv-cache uv lock && \
    UV_CACHE_DIR=/tmp/uv-cache uv sync --no-dev

COPY --chown=appuser:appuser receipt_inference/ ./

RUN chmod +x /app/receipt_inference/entrypoint.sh

ENV LLAMA_SERVER_URL=http://127.0.0.1:8080/v1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["/app/receipt_inference/entrypoint.sh"]
