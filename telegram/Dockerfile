FROM python:3.12-slim

WORKDIR /app

# Install shared package first (changes less frequently)
COPY shared/ /app/shared/
RUN pip install --no-cache-dir -e /app/shared/

# Install telegram package
COPY telegram/ /app/telegram/
RUN pip install --no-cache-dir -e /app/telegram/

CMD ["python", "-m", "tg_gateway.main"]
