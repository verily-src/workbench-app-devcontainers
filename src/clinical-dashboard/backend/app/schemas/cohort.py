"""Pydantic schemas for cohort endpoints"""
from pydantic import BaseModel


class Participant(BaseModel):
    usubjid: str
    sex: str | None = None
    age_at_enrollment: int | None = None
    race: str | None = None


class CohortFilters(BaseModel):
    sex: str | None = None
    min_age: int | None = None
    max_age: int | None = None
    disease: str | None = None
    medication: str | None = None


class CohortResponse(BaseModel):
    cohort_id: str
    filters: CohortFilters
    total_participants: int
    participants: list[Participant]
