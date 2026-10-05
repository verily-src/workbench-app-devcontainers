FROM mcr.microsoft.com/vscode/devcontainers/python:3.12-bookworm
WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .
EXPOSE 8080
CMD ["panel", "serve", "main.py", \
     "--address", "0.0.0.0", "--port", "8080", \
     "--allow-websocket-origin", "*", \
     "--index", "main", \
     "--liveness"]
