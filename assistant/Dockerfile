FROM python:3.12-slim
WORKDIR /app
COPY shared/ /app/shared/
RUN pip install --no-cache-dir -e /app/shared/
COPY assistant/ /app/assistant/
RUN pip install --no-cache-dir -e /app/assistant/
CMD ["python", "-m", "assistant_svc.main"]
