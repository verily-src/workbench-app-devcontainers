FROM python:3.11-slim

RUN groupadd -r appuser && useradd -r -g appuser -d /home/appuser -m appuser

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl fuse \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create directories for file processing
RUN mkdir -p /app/uploads /app/processed /app/schemas && \
    chown -R appuser:appuser /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .
RUN chown -R appuser:appuser /app /home/appuser

EXPOSE 8080
USER appuser

CMD ["python", "main.py"]
