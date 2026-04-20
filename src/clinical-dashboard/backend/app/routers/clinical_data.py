from fastapi import APIRouter, HTTPException
from ..services.bq import query_to_dataframe
from ..schemas.clinical_data import ClinicalTimelineResponse, VisitPoint
from ..config import get_settings

router = APIRouter()
settings = get_settings()


@router.get("/visit-timeline", response_model=ClinicalTimelineResponse)
def get_visit_timeline(
    cohort_ids: str,  # comma-separated USUBJIDs
):
    """Get physician visit timeline with BP, HR for a cohort."""

    usubjids = [uid.strip() for uid in cohort_ids.split(",") if uid.strip()]
    if not usubjids:
        raise HTTPException(status_code=400, detail="No cohort IDs provided")

    # Build IN clause for USUBJIDs
    usubjid_list = "', '".join(usubjids)

    try:
        query = f"""
        SELECT
            VISITNUM as visit_num,
            ANY_VALUE(VISIT) as visit_name,
            AVG(study_day) as study_day_mean,
            AVG(vs_sbp1_mmhg) as sbp_mean,
            STDDEV(vs_sbp1_mmhg) as sbp_std,
            AVG(vs_dbp1_mmhg) as dbp_mean,
            STDDEV(vs_dbp1_mmhg) as dbp_std,
            AVG(vs_pulse_bpm) as hr_mean,
            STDDEV(vs_pulse_bpm) as hr_std,
            COUNT(DISTINCT USUBJID) as participant_count
        FROM `{settings.bhs_project}.crf.VS`
        WHERE USUBJID IN ('{usubjid_list}')
          AND VISITNUM IS NOT NULL
          AND (vs_sbp1_mmhg IS NOT NULL OR vs_dbp1_mmhg IS NOT NULL OR vs_pulse_bpm IS NOT NULL)
        GROUP BY VISITNUM
        ORDER BY VISITNUM
        """

        df = query_to_dataframe(query)

        visits = [
            VisitPoint(
                visit_num=int(row["visit_num"]),
                visit_name=str(row["visit_name"]) if row.get("visit_name") else f"Visit {int(row['visit_num'])}",
                study_day_mean=float(row["study_day_mean"]) if row.get("study_day_mean") else 0.0,
                sbp_mean=float(row["sbp_mean"]) if row.get("sbp_mean") else 0.0,
                sbp_std=float(row["sbp_std"]) if row.get("sbp_std") else 0.0,
                dbp_mean=float(row["dbp_mean"]) if row.get("dbp_mean") else 0.0,
                dbp_std=float(row["dbp_std"]) if row.get("dbp_std") else 0.0,
                hr_mean=float(row["hr_mean"]) if row.get("hr_mean") else 0.0,
                hr_std=float(row["hr_std"]) if row.get("hr_std") else 0.0,
                count=int(row["participant_count"])
            )
            for _, row in df.iterrows()
        ]

        return ClinicalTimelineResponse(
            cohort_size=len(usubjids),
            visits=visits,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"BigQuery error: {str(e)}")


@router.get("/visit-scatter")
def get_visit_scatter(cohort_ids: str):
    """Get individual visit dates for scatter plot.

    Returns each participant's visit dates (study_day) for all visits.
    """
    usubjids = [uid.strip() for uid in cohort_ids.split(",") if uid.strip()]
    if not usubjids:
        raise HTTPException(status_code=400, detail="No cohort IDs provided")

    usubjid_list = "', '".join(usubjids)

    try:
        query = f"""
        SELECT
            USUBJID,
            VISITNUM as visit_num,
            VISIT as visit_name,
            study_day
        FROM `{settings.bhs_project}.crf.VS`
        WHERE USUBJID IN ('{usubjid_list}')
          AND VISITNUM IS NOT NULL
          AND study_day IS NOT NULL
        ORDER BY USUBJID, VISITNUM
        LIMIT 10000
        """

        df = query_to_dataframe(query)

        visits = [
            {
                "usubjid": str(row["USUBJID"]),
                "visit_num": int(row["visit_num"]),
                "visit_name": str(row["visit_name"]) if row.get("visit_name") else f"Visit {int(row['visit_num'])}",
                "study_day": float(row["study_day"])
            }
            for _, row in df.iterrows()
        ]

        return {
            "cohort_size": len(usubjids),
            "visits": visits
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"BigQuery error: {str(e)}")
