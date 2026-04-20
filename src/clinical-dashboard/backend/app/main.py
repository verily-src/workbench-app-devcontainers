from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .routers import cohorts, device_data, clinical_data

settings = get_settings()

app = FastAPI(
    title="Cohort Multimodal Dashboard",
    version="0.1.0",
    description="Interactive dashboard for cohort-based multimodal analysis",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.env == "dev" else [],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cohorts.router, prefix="/api/cohorts", tags=["cohorts"])
app.include_router(device_data.router, prefix="/api/device-data", tags=["device-data"])
app.include_router(clinical_data.router, prefix="/api/clinical-data", tags=["clinical-data"])


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "env": settings.env,
        "bhs_project": settings.bhs_project,
        "app_project": settings.app_project,
        "use_demo_tables": settings.use_demo_tables,
    }


# Serve the built frontend at the app root
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIST), html=True),
        name="frontend",
    )
