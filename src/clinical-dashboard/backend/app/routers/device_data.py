from fastapi import APIRouter, HTTPException
from ..services.bq import query_to_dataframe
from ..schemas.device_data import DeviceDataResponse, DeviceMetricPoint
from ..config import get_settings
from typing import Optional
import numpy as np

router = APIRouter()
settings = get_settings()


def safe_float(value, default=0.0):
    """Convert value to float, handling NaN/None."""
    if value is None:
        return default
    try:
        f = float(value)
        if np.isnan(f) or np.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


@router.get("/participants-with-data")
def get_participants_with_sensor_data(cohort_ids: str):
    """Return list of participants from cohort that have sensor data."""
    usubjids = [uid.strip() for uid in cohort_ids.split(",") if uid.strip()]
    if not usubjids:
        return {"participants": []}

    usubjid_list = "', '".join(usubjids)

    try:
        # Check which participants have ANY sensor data
        query = f"""
        SELECT DISTINCT USUBJID
        FROM `{settings.bhs_project}.sensordata.STEP`
        WHERE USUBJID IN ('{usubjid_list}')
        """
        df = query_to_dataframe(query)
        participants_with_data = [str(row["USUBJID"]) for _, row in df.iterrows()]

        return {"participants": participants_with_data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"BigQuery error: {str(e)}")


@router.get("/individual")
def get_individual_participant_data(
    usubjid: str,
    metrics: str = "steps,sleep",
    min_day: Optional[int] = None,
    max_day: Optional[int] = None,
):
    """Get individual participant device data (not aggregated).

    Args:
        usubjid: Single participant ID
        metrics: Comma-separated metric names
        min_day: Minimum study day
        max_day: Maximum study day
    """
    if not usubjid:
        raise HTTPException(status_code=400, detail="No participant ID provided")

    metric_list = [m.strip() for m in metrics.split(",")]
    result_metrics = {}

    # Build time window filter
    time_filter = ""
    if min_day is not None:
        time_filter += f" AND study_day >= {min_day}"
    if max_day is not None:
        time_filter += f" AND study_day <= {max_day}"

    try:
        # Steps
        if "steps" in metric_list:
            query = f"""
            SELECT
                CAST(study_day AS INT64) as study_day,
                step_count as value
            FROM `{settings.bhs_project}.sensordata.STEP`
            WHERE USUBJID = '{usubjid}'
              AND step_count IS NOT NULL
              AND study_day IS NOT NULL
              {time_filter}
            ORDER BY study_day
            LIMIT 1000
            """
            df = query_to_dataframe(query)
            result_metrics["steps"] = [
                {"study_day": int(row["study_day"]), "value": safe_float(row["value"])}
                for _, row in df.iterrows()
            ]

        # Sleep - total
        if "sleep" in metric_list:
            query = f"""
            SELECT
                CAST(study_day AS INT64) as study_day,
                total_sleep_time as value
            FROM `{settings.bhs_project}.sensordata.SLPMET`
            WHERE USUBJID = '{usubjid}'
              AND total_sleep_time IS NOT NULL
              AND study_day IS NOT NULL
              {time_filter}
            ORDER BY study_day
            LIMIT 1000
            """
            df = query_to_dataframe(query)
            result_metrics["sleep"] = [
                {"study_day": int(row["study_day"]), "value": safe_float(row["value"])}
                for _, row in df.iterrows()
            ]

        # Sleep stages
        for stage in ["rem", "deep", "light"]:
            if f"sleep_{stage}" in metric_list:
                query = f"""
                SELECT
                    CAST(study_day AS INT64) as study_day,
                    {stage} as value
                FROM `{settings.bhs_project}.sensordata.SLPMET`
                WHERE USUBJID = '{usubjid}'
                  AND {stage} IS NOT NULL
                  AND study_day IS NOT NULL
                  {time_filter}
                ORDER BY study_day
                LIMIT 1000
                """
                df = query_to_dataframe(query)
                result_metrics[f"sleep_{stage}"] = [
                    {"study_day": int(row["study_day"]), "value": safe_float(row["value"])}
                    for _, row in df.iterrows()
                ]

        # HRV
        if "hrv" in metric_list:
            query = f"""
            SELECT
                CAST(study_day AS INT64) as study_day,
                rmssd_mean as value
            FROM `{settings.bhs_project}.sensordata.HEMET`
            WHERE USUBJID = '{usubjid}'
              AND rmssd_mean IS NOT NULL
              AND study_day IS NOT NULL
              {time_filter}
            ORDER BY study_day
            LIMIT 1000
            """
            df = query_to_dataframe(query)
            result_metrics["hrv"] = [
                {"study_day": int(row["study_day"]), "value": safe_float(row["value"])}
                for _, row in df.iterrows()
            ]

        return {
            "usubjid": usubjid,
            "metrics": result_metrics,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"BigQuery error: {str(e)}")


@router.get("/aggregated", response_model=DeviceDataResponse)
def get_aggregated_device_data(
    cohort_ids: str,  # comma-separated USUBJIDs
    metrics: str = "steps,sleep,sleep_rem,sleep_deep,sleep_light,hrv,walking_bouts,nonwalking_bouts",
    min_day: Optional[int] = None,
    max_day: Optional[int] = None,
):
    """Get aggregated device data for a cohort (mean + stdev over time).

    Args:
        cohort_ids: Comma-separated USUBJIDs
        metrics: Comma-separated metric names
        min_day: Minimum study day (filter time window)
        max_day: Maximum study day (filter time window)
    """

    usubjids = [uid.strip() for uid in cohort_ids.split(",") if uid.strip()]
    if not usubjids:
        raise HTTPException(status_code=400, detail="No cohort IDs provided")

    # Filter to only participants with sensor data
    try:
        check_query = f"""
        SELECT DISTINCT USUBJID
        FROM `{settings.bhs_project}.sensordata.STEP`
        WHERE USUBJID IN ('{"', '".join(usubjids)}')
        """
        check_df = query_to_dataframe(check_query)
        usubjids = [str(row["USUBJID"]) for _, row in check_df.iterrows()]

        if not usubjids:
            return DeviceDataResponse(cohort_size=0, metrics={})
    except:
        pass  # Continue with original list if check fails

    metric_list = [m.strip() for m in metrics.split(",")]
    result_metrics = {}

    # Build IN clause for USUBJIDs
    usubjid_list = "', '".join(usubjids)

    # Build time window filter
    time_filter = ""
    if min_day is not None:
        time_filter += f" AND study_day >= {min_day}"
    if max_day is not None:
        time_filter += f" AND study_day <= {max_day}"

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
              {time_filter}
            GROUP BY study_day
            ORDER BY study_day
            LIMIT 1000
            """
            df = query_to_dataframe(query)
            result_metrics["steps"] = [
                DeviceMetricPoint(
                    study_day=int(row["study_day"]),
                    mean=safe_float(row["mean_steps"]),
                    std=safe_float(row["std_steps"]),
                    count=int(row["participant_count"])
                )
                for _, row in df.iterrows()
            ]

        # Sleep aggregation - total sleep time
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
              {time_filter}
            GROUP BY study_day
            ORDER BY study_day
            LIMIT 1000
            """
            df = query_to_dataframe(query)
            result_metrics["sleep"] = [
                DeviceMetricPoint(
                    study_day=int(row["study_day"]),
                    mean=safe_float(row["mean_sleep"]),
                    std=safe_float(row["std_sleep"]),
                    count=int(row["participant_count"])
                )
                for _, row in df.iterrows()
            ]

        # Sleep stages - REM
        if "sleep_rem" in metric_list:
            query = f"""
            SELECT
                CAST(study_day AS INT64) as study_day,
                AVG(rem) as mean_rem,
                STDDEV(rem) as std_rem,
                COUNT(DISTINCT USUBJID) as participant_count
            FROM `{settings.bhs_project}.sensordata.SLPMET`
            WHERE USUBJID IN ('{usubjid_list}')
              AND rem IS NOT NULL
              AND study_day IS NOT NULL
              {time_filter}
            GROUP BY study_day
            ORDER BY study_day
            LIMIT 1000
            """
            df = query_to_dataframe(query)
            result_metrics["sleep_rem"] = [
                DeviceMetricPoint(
                    study_day=int(row["study_day"]),
                    mean=safe_float(row["mean_rem"]),
                    std=safe_float(row["std_rem"]),
                    count=int(row["participant_count"])
                )
                for _, row in df.iterrows()
            ]

        # Sleep stages - Deep
        if "sleep_deep" in metric_list:
            query = f"""
            SELECT
                CAST(study_day AS INT64) as study_day,
                AVG(deep) as mean_deep,
                STDDEV(deep) as std_deep,
                COUNT(DISTINCT USUBJID) as participant_count
            FROM `{settings.bhs_project}.sensordata.SLPMET`
            WHERE USUBJID IN ('{usubjid_list}')
              AND deep IS NOT NULL
              AND study_day IS NOT NULL
              {time_filter}
            GROUP BY study_day
            ORDER BY study_day
            LIMIT 1000
            """
            df = query_to_dataframe(query)
            result_metrics["sleep_deep"] = [
                DeviceMetricPoint(
                    study_day=int(row["study_day"]),
                    mean=safe_float(row["mean_deep"]),
                    std=safe_float(row["std_deep"]),
                    count=int(row["participant_count"])
                )
                for _, row in df.iterrows()
            ]

        # Sleep stages - Light
        if "sleep_light" in metric_list:
            query = f"""
            SELECT
                CAST(study_day AS INT64) as study_day,
                AVG(light) as mean_light,
                STDDEV(light) as std_light,
                COUNT(DISTINCT USUBJID) as participant_count
            FROM `{settings.bhs_project}.sensordata.SLPMET`
            WHERE USUBJID IN ('{usubjid_list}')
              AND light IS NOT NULL
              AND study_day IS NOT NULL
              {time_filter}
            GROUP BY study_day
            ORDER BY study_day
            LIMIT 1000
            """
            df = query_to_dataframe(query)
            result_metrics["sleep_light"] = [
                DeviceMetricPoint(
                    study_day=int(row["study_day"]),
                    mean=safe_float(row["mean_light"]),
                    std=safe_float(row["std_light"]),
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
              {time_filter}
            GROUP BY study_day
            ORDER BY study_day
            LIMIT 1000
            """
            df = query_to_dataframe(query)
            result_metrics["hrv"] = [
                DeviceMetricPoint(
                    study_day=int(row["study_day"]),
                    mean=safe_float(row["mean_hrv"]),
                    std=safe_float(row["std_hrv"]),
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
                  {time_filter.replace("study_day", "study_day_int")}
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
                    mean=safe_float(row["mean_bouts"]),
                    std=safe_float(row["std_bouts"]),
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
                  {time_filter.replace("study_day", "study_day_int")}
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
                    mean=safe_float(row["mean_bouts"]),
                    std=safe_float(row["std_bouts"]),
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
