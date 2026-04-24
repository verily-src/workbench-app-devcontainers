"""Absolute minimum FastAPI server - health endpoint only"""
from fastapi import FastAPI

app = FastAPI(title="stat-expl-minimal")

@app.get("/dashboard/api/health")
def health():
    return {"status": "ok", "app": "stat-expl-minimal", "version": "0.0.1"}

@app.get("/")
def root():
    return {"message": "stat-expl minimal debug server running"}
