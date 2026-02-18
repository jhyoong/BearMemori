FROM python:3.12-slim
WORKDIR /app
COPY llm_worker/ /app/llm_worker/
RUN pip install --no-cache-dir -e /app/llm_worker/
CMD ["python", "-m", "worker.main"]
