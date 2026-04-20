from typing import Optional
from fastapi import APIRouter, HTTPException
from ..services.bq import query_to_dataframe
from ..schemas.cohort import CohortResponse, CohortFilters, Participant
from ..config import get_settings
import hashlib

router = APIRouter()
settings = get_settings()

# Complete map of ALL available clinical filters
FILTER_CATALOG = {
    "demographics": {
        "sex": {"column": "sex", "label": "Sex", "type": "categorical"},
        "smoking_status": {"column": "smoking_status", "label": "Smoking Status", "type": "categorical"},
        "pack_years": {"column": "pack_years_smoked", "label": "Pack Years Smoked", "type": "numeric"},
    },
    "cardiovascular": {
        "htn": {"column": "mh_htn", "label": "Hypertension", "type": "binary"},
        "cvd": {"column": "mh_cvd", "label": "Cardiovascular Disease", "type": "binary"},
        "afib": {"column": "mh_afib", "label": "Atrial Fibrillation", "type": "binary"},
        "cad": {"column": "mh_cad", "label": "Coronary Artery Disease", "type": "binary"},
        "chf": {"column": "mh_chf", "label": "Congestive Heart Failure", "type": "binary"},
        "mi": {"column": "mh_mi", "label": "Myocardial Infarction", "type": "binary"},
        "stroke": {"column": "mh_cva", "label": "Stroke (CVA)", "type": "binary"},
        "tia": {"column": "mh_tia", "label": "Transient Ischemic Attack", "type": "binary"},
        "pad": {"column": "mh_pad", "label": "Peripheral Artery Disease", "type": "binary"},
        "vhd": {"column": "mh_vhd", "label": "Valvular Heart Disease", "type": "binary"},
    },
    "metabolic": {
        "diabetes": {"column": "mh_diabetes", "label": "Diabetes (Any Type)", "type": "binary"},
        "diab1": {"column": "mh_diab1", "label": "Type 1 Diabetes", "type": "binary"},
        "diab2": {"column": "mh_diab2", "label": "Type 2 Diabetes", "type": "binary"},
        "prediabetes": {"column": "mh_prediabetes", "label": "Prediabetes", "type": "binary"},
        "ckd": {"column": "mh_ckd", "label": "Chronic Kidney Disease", "type": "binary"},
        "copd": {"column": "mh_copd", "label": "COPD", "type": "binary"},
        "sleepapnea": {"column": "mh_sleepapnea", "label": "Sleep Apnea", "type": "binary"},
    },
    "mental_health": {
        "depression": {"column": "mh_major_depression", "label": "Major Depression", "type": "binary"},
        "bipolar": {"column": "mh_bipolar", "label": "Bipolar Disorder", "type": "binary"},
        "dementia": {"column": "mh_dementia", "label": "Dementia", "type": "binary"},
    },
    "medications": {
        "acei": {"column": "cm_acei", "label": "ACE Inhibitors", "type": "binary"},
        "arb": {"column": "cm_arb", "label": "ARBs", "type": "binary"},
        "bb": {"column": "cm_bb", "label": "Beta Blockers", "type": "binary"},
        "ccb": {"column": "cm_ccb", "label": "Calcium Channel Blockers", "type": "binary"},
        "diuretics": {"column": "cm_diuretics", "label": "Diuretics", "type": "binary"},
        "statin": {"column": "cm_statin", "label": "Statins", "type": "binary"},
        "diabetes_med": {"column": "cm_diabetes", "label": "Diabetes Medications", "type": "binary"},
    },
}

# Flatten for backward compatibility
DISEASE_MAP = {k: v["column"] for cat in ["cardiovascular", "metabolic", "mental_health"]
               for k, v in FILTER_CATALOG[cat].items()}
MEDICATION_MAP = {k: v["column"] for k, v in FILTER_CATALOG["medications"].items()}


@router.get("/filters")
def get_available_filters():
    """Return catalog of all available filters grouped by category."""
    return FILTER_CATALOG


from typing import Dict, Any
from fastapi import Query
import json


@router.get("/filter", response_model=CohortResponse)
def filter_cohort(
    sex: Optional[str] = None,
    disease: Optional[str] = None,
    medication: Optional[str] = None,
    filters: Optional[str] = Query(None, description="JSON object of additional filters"),
):
    """Filter participants by clinical labels to build a cohort.

    Accepts both legacy parameters (sex, disease, medication) and
    a 'filters' JSON object for dynamic filtering.

    Example: ?sex=Male&disease=htn&filters={"cad":"1","depression":"1"}
    """

    # Build WHERE clause
    where_conditions = []

    # Legacy sex parameter
    if sex:
        where_conditions.append(f"sex = '{sex}'")

    # Legacy disease/medication parameters
    if disease:
        disease_col = DISEASE_MAP.get(disease)
        if disease_col:
            where_conditions.append(f"CAST({disease_col} AS STRING) = '1'")

    if medication:
        med_col = MEDICATION_MAP.get(medication)
        if med_col:
            where_conditions.append(f"CAST({med_col} AS STRING) = '1'")

    # Dynamic filters from JSON
    if filters:
        try:
            filter_dict = json.loads(filters)
            # Look up each filter in the catalog
            for filter_key, filter_value in filter_dict.items():
                # Find the column name in catalog
                for category in FILTER_CATALOG.values():
                    if filter_key in category:
                        col_info = category[filter_key]
                        column = col_info["column"]

                        if col_info["type"] == "binary":
                            # Binary filter (0/1)
                            if filter_value in ["1", 1, True, "true"]:
                                where_conditions.append(f"CAST({column} AS STRING) = '1'")
                        elif col_info["type"] == "categorical":
                            # Categorical filter (exact match)
                            where_conditions.append(f"{column} = '{filter_value}'")
                        # Add numeric range handling if needed
                        break
        except (json.JSONDecodeError, Exception) as e:
            # Ignore malformed filters
            pass

    where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

    # Query DIAGNOSES table (only available columns)
    query = f"""
    SELECT DISTINCT
        USUBJID,
        sex
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
                    age_at_enrollment=None,  # Not available in DIAGNOSES table
                    race=None,  # Not available in DIAGNOSES table
                )
            )

        # Generate cohort ID from filters
        filter_str = f"{sex}_{disease}_{medication}_{filters}"
        cohort_id = hashlib.md5(filter_str.encode()).hexdigest()[:8]

        # Parse additional filters for response
        additional_filters_dict = None
        if filters:
            try:
                additional_filters_dict = json.loads(filters)
            except:
                pass

        return CohortResponse(
            cohort_id=cohort_id,
            filters=CohortFilters(
                sex=sex,
                min_age=None,
                max_age=None,
                disease=disease,
                medication=medication,
                additional_filters=additional_filters_dict,
            ),
            total_participants=len(participants),
            participants=participants,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"BigQuery error: {str(e)}")
