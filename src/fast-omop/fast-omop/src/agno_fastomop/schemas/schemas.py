from pydantic import BaseModel
from typing import List, Optional, Dict, Literal

class ConceptMapping(BaseModel):
    term: str
    concept_code: Optional[str] = None  # Allow None when concept not found
    concept_name: Optional[str] = None
    vocabulary_id: Optional[str] = None
    domain_id: Optional[Literal["Condition", "Drug", "Device", "Observation",
                         "Procedure", "Measurement", "Gender",
                         "Race", "Ethnicity", "Visit"]] = None
    concept_id: Optional[int] = None

    # NEW: Intelligent concept selection fields
    selection_reasoning: Optional[str] = None  # Explanation of why this concept was chosen
    alternative_concepts_considered: Optional[List[int]] = None  # Other concept IDs evaluated
    estimated_patient_count: Optional[int] = None  # Patient count from database usage check

class TemporalConstraint(BaseModel):
    """Flexible temporal constraint - structure varies by query type.

    Common patterns:
    - Relative window: {window_days: int, constraint_type: "within"|"before"|"after"}
    - Specific year: {year: int, constraint_type: str}
    - Date range: {start_date: str, end_date: str}
    - Grouping: {group_by: str}
    - Any other semantic representation the LLM finds appropriate

    The database agent is responsible for interpreting these fields and generating appropriate SQL.
    """

    # Common fields (all optional to support different patterns)
    window_days: Optional[int] = None
    constraint_type: Optional[str] = None
    year: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    group_by: Optional[str] = None

    class Config:
        extra = "allow"  # Accept novel fields from LLM


class AdditionalFilters(BaseModel):
    """Additional filters for query context.

    For follow-up queries like "How many of these have diabetes?", is_followup signals
    that the database agent should look at conversation history to find the previous
    cohort filtering logic and SQL query.
    """
    # Signal for follow-up queries - tells DB agent to look at conversation history
    is_followup: Optional[bool] = False

    # Demographics filters
    gender: Optional[str] = None
    age: Optional[int] = None  # Exact age constraint (e.g., "at age 18")
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    race: Optional[str] = None

    class Config:
        extra = "allow"  # Accept novel fields from LLM


class SemanticContext(BaseModel):
    user_query: str
    query_intent: str  # Allow any query type (e.g., "demographics", "distribution", "cohort_analysis", etc.)
    query_type: Optional[Literal["single", "intersection", "multi_intersection", "union", "demographics"]] = "single"

    entities: Optional[List[ConceptMapping]] = []  # Empty for demographics queries
    temporal_constraint: Optional[TemporalConstraint] = None
    additional_filters: Optional[AdditionalFilters] = None

class QueryResult(BaseModel):
    sql: str
    result_count: Optional[int] = None
    execution_time: Optional[str] = None
    schema_prefix: str
    rows: Optional[List[Dict]] = None
    message: Optional[str] = None  # For error messages or explanations

class ErrorResponse(BaseModel):
    error_type: str
    message: str
    suggested_fix: Optional[str] = None


