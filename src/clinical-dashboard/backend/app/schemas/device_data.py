"""Pydantic schemas for device data endpoints"""
from pydantic import BaseModel


class DeviceMetricPoint(BaseModel):
    study_day: int
    mean: float
    std: float
    count: int


class DeviceDataResponse(BaseModel):
    cohort_size: int
    metrics: dict[str, list[DeviceMetricPoint]]
