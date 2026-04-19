from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration."""

    env: str = "dev"
    bhs_project: str = "wb-spotless-eggplant-4340"
    app_project: str = "wb-spotless-eggplant-4340"
    use_demo_tables: bool = True

    # BigQuery cost guardrails
    bq_max_bytes_billed: int = 2_000_000_000_000  # 2 TB for demo

    class Config:
        env_file = ".env"
        env_prefix = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
