FROM python:3.12-slim

WORKDIR /app

# Install curl for health checks
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Copy and install shared package first (dependency of core)
COPY shared/ /app/shared/
RUN pip install --no-cache-dir -e /app/shared/

# Copy and install core package
COPY core/ /app/core/
RUN pip install --no-cache-dir -e /app/core/

# Create data directories for database and images
# These will be mounted as volumes in docker-compose
RUN mkdir -p /data/db /data/images

# Expose the FastAPI port (informational; actual port comes from CORE_PORT env var)
EXPOSE ${CORE_PORT:-8000}

# Run uvicorn server; shell form so CORE_HOST and CORE_PORT are expanded at runtime
CMD python -m uvicorn core_svc.main:app --host ${CORE_HOST:-0.0.0.0} --port ${CORE_PORT:-8000}
