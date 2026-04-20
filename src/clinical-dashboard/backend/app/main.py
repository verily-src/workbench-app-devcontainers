from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Cohort Multimodal Dashboard",
    version="0.1.0",
    description="Interactive dashboard for cohort-based multimodal analysis",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "message": "Backend is running - routes will be added incrementally"
    }


@app.get("/")
def root():
    return {
        "message": "Cohort Multimodal Dashboard API",
        "endpoints": ["/api/health"]
    }
