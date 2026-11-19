FROM python:3.11-slim

RUN groupadd -r appuser && useradd -r -g appuser -d /home/appuser -m appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R appuser:appuser /app

EXPOSE 8501
USER appuser

# Other Streamlit settings live in .streamlit/config.toml.
CMD ["streamlit", "run", "main.py", "--server.port=8501", "--server.address=0.0.0.0"]
