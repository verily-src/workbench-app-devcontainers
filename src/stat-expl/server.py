"""
FastAPI server to serve the built React SPA.
Uses FastAPI with StaticFiles for proper SPA routing.
CRITICAL: Workbench reserves /api/ - use /dashboard/api/ prefix instead.
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

@app.get("/dashboard/api/health")
def health():
    return {
        "status": "ok",
        "app": "stat-expl",
        "version": "0.1.0"
    }

# Serve the built frontend at the app root. Static mounts are registered
# LAST so /dashboard/api/* takes precedence. Using StaticFiles(html=True) makes it serve
# index.html for the root and fall through for asset paths.
_FRONTEND_DIST = Path(__file__).resolve().parent / "dist"
if _FRONTEND_DIST.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIST), html=True),
        name="frontend",
    )
