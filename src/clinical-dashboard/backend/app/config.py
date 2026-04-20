from functools import lru_cache
from pydantic_settings import BaseSettings
import subprocess


def get_gcp_project() -> str:
    """Auto-detect current GCP project."""
    try:
        result = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        project = result.stdout.strip()
        return project if project else "wb-rapid-apricot-2196"
    except Exception:
        return "wb-rapid-apricot-2196"


class Settings(BaseSettings):
    """Application configuration."""

    env: str = "dev"
    bhs_project: str = "wb-spotless-eggplant-4340"  # Where BHS data lives
    app_project: str = get_gcp_project()  # Current workspace project
    use_demo_tables: bool = True

    # BigQuery cost guardrails
    bq_max_bytes_billed: int = 2_000_000_000_000  # 2 TB for demo

    class Config:
        env_file = ".env"
        env_prefix = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
