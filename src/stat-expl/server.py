"""Minimal FastAPI server with Vite React build"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="stat-expl-minimal")

@app.get("/dashboard/api/health")
def health():
    return {"status": "ok", "app": "stat-expl-minimal", "version": "0.0.3"}

# Mount Vite build at root
_DIST_DIR = Path(__file__).parent / "dist"
if _DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_DIST_DIR), html=True), name="frontend")
