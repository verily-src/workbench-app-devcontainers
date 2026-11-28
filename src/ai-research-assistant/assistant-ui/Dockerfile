# The NVIDIA AI Research Assistant's page and its server (README.md). Runs in the app
# container's network namespace, behind Caddy.
FROM python:3.12-slim

WORKDIR /opt/assistant-ui
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py settings.py record_replay.py demo.yaml ./
COPY static ./static
COPY examples ./examples

USER nobody
CMD ["python3", "-u", "server.py"]
