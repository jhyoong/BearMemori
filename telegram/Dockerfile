FROM python:3.12-slim
WORKDIR /app
COPY telegram/ /app/telegram/
RUN pip install --no-cache-dir -e /app/telegram/
CMD ["python", "-m", "tg_gateway.main"]
