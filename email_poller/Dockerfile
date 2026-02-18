FROM python:3.12-slim
WORKDIR /app
COPY email_poller/ /app/email_poller/
RUN pip install --no-cache-dir -e /app/email_poller/
CMD ["python", "-m", "poller.main"]
