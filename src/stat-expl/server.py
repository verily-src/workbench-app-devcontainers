"""Minimal FastAPI server with StaticFiles serving"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="stat-expl-minimal")

@app.get("/dashboard/api/health")
def health():
    return {"status": "ok", "app": "stat-expl-minimal", "version": "0.0.2"}

# Mount static files at root
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
