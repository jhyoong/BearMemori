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

# Expose the FastAPI port
EXPOSE 8000

# Run uvicorn server
# Uses module notation to run core.main:app
CMD ["python", "-m", "uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8000"]
