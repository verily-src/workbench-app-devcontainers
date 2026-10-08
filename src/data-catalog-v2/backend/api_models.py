"""Pydantic models for API responses."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class DatasetSummary(BaseModel):
    dataset_id: str
    table_count: int = 0


class TableSummary(BaseModel):
    fq_table: str
    project_id: str
    dataset_id: str
    table_id: str
    row_count: Optional[int] = None
    size_bytes: Optional[int] = None
    table_type: str = "BASE TABLE"
    column_count: int = 0
    creation_time: Optional[str] = None
    profiling: dict[str, str] = Field(
        default_factory=lambda: {"technical": "none", "semantic": "none"}
    )
    business_name: Optional[str] = None
    table_definition: Optional[str] = None


class CatalogResponse(BaseModel):
    project_id: str
    profile_bucket: str
    datasets: list[dict[str, Any]]


class JobStartResponse(BaseModel):
    job_id: str
    status: str = "running"


class ProfileStatusResponse(BaseModel):
    technical: str
    semantic: str


class ChartSuggestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chart_type: str = "bar"
    columns: list[str] = Field(default_factory=list)
    title: str = ""
    rationale: str = ""


class ChartsSuggestResponse(BaseModel):
    charts: list[ChartSuggestion]
