from fastapi import APIRouter, HTTPException
from ..services.bq import query_to_dataframe
from ..schemas.cohort import CohortResponse, CohortFilters, Participant
from ..config import get_settings
import hashlib

router = APIRouter()
settings = get_settings()

# Map disease/medication names to column names
DISEASE_MAP = {
    "htn": "mh_htn",
    "diabetes": "mh_diabetes",
    "cvd": "mh_cvd",
    "ckd": "mh_ckd",
    "afib": "mh_afib",
    "copd": "mh_copd",
}

MEDICATION_MAP = {
    "acei": "cm_acei",
    "arb": "cm_arb",
    "bb": "cm_bb",
    "ccb": "cm_ccb",
    "diuretics": "cm_diuretics",
}


@router.get("/filter", response_model=CohortResponse)
def filter_cohort(
    sex: str | None = None,
    min_age: int | None = None,
    max_age: int | None = None,
    disease: str | None = None,
    medication: str | None = None,
):
    """Filter participants by clinical labels to build a cohort."""

    # Build WHERE clause
    where_conditions = []

    if sex:
        where_conditions.append(f"sex = '{sex}'")

    if min_age is not None:
        where_conditions.append(f"age_at_enrollment >= {min_age}")

    if max_age is not None:
        where_conditions.append(f"age_at_enrollment <= {max_age}")

    if disease:
        disease_col = DISEASE_MAP.get(disease)
        if disease_col:
            # Handle both string '1' and numeric 1
            where_conditions.append(f"CAST({disease_col} AS STRING) = '1'")

    if medication:
        med_col = MEDICATION_MAP.get(medication)
        if med_col:
            # Handle both string '1' and numeric 1
            where_conditions.append(f"CAST({med_col} AS STRING) = '1'")

    where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

    # Query DIAGNOSES table
    query = f"""
    SELECT DISTINCT
        USUBJID,
        sex,
        age_at_enrollment,
        race
    FROM `{settings.bhs_project}.analysis.DIAGNOSES`
    WHERE {where_clause}
    ORDER BY USUBJID
    LIMIT 1000
    """

    try:
        df = query_to_dataframe(query)

        # Convert to participants
        participants = []
        for _, row in df.iterrows():
            participants.append(
                Participant(
                    usubjid=str(row["USUBJID"]),
                    sex=str(row["sex"]) if row.get("sex") else None,
                    age_at_enrollment=int(row["age_at_enrollment"]) if row.get("age_at_enrollment") else None,
                    race=str(row["race"]) if row.get("race") else None,
                )
            )

        # Generate cohort ID from filters
        filter_str = f"{sex}_{min_age}_{max_age}_{disease}_{medication}"
        cohort_id = hashlib.md5(filter_str.encode()).hexdigest()[:8]

        return CohortResponse(
            cohort_id=cohort_id,
            filters=CohortFilters(
                sex=sex,
                min_age=min_age,
                max_age=max_age,
                disease=disease,
                medication=medication,
            ),
            total_participants=len(participants),
            participants=participants,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"BigQuery error: {str(e)}")
