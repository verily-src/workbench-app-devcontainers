FROM python:3.11-slim

RUN groupadd -r appuser && useradd -r -g appuser -d /home/appuser -m appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R appuser:appuser /app

EXPOSE 8501
USER appuser

# launcher.py fetches the latest copy of the app, then starts Streamlit.
# Streamlit settings live in .streamlit/config.toml.
CMD ["python", "launcher.py"]
