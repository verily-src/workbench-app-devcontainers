"""Configuration management for the Streamlit NL-to-SQL application."""

import os
from dataclasses import dataclass, field
from typing import Optional, List
import requests


@dataclass
class AppConfig:
    """Application configuration with GCP and security settings."""

    # GCP Configuration
    project_id: str
    location: str = "us-central1"

    # BigQuery Configuration
    max_query_size_kb: int = 100
    query_timeout_seconds: int = 30
    max_results: int = 10000
    max_bytes_billed: int = 10 * 1024 * 1024 * 1024  # 10GB

    # Gemini Configuration
    gemini_model: str = "gemini-1.5-pro"
    temperature: float = 0.1
    max_output_tokens: int = 2048

    # Security Settings
    allowed_sql_operations: List[str] = field(default_factory=lambda: ["SELECT"])
    blocked_keywords: List[str] = field(default_factory=lambda: [
        "DROP", "DELETE", "UPDATE", "INSERT",
        "CREATE", "ALTER", "TRUNCATE", "GRANT",
        "REVOKE", "EXEC", "EXECUTE"
    ])
    enable_query_validation: bool = True


def get_project_from_metadata() -> Optional[str]:
    """
    Get GCP project ID from metadata server.

    Returns:
        Project ID or None if not available
    """
    try:
        response = requests.get(
            "http://metadata.google.internal/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"},
            timeout=1
        )
        if response.status_code == 200:
            return response.text
    except Exception:
        pass
    return None


def load_config() -> AppConfig:
    """
    Load application configuration from environment or metadata.

    Returns:
        AppConfig instance

    Raises:
        ValueError: If project ID cannot be determined
    """
    # Try to get project from environment variables
    project_id = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")

    # If not in environment, try metadata server
    if not project_id:
        project_id = get_project_from_metadata()

    if not project_id:
        raise ValueError(
            "Unable to determine GCP project ID. "
            "Set GCP_PROJECT environment variable or run in GCP environment."
        )

    return AppConfig(
        project_id=project_id,
        location=os.getenv("VERTEX_AI_LOCATION", "us-central1")
    )
