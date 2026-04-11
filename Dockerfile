FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install the project itself
COPY bearmemori/ bearmemori/
RUN uv sync --frozen --no-dev --no-editable


FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH"

# Default data directory for SQLite, ChromaDB, and HuggingFace model cache
RUN mkdir -p /data
ENV DATABASE_PATH=/data/bearmemori.db
ENV CHROMA_PERSIST_DIR=/data/chroma
ENV IMAGE_STORAGE_DIR=/data/images
ENV HF_HOME=/data/hf_cache

EXPOSE 8100

CMD ["python", "-m", "bearmemori"]
