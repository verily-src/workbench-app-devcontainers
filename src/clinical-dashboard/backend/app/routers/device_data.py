from fastapi import APIRouter, HTTPException
from ..services.bq import query_to_dataframe
from ..schemas.device_data import DeviceDataResponse, DeviceMetricPoint
from ..config import get_settings

router = APIRouter()
settings = get_settings()


@router.get("/aggregated", response_model=DeviceDataResponse)
def get_aggregated_device_data(
    cohort_ids: str,  # comma-separated USUBJIDs
    metrics: str = "steps,sleep,hrv,walking_bouts,nonwalking_bouts",
):
    """Get aggregated device data for a cohort (mean + stdev over time)."""

    usubjids = [uid.strip() for uid in cohort_ids.split(",") if uid.strip()]
    if not usubjids:
        raise HTTPException(status_code=400, detail="No cohort IDs provided")

    metric_list = [m.strip() for m in metrics.split(",")]
    result_metrics = {}

    # Build IN clause for USUBJIDs
    usubjid_list = "', '".join(usubjids)

    try:
        # Steps aggregation
        if "steps" in metric_list:
            query = f"""
            SELECT
                CAST(study_day AS INT64) as study_day,
                AVG(step_count) as mean_steps,
                STDDEV(step_count) as std_steps,
                COUNT(DISTINCT USUBJID) as participant_count
            FROM `{settings.bhs_project}.sensordata.STEP`
            WHERE USUBJID IN ('{usubjid_list}')
              AND step_count IS NOT NULL
              AND study_day IS NOT NULL
            GROUP BY study_day
            ORDER BY study_day
            LIMIT 1000
            """
            df = query_to_dataframe(query)
            result_metrics["steps"] = [
                DeviceMetricPoint(
                    study_day=int(row["study_day"]),
                    mean=float(row["mean_steps"]) if row["mean_steps"] else 0.0,
                    std=float(row["std_steps"]) if row["std_steps"] else 0.0,
                    count=int(row["participant_count"])
                )
                for _, row in df.iterrows()
            ]

        # Sleep aggregation
        if "sleep" in metric_list:
            query = f"""
            SELECT
                CAST(study_day AS INT64) as study_day,
                AVG(total_sleep_time) as mean_sleep,
                STDDEV(total_sleep_time) as std_sleep,
                COUNT(DISTINCT USUBJID) as participant_count
            FROM `{settings.bhs_project}.sensordata.SLPMET`
            WHERE USUBJID IN ('{usubjid_list}')
              AND total_sleep_time IS NOT NULL
              AND study_day IS NOT NULL
            GROUP BY study_day
            ORDER BY study_day
            LIMIT 1000
            """
            df = query_to_dataframe(query)
            result_metrics["sleep"] = [
                DeviceMetricPoint(
                    study_day=int(row["study_day"]),
                    mean=float(row["mean_sleep"]) if row["mean_sleep"] else 0.0,
                    std=float(row["std_sleep"]) if row["std_sleep"] else 0.0,
                    count=int(row["participant_count"])
                )
                for _, row in df.iterrows()
            ]

        # HRV aggregation (using rmssd_mean)
        if "hrv" in metric_list:
            query = f"""
            SELECT
                CAST(study_day AS INT64) as study_day,
                AVG(rmssd_mean) as mean_hrv,
                STDDEV(rmssd_mean) as std_hrv,
                COUNT(DISTINCT USUBJID) as participant_count
            FROM `{settings.bhs_project}.sensordata.HEMET`
            WHERE USUBJID IN ('{usubjid_list}')
              AND rmssd_mean IS NOT NULL
              AND study_day IS NOT NULL
            GROUP BY study_day
            ORDER BY study_day
            LIMIT 1000
            """
            df = query_to_dataframe(query)
            result_metrics["hrv"] = [
                DeviceMetricPoint(
                    study_day=int(row["study_day"]),
                    mean=float(row["mean_hrv"]) if row["mean_hrv"] else 0.0,
                    std=float(row["std_hrv"]) if row["std_hrv"] else 0.0,
                    count=int(row["participant_count"])
                )
                for _, row in df.iterrows()
            ]

        # Walking bouts (ACTIVITY_AMBULATORY)
        if "walking_bouts" in metric_list:
            query = f"""
            SELECT
                study_day_int as study_day,
                AVG(bout_count) as mean_bouts,
                STDDEV(bout_count) as std_bouts,
                COUNT(DISTINCT USUBJID) as participant_count
            FROM (
                SELECT
                    USUBJID,
                    study_day_int,
                    COUNT(*) as bout_count
                FROM `{settings.bhs_project}.sensordata.AMCLASS`
                WHERE USUBJID IN ('{usubjid_list}')
                  AND class_label = 'ACTIVITY_AMBULATORY'
                  AND study_day_int IS NOT NULL
                GROUP BY USUBJID, study_day_int
            )
            GROUP BY study_day
            ORDER BY study_day
            LIMIT 1000
            """
            df = query_to_dataframe(query)
            result_metrics["walking_bouts"] = [
                DeviceMetricPoint(
                    study_day=int(row["study_day"]),
                    mean=float(row["mean_bouts"]) if row["mean_bouts"] else 0.0,
                    std=float(row["std_bouts"]) if row["std_bouts"] else 0.0,
                    count=int(row["participant_count"])
                )
                for _, row in df.iterrows()
            ]

        # Non-walking bouts (everything except ACTIVITY_AMBULATORY)
        if "nonwalking_bouts" in metric_list:
            query = f"""
            SELECT
                study_day_int as study_day,
                AVG(bout_count) as mean_bouts,
                STDDEV(bout_count) as std_bouts,
                COUNT(DISTINCT USUBJID) as participant_count
            FROM (
                SELECT
                    USUBJID,
                    study_day_int,
                    COUNT(*) as bout_count
                FROM `{settings.bhs_project}.sensordata.AMCLASS`
                WHERE USUBJID IN ('{usubjid_list}')
                  AND class_label != 'ACTIVITY_AMBULATORY'
                  AND study_day_int IS NOT NULL
                GROUP BY USUBJID, study_day_int
            )
            GROUP BY study_day
            ORDER BY study_day
            LIMIT 1000
            """
            df = query_to_dataframe(query)
            result_metrics["nonwalking_bouts"] = [
                DeviceMetricPoint(
                    study_day=int(row["study_day"]),
                    mean=float(row["mean_bouts"]) if row["mean_bouts"] else 0.0,
                    std=float(row["std_bouts"]) if row["std_bouts"] else 0.0,
                    count=int(row["participant_count"])
                )
                for _, row in df.iterrows()
            ]

        return DeviceDataResponse(
            cohort_size=len(usubjids),
            metrics=result_metrics,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"BigQuery error: {str(e)}")
