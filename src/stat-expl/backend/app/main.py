"""Dataset Statistical Explorer - FastAPI server"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="Dataset Statistical Explorer",
    version="1.0.0",
    description="5-page biostatistics workspace for dataset fitness assessment"
)

@app.get("/dashboard/api/health")
def health():
    return {"status": "ok", "app": "stat-expl", "version": "1.0.0"}

# Mount Vite build at root
# Path: /app/backend/app/main.py -> /app/frontend/dist
_DIST_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_DIST_DIR), html=True), name="frontend")
