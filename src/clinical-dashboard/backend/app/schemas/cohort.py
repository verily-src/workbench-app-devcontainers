"""Pydantic schemas for cohort endpoints"""
from typing import Optional, List
from pydantic import BaseModel


class Participant(BaseModel):
    usubjid: str
    sex: Optional[str] = None
    age_at_enrollment: Optional[int] = None
    race: Optional[str] = None


class CohortFilters(BaseModel):
    sex: Optional[str] = None
    min_age: Optional[int] = None
    max_age: Optional[int] = None
    disease: Optional[str] = None
    medication: Optional[str] = None


class CohortResponse(BaseModel):
    cohort_id: str
    filters: CohortFilters
    total_participants: int
    participants: List[Participant]
