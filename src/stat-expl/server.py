"""
FastAPI server to serve the built React SPA.
Uses FastAPI with StaticFiles for proper SPA routing.
Pattern from clinical-dashboard.
"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app = FastAPI(
    title="Dataset Statistical Explorer",
    version="0.1.0",
    description="5-page biostatistics workspace for dataset fitness assessment",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": "stat-expl",
        "version": "0.1.0"
    }

# Serve the built frontend at the app root
# html=True makes it serve index.html for all routes (SPA routing)
# Only mount if dist exists AND has content (not just empty dir)
_FRONTEND_DIST = Path(__file__).resolve().parent / "dist"
if _FRONTEND_DIST.exists() and any(_FRONTEND_DIST.iterdir()):
    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIST), html=True),
        name="frontend",
    )
