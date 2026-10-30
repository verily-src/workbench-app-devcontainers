FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user; /data holds the cached documentation index.
RUN useradd --system --create-home app && mkdir -p /data && chown -R app:app /app /data
USER app

EXPOSE 8080

# One worker keeps a single in-memory index; threads handle concurrent chats.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "--timeout", "180", "app:app"]
