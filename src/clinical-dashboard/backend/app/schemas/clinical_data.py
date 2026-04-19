"""Pydantic schemas for clinical data endpoints"""
from pydantic import BaseModel


class VisitPoint(BaseModel):
    visit_num: int
    visit_name: str
    study_day_mean: float
    sbp_mean: float
    sbp_std: float
    dbp_mean: float
    dbp_std: float
    hr_mean: float
    hr_std: float
    count: int


class ClinicalTimelineResponse(BaseModel):
    cohort_size: int
    visits: list[VisitPoint]
