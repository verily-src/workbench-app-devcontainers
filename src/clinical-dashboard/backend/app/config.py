from functools import lru_cache
from pydantic_settings import BaseSettings
import os


class Settings(BaseSettings):
    """Application configuration."""

    env: str = "dev"
    bhs_project: str = "wb-spotless-eggplant-4340"  # Where BHS data lives

    # Workbench sets GOOGLE_CLOUD_PROJECT in deployed containers
    # Fall back to wb-rapid-apricot-2196 for local dev
    app_project: str = os.getenv("GOOGLE_CLOUD_PROJECT", "wb-rapid-apricot-2196")

    use_demo_tables: bool = True

    # BigQuery cost guardrails
    bq_max_bytes_billed: int = 2_000_000_000_000  # 2 TB for demo

    class Config:
        env_file = ".env"
        env_prefix = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
