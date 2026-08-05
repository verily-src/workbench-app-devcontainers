import os
import subprocess
from pathlib import Path

import yaml
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, jsonify, render_template_string, request
from flask_cors import CORS
from google.cloud import bigquery


def _parse_wb_workspace():
    result = {}
    try:
        out = subprocess.run(
            ["wb", "workspace", "describe"],
            capture_output=True, text=True, timeout=10,
        )
        for line in out.stdout.splitlines():
            for key in ("Organization:", "Google project:"):
                if line.strip().startswith(key):
                    result[key.rstrip(":")] = line.split(":", 1)[1].strip()
    except Exception:
        pass
    return result

_wb_info = _parse_wb_workspace()

app = Flask(__name__)
app.config['STRICT_SLASHES'] = False
CORS(app)

_config_path = Path(__file__).parent / "config.yaml"
_config = {}
if _config_path.exists():
    with open(_config_path) as f: 
        _config = yaml.safe_load(f) or {}

ENV = os.environ.get("DC_ACCESS_ENV") or _config.get("env", "prod")
BQ_PROJECT = os.environ.get("DC_ACCESS_BQ_PROJECT") or _config.get("bq_project", "")
JOB_PROJECT = os.environ.get("DC_ACCESS_JOB_PROJECT") or _config.get("job_project", "") or _wb_info.get("Google project", "")
ORG = os.environ.get("DC_ACCESS_ORG_UFID", "").strip() or _config.get("org", "") or _wb_info.get("Organization", "")
ORG_SUFFIX = f"_{ORG}" if ORG else "" 

bq_client = bigquery.Client(project=JOB_PROJECT) if JOB_PROJECT else bigquery.Client()



DC_EXISTS_QUERY = """
SELECT COUNT(*) AS cnt
FROM `workbench-bq-log-sink.workbench_monitoring_org_logs_{env}.data_collection_access_grants{org_suffix}`
WHERE data_collection_user_facing_id = @dc_user_facing_id
"""


# if ENV == "dev":
USER_ACTIVITY_LOG_CTES = '''
  user_activity_log_data AS (
    SELECT *
    FROM `workbench-bq-log-sink.workbench_monitoring_org_logs_{env}.um_user_activity_in_org_log{org_suffix}`
  ),
'''
WB_GROUPS_CTE = '''
  wb_groups AS (
    SELECT internal_name, group_name
    FROM `workbench-bq-log-sink.workbench_monitoring_org_logs_{env}.um_workbench_groups{org_suffix}`
  ),
'''

DC_ACCESS_QUERY = '''
WITH
{user_activity_log_ctes}

dc_grants AS (
  SELECT
    user_email,
    data_collection_name,
    data_collection_user_facing_id,
    role,
    grant_type,
    group_email,
    group_name,
    member_group_name,
    user_facing_group_name,
    org_id
  FROM `workbench-bq-log-sink.workbench_monitoring_org_logs_{env}.data_collection_access_grants{org_suffix}`
  WHERE data_collection_user_facing_id = @dc_user_facing_id
    AND grant_type = 'GROUP'
),

grant_events AS (
  SELECT
    ual.subject_id       AS group_internal_name,
    ual.change_timestamp,
    ual.actor_email      AS granted_by,
    JSON_VALUE(ual.properties, '$.comment') AS grant_reason,
    (
      SELECT REGEXP_EXTRACT(JSON_VALUE(elem, '$.resourceId'), r'(?i)^(.+):USER$')
      FROM UNNEST(JSON_EXTRACT_ARRAY(ual.related_resources)) AS elem
      WHERE JSON_VALUE(elem, '$.resourceType') = 'PRINCIPAL'
      LIMIT 1
    ) AS granted_user_email
  FROM user_activity_log_data ual
  WHERE ual.change_type = 'GRANT_ROLE_GROUP'
),

latest_grants AS (
  SELECT
    group_internal_name,
    granted_user_email,
    change_timestamp,
    granted_by,
    grant_reason,
    ROW_NUMBER() OVER (
      PARTITION BY group_internal_name, granted_user_email
      ORDER BY change_timestamp DESC
    ) AS rn
  FROM grant_events
  WHERE granted_user_email IS NOT NULL
)

SELECT
g.user_email,
g.role                            AS role_on_collection,
g.user_facing_group_name          AS group_name,
g.group_email,
g.data_collection_name,
g.data_collection_user_facing_id,
lg.change_timestamp               AS access_granted_at,
lg.granted_by,
lg.grant_reason
FROM dc_grants g
LEFT JOIN latest_grants lg
ON  lg.group_internal_name = g.member_group_name
AND lg.granted_user_email  = g.user_email
AND lg.rn = 1
ORDER BY
g.role,
g.user_email
'''



GROUP_MEMBERSHIP_QUERY = '''
WITH
{user_activity_log_ctes}
resolved_group AS (
  SELECT DISTINCT member_group_name
  FROM `workbench-bq-log-sink.workbench_monitoring_org_logs_{env}.data_collection_access_grants{org_suffix}`
  WHERE user_facing_group_name = @group_name
),

group_events AS (
  SELECT
    ual.subject_id        AS group_internal_name,
    ual.change_type,
    ual.change_timestamp,
    ual.actor_email       AS acted_by,
    JSON_VALUE(ual.properties, '$.role')    AS group_role,
    JSON_VALUE(ual.properties, '$.comment') AS reason,
    (
      SELECT REGEXP_EXTRACT(JSON_VALUE(elem, '$.resourceId'), r'(?i)^(.+):USER$')
      FROM UNNEST(JSON_EXTRACT_ARRAY(ual.related_resources)) AS elem
      WHERE JSON_VALUE(elem, '$.resourceType') = 'PRINCIPAL'
      LIMIT 1
    ) AS member_email
  FROM user_activity_log_data ual
  WHERE ual.change_type IN ('GRANT_ROLE_GROUP', 'REVOKE_ROLE_GROUP')
    AND ual.subject_id IN (SELECT member_group_name FROM resolved_group)
),

ranked_events AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY group_internal_name, member_email
      ORDER BY change_timestamp DESC
    ) AS rn
  FROM group_events
  WHERE member_email IS NOT NULL
),

current_members AS (
  SELECT *
  FROM ranked_events
  WHERE rn = 1
    AND change_type = 'GRANT_ROLE_GROUP'
)

SELECT
member_email,
group_internal_name,
group_role,
change_timestamp    AS access_granted_at,
acted_by            AS granted_by,
reason              AS grant_reason
FROM current_members
ORDER BY
change_timestamp DESC
'''


GROUP_AUDIT_QUERY = '''
WITH
{user_activity_log_ctes}

{wb_groups_cte}

group_events AS (
  SELECT
    ual.change_timestamp,
    ual.change_type,
    ual.subject_id AS group_internal_name,
    wb.group_name AS user_facing_group_name,
    ual.actor_email,
    UPPER(JSON_VALUE(ual.properties, '$.role')) AS group_role,
    JSON_VALUE(ual.properties, '$.comment') AS reason,
    (
      SELECT REGEXP_EXTRACT(JSON_VALUE(elem, '$.resourceId'), r'(?i)^(.+):USER$')
      FROM UNNEST(JSON_EXTRACT_ARRAY(ual.related_resources)) AS elem
      WHERE JSON_VALUE(elem, '$.resourceType') = 'PRINCIPAL'
      LIMIT 1
    ) AS member_email
  FROM user_activity_log_data ual
  LEFT JOIN wb_groups wb ON ual.subject_id = wb.internal_name
  WHERE ual.change_type IN ('GRANT_ROLE_GROUP', 'REVOKE_ROLE_GROUP')
    AND wb.group_name = @group_name
)

SELECT
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', change_timestamp) AS change_timestamp,
  CASE
    WHEN change_type = 'GRANT_ROLE_GROUP' THEN 'GRANTED'
    WHEN change_type = 'REVOKE_ROLE_GROUP' THEN 'REVOKED'
  END AS action,
  member_email,
  user_facing_group_name,
  group_internal_name,
  group_role,
  actor_email AS acted_by,
  reason
FROM group_events
WHERE member_email IS NOT NULL
ORDER BY change_timestamp DESC
'''


FORENSIC_V2_QUERY = '''
WITH
{user_activity_log_ctes}
{wb_groups_cte}

workspace_events AS (
  SELECT
    w.change_date AS event_timestamp,
    w.change_type,
    w.change_subject_id AS subject,
    w.actor_email,
    UPPER(JSON_VALUE(w.properties, '$.role')) AS role,
    CAST(NULL AS STRING) AS reason,
    CASE WHEN wb.internal_name IS NOT NULL THEN 'GROUP' ELSE 'INDIVIDUAL' END AS subject_type,
    wb.group_name AS group_name,
    CASE
      WHEN w.change_type = 'GRANT_WORKSPACE_ROLE' THEN 'DC ACCESS GRANTED'
      WHEN w.change_type = 'REMOVE_WORKSPACE_ROLE' THEN 'DC ACCESS REVOKED'
    END AS action
  FROM `workbench-bq-log-sink.workbench_monitoring_org_logs_{env}.wsm_workspace_activity_logs{org_suffix}` w
  LEFT JOIN wb_groups wb ON REGEXP_EXTRACT(w.change_subject_id, r'^(.+)@verily-bvdp\\.com$') = wb.internal_name
  WHERE w.change_type IN ('GRANT_WORKSPACE_ROLE', 'REMOVE_WORKSPACE_ROLE')
    AND w.workspace_user_facing_id = @workspace_name
),

dc_groups AS (
  SELECT DISTINCT REGEXP_EXTRACT(subject, r'^(.+)@verily-bvdp\\.com$') AS internal_name
  FROM workspace_events
  WHERE subject_type = 'GROUP'
),

member_events AS (
  SELECT
    ual.change_timestamp AS event_timestamp,
    ual.change_type,
    (
      SELECT REGEXP_EXTRACT(JSON_VALUE(elem, '$.resourceId'), r'(?i)^(.+):USER$')
      FROM UNNEST(JSON_EXTRACT_ARRAY(ual.related_resources)) AS elem
      WHERE JSON_VALUE(elem, '$.resourceType') = 'PRINCIPAL'
      LIMIT 1
    ) AS subject,
    ual.actor_email,
    UPPER(JSON_VALUE(ual.properties, '$.role')) AS role,
    JSON_VALUE(ual.properties, '$.comment') AS reason,
    'MEMBER' AS subject_type,
    wb.group_name AS group_name,
    CASE
      WHEN ual.change_type = 'GRANT_ROLE_GROUP' THEN 'ADDED TO GROUP'
      WHEN ual.change_type = 'REVOKE_ROLE_GROUP' THEN 'REMOVED FROM GROUP'
    END AS action
  FROM user_activity_log_data ual
  INNER JOIN dc_groups dg ON ual.subject_id = dg.internal_name
  LEFT JOIN wb_groups wb ON ual.subject_id = wb.internal_name
  WHERE ual.change_type IN ('GRANT_ROLE_GROUP', 'REVOKE_ROLE_GROUP')
)

SELECT * FROM (
  SELECT event_timestamp, FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', event_timestamp) AS event_timestamp_fmt, action, subject_type, subject, group_name, role, actor_email, reason
  FROM workspace_events
  UNION ALL
  SELECT event_timestamp, FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', event_timestamp) AS event_timestamp_fmt, action, subject_type, subject, group_name, role, actor_email, reason
  FROM member_events
  WHERE subject IS NOT NULL
)
ORDER BY event_timestamp DESC
'''


WORKSPACE_FORENSIC_QUERY = '''
WITH
{user_activity_log_ctes}
{wb_groups_cte}

workspace_grants AS (
  SELECT
    w.change_date,
    w.change_subject_id,
    w.workspace_user_facing_id,
    w.org_user_facing_id,
    w.actor_email,
    CASE
      WHEN (
        SELECT MIN(rv.change_date) FROM `workbench-bq-log-sink.workbench_monitoring_org_logs_{env}.wsm_workspace_activity_logs{org_suffix}` rv
        WHERE rv.change_type = 'REMOVE_WORKSPACE_ROLE'
          AND rv.workspace_user_facing_id = w.workspace_user_facing_id
          AND rv.change_subject_id = w.change_subject_id
          AND UPPER(JSON_VALUE(rv.properties, '$.role')) = UPPER(JSON_VALUE(w.properties, '$.role'))
          AND rv.change_date >= w.change_date
      ) IS NOT NULL THEN UPPER(JSON_VALUE(w.properties, '$.role')) || ' (REVOKED ' || FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', (
        SELECT MIN(rv.change_date) FROM `workbench-bq-log-sink.workbench_monitoring_org_logs_{env}.wsm_workspace_activity_logs{org_suffix}` rv
        WHERE rv.change_type = 'REMOVE_WORKSPACE_ROLE'
          AND rv.workspace_user_facing_id = w.workspace_user_facing_id
          AND rv.change_subject_id = w.change_subject_id
          AND UPPER(JSON_VALUE(rv.properties, '$.role')) = UPPER(JSON_VALUE(w.properties, '$.role'))
          AND rv.change_date >= w.change_date
      )) || ')'
      ELSE UPPER(JSON_VALUE(w.properties, '$.role'))
    END AS granted_role,
    CASE WHEN wb.internal_name IS NOT NULL THEN 'GROUP' ELSE 'DIRECT' END AS dc_grant_type
  FROM `workbench-bq-log-sink.workbench_monitoring_org_logs_{env}.wsm_workspace_activity_logs{org_suffix}` w
  LEFT JOIN wb_groups wb ON REGEXP_EXTRACT(w.change_subject_id, r'^(.+)@verily-bvdp\.com$') = wb.internal_name
  WHERE w.change_type = 'GRANT_WORKSPACE_ROLE'
    AND w.workspace_user_facing_id = @workspace_name
),

group_grants AS (
  SELECT
    wg.change_date,
    wg.change_subject_id,
    wg.workspace_user_facing_id,
    wg.org_user_facing_id,
    wg.actor_email,
    wg.granted_role,
    wb.internal_name AS resolved_group_name,
    wb.group_name AS user_facing_group_name
  FROM workspace_grants wg
  JOIN wb_groups wb
    ON REGEXP_EXTRACT(wg.change_subject_id, r'^(.+)@verily-bvdp\.com$') = wb.internal_name
  WHERE wg.dc_grant_type = 'GROUP'
),

unresolved_group_grants AS (
  SELECT
    wg.change_date,
    wg.change_subject_id,
    wg.workspace_user_facing_id,
    wg.org_user_facing_id,
    wg.actor_email,
    wg.granted_role
  FROM workspace_grants wg
  WHERE wg.dc_grant_type = 'GROUP'
    AND REGEXP_EXTRACT(wg.change_subject_id, r'^(.+)@verily-bvdp\.com$') NOT IN (SELECT DISTINCT internal_name FROM wb_groups)
),

member_events AS (
  SELECT
    ual.subject_id AS group_internal_name,
    ual.change_type,
    ual.change_timestamp,
    ual.actor_email AS member_granted_by,
    UPPER(JSON_VALUE(ual.properties, '$.role')) AS member_role,
    (
      SELECT REGEXP_EXTRACT(JSON_VALUE(elem, '$.resourceId'), r'(?i)^(.+):USER$')
      FROM UNNEST(JSON_EXTRACT_ARRAY(ual.related_resources)) AS elem
      WHERE JSON_VALUE(elem, '$.resourceType') = 'PRINCIPAL'
      LIMIT 1
    ) AS member_email
  FROM user_activity_log_data ual
  WHERE ual.change_type IN ('GRANT_ROLE_GROUP', 'REVOKE_ROLE_GROUP')
    AND ual.subject_id IN (SELECT DISTINCT resolved_group_name FROM group_grants)
),

ranked_members AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY group_internal_name, member_email
      ORDER BY change_timestamp DESC
    ) AS rn
  FROM member_events
  WHERE member_email IS NOT NULL
),

current_members AS (
  SELECT *
  FROM ranked_members
  WHERE rn = 1
    AND change_type = 'GRANT_ROLE_GROUP'
),

group_rows AS (
  SELECT
    gg.change_date,
    'GROUP' AS grant_level,
    gg.change_subject_id AS granted_to,
    gg.user_facing_group_name,
    gg.resolved_group_name AS internal_name,
    gg.workspace_user_facing_id AS workspace,
    gg.org_user_facing_id AS org,
    gg.actor_email AS granted_by,
    gg.change_date AS effective_access_date,
    gg.granted_role,
    CAST(NULL AS STRING) AS group_member_role
  FROM group_grants gg

  UNION ALL

  SELECT
    ug.change_date,
    'GROUP' AS grant_level,
    ug.change_subject_id AS granted_to,
    CAST(NULL AS STRING) AS user_facing_group_name,
    REGEXP_EXTRACT(ug.change_subject_id, r'^(.+)@verily-bvdp\.com$') AS internal_name,
    ug.workspace_user_facing_id AS workspace,
    ug.org_user_facing_id AS org,
    ug.actor_email AS granted_by,
    ug.change_date AS effective_access_date,
    ug.granted_role,
    CAST(NULL AS STRING) AS group_member_role
  FROM unresolved_group_grants ug
),

member_rows AS (
  SELECT
    cm.change_timestamp AS change_date,
    'MEMBER' AS grant_level,
    cm.member_email AS granted_to,
    gg.user_facing_group_name,
    cm.group_internal_name AS internal_name,
    gg.workspace_user_facing_id AS workspace,
    gg.org_user_facing_id AS org,
    cm.member_granted_by AS granted_by,
    CASE
      WHEN cm.change_timestamp > gg.group_grant_date THEN cm.change_timestamp
      ELSE gg.group_grant_date
    END AS effective_access_date,
    gg.granted_role,
    cm.member_role AS group_member_role
  FROM current_members cm
  INNER JOIN (SELECT DISTINCT resolved_group_name, user_facing_group_name, workspace_user_facing_id, org_user_facing_id, change_date AS group_grant_date, granted_role FROM group_grants) gg
    ON cm.group_internal_name = gg.resolved_group_name
  WHERE cm.change_timestamp > gg.group_grant_date
),

member_events_with_prev AS (
  SELECT
    me.*,
    LAG(me.change_type) OVER (
      PARTITION BY me.group_internal_name, me.member_email
      ORDER BY me.change_timestamp
    ) AS prev_change_type
  FROM member_events me
  WHERE me.member_email IS NOT NULL
),

revoked_member_rows AS (
  SELECT
    mp.change_timestamp AS change_date,
    'MEMBER' AS grant_level,
    mp.member_email AS granted_to,
    gg.user_facing_group_name,
    mp.group_internal_name AS internal_name,
    gg.workspace_user_facing_id AS workspace,
    gg.org_user_facing_id AS org,
    mp.member_granted_by AS granted_by,
    mp.change_timestamp AS effective_access_date,
    REGEXP_REPLACE(gg.granted_role, r' \(REVOKED.*', '') || ' (REVOKED ' || FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', mp.change_timestamp) || ')' AS granted_role,
    mp.member_role AS group_member_role
  FROM member_events_with_prev mp
  INNER JOIN (SELECT DISTINCT resolved_group_name, user_facing_group_name, workspace_user_facing_id, org_user_facing_id, change_date AS group_grant_date, granted_role FROM group_grants) gg
    ON mp.group_internal_name = gg.resolved_group_name
  WHERE mp.change_type = 'REVOKE_ROLE_GROUP'
    AND mp.prev_change_type = 'GRANT_ROLE_GROUP'
    AND mp.change_timestamp > gg.group_grant_date
),

individual_rows AS (
  SELECT
    wg.change_date,
    'INDIVIDUAL' AS grant_level,
    wg.change_subject_id AS granted_to,
    CAST(NULL AS STRING) AS user_facing_group_name,
    CAST(NULL AS STRING) AS internal_name,
    wg.workspace_user_facing_id AS workspace,
    wg.org_user_facing_id AS org,
    wg.actor_email AS granted_by,
    wg.change_date AS effective_access_date,
    wg.granted_role,
    CAST(NULL AS STRING) AS group_member_role
  FROM workspace_grants wg
  WHERE wg.dc_grant_type != 'GROUP'
)

SELECT FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', change_date) AS change_date, grant_level, granted_to, user_facing_group_name, internal_name, workspace, org, granted_by, effective_access_date, granted_role, group_member_role FROM group_rows
UNION ALL
SELECT FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', change_date) AS change_date, grant_level, granted_to, user_facing_group_name, internal_name, workspace, org, granted_by, effective_access_date, granted_role, group_member_role FROM member_rows
UNION ALL
SELECT FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', change_date) AS change_date, grant_level, granted_to, user_facing_group_name, internal_name, workspace, org, granted_by, effective_access_date, granted_role, group_member_role FROM revoked_member_rows
UNION ALL
SELECT FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', change_date) AS change_date, grant_level, granted_to, user_facing_group_name, internal_name, workspace, org, granted_by, effective_access_date, granted_role, group_member_role FROM individual_rows
ORDER BY change_date DESC NULLS LAST
'''

GROUP_MEMBERS_AT_QUERY = '''
WITH
{user_activity_log_ctes}
group_events AS (
  SELECT
    ual.subject_id AS group_internal_name,
    ual.change_type,
    ual.change_timestamp,
    ual.actor_email AS acted_by,
    JSON_VALUE(ual.properties, '$.comment') AS reason,
    (
      SELECT REGEXP_EXTRACT(JSON_VALUE(elem, '$.resourceId'), r'(?i)^(.+):USER$')
      FROM UNNEST(JSON_EXTRACT_ARRAY(ual.related_resources)) AS elem
      WHERE JSON_VALUE(elem, '$.resourceType') = 'PRINCIPAL'
      LIMIT 1
    ) AS member_email
  FROM user_activity_log_data ual
  WHERE ual.change_type IN ('GRANT_ROLE_GROUP', 'REVOKE_ROLE_GROUP')
    AND ual.subject_id = @group_name
    AND ual.change_timestamp <= @as_of_timestamp
),

ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY member_email
      ORDER BY change_timestamp DESC
    ) AS rn
  FROM group_events
  WHERE member_email IS NOT NULL
)

SELECT
  member_email,
  change_timestamp AS added_at,
  acted_by AS added_by,
  reason
FROM ranked
WHERE rn = 1
  AND change_type = 'GRANT_ROLE_GROUP'
ORDER BY change_timestamp DESC
'''




########################################################################################################################################################


BASE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Data Collection Access Logging</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Open+Sans:wght@300;400;600;700&family=Poppins:wght@500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --primary-teal: #087a6a;
      --dark-teal: #074D43;
      --hover-teal: #054f45;
      --lighter-teal: #84bdb5;
      --light-gray-bg: #F5F6F7;
      --white: #ffffff;
      --dark-bg: #1A1A1A;
      --border-gray: #dee2e6;
      --primary-text: #212529;
      --secondary-text: rgba(0, 0, 0, 0.60);
      --font-body: "Open Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-hero: "Poppins", sans-serif;
      --border-radius: 0.375rem;
      --border-radius-lg: 0.5rem;
      --border-radius-xl: 1rem;
      --shadow-sm: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
      --shadow: 0 0.5rem 1rem rgba(0, 0, 0, 0.15);
      --focus-ring: 0 0 0 0.25rem rgba(8, 122, 106, 0.25);
    }

    * { margin: 0; padding: 0; box-sizing: border-box; }

    body {
      font-family: var(--font-body);
      color: var(--primary-text);
      line-height: 1.5;
      font-size: 1rem;
      background-color: var(--white);
    }

    .navbar {
      background-color: var(--primary-teal);
      color: var(--white);
      padding: 0.75rem 2rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .navbar-brand {
      font-family: var(--font-hero);
      font-weight: 600;
      font-size: 1.15rem;
      color: var(--white);
      text-decoration: none;
    }
    .navbar-env {
      display: inline-block;
      padding: 0.2rem 0.6rem;
      border-radius: var(--border-radius);
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-left: 0.75rem;
      vertical-align: middle;
    }
    .navbar-env-prod { background: rgba(255,255,255,0.2); color: var(--white); }
    .navbar-env-dev { background: #b6d0ff; color: #1A1A1A; }
    .navbar-env-test { background: #fef7e0; color: #1A1A1A; }

    .nav-tabs {
      display: flex;
      gap: 0;
      border-bottom: 2px solid var(--border-gray);
      margin-bottom: 1.5rem;
    }
    .nav-tabs a {
      padding: 0.75rem 1.25rem;
      color: var(--secondary-text);
      text-decoration: none;
      font-weight: 600;
      font-size: 0.95rem;
      border-bottom: 3px solid transparent;
      margin-bottom: -2px;
      transition: color 0.15s, border-color 0.15s;
    }
    .nav-tabs a:hover { color: var(--primary-teal); }
    .nav-tabs a.active {
      color: var(--primary-teal);
      border-bottom-color: var(--primary-teal);
    }

    .container { max-width: 1200px; margin: 0 auto; padding: 0 2rem; }

    .page-header {
      margin: 2rem 0 0.5rem;
    }
    .page-header h2 {
      font-family: var(--font-hero);
      font-size: 1.5rem;
      font-weight: 600;
      color: var(--primary-text);
      margin-bottom: 0.5rem;
    }
    .page-header p {
      color: var(--secondary-text);
      font-size: 0.95rem;
      margin-bottom: 0;
    }

    .search-card {
      background: var(--light-gray-bg);
      border-radius: var(--border-radius-xl);
      padding: 1.5rem;
      margin: 1.5rem 0;
    }
    .search-form {
      display: flex;
      gap: 0.75rem;
      align-items: flex-end;
      flex-wrap: wrap;
    }
    .form-group {
      display: flex;
      flex-direction: column;
      flex: 1;
      min-width: 250px;
    }
    .form-group label {
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--secondary-text);
      margin-bottom: 0.375rem;
    }
    .form-input {
      width: 100%;
      padding: 0.625rem 1rem;
      font-size: 1rem;
      font-family: var(--font-body);
      border: 1px solid var(--border-gray);
      border-radius: var(--border-radius);
      color: var(--primary-text);
      background: var(--white);
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    .form-input:focus {
      outline: none;
      border-color: var(--lighter-teal);
      box-shadow: var(--focus-ring);
    }
    .form-input::placeholder { color: var(--secondary-text); }

    .btn {
      display: inline-block;
      font-weight: 600;
      font-family: var(--font-body);
      line-height: 1.5;
      text-align: center;
      cursor: pointer;
      border: 1px solid transparent;
      padding: 0.625rem 1.5rem;
      font-size: 1rem;
      border-radius: var(--border-radius);
      transition: background-color 0.15s, border-color 0.15s, box-shadow 0.15s;
      white-space: nowrap;
    }
    .btn-primary {
      background-color: var(--primary-teal);
      border-color: var(--primary-teal);
      color: var(--white);
    }
    .btn-primary:hover {
      background-color: var(--hover-teal);
      border-color: var(--hover-teal);
    }
    .btn-primary:focus { box-shadow: var(--focus-ring); }

    .results-table {
      width: auto;
      max-width: 100%;
      margin: 1.5rem auto 0;
      border-collapse: separate;
      border-spacing: 0;
      font-size: 0.9rem;
      border: 1px solid var(--border-gray);
      border-radius: var(--border-radius-lg);
      overflow: hidden;
    }
    .results-table th {
      background: var(--light-gray-bg);
      font-weight: 600;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      color: var(--secondary-text);
      padding: 0.75rem 1rem;
      text-align: left;
      white-space: nowrap;
      position: relative;
      border-bottom: 2px solid var(--border-gray);
    }
    .results-table td {
      padding: 0.65rem 1rem;
      text-align: left;
      word-break: break-word;
      border-bottom: 1px solid var(--border-gray);
    }
    .results-table tbody tr:last-child td { border-bottom: none; }
    .results-table tbody tr:hover { background-color: rgba(8, 122, 106, 0.04); }

    .alert {
      padding: 0.75rem 1rem;
      border-radius: var(--border-radius);
      margin-top: 1rem;
      font-size: 0.95rem;
    }
    .alert-error {
      background: #fce8e6;
      color: #c5221f;
      border: 1px solid #f5c6cb;
    }
    .alert-info {
      background: var(--light-gray-bg);
      color: var(--secondary-text);
      border: 1px solid var(--border-gray);
    }

    .forensic-section {
      margin-top: 2.5rem;
      padding-top: 2rem;
      border-top: 2px solid var(--border-gray);
    }
    .forensic-section h3 {
      font-family: var(--font-hero);
      font-size: 1.25rem;
      font-weight: 600;
      color: var(--primary-text);
      margin-bottom: 0.5rem;
    }
    .forensic-section p {
      color: var(--secondary-text);
      font-size: 0.9rem;
      margin-bottom: 0;
    }
    .badge-grant {
      display: inline-block;
      padding: 0.2rem 0.5rem;
      border-radius: var(--border-radius);
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    .badge-group {
      background-color: var(--primary-teal);
      color: var(--white);
    }
    .badge-individual {
      background-color: var(--light-gray-bg);
      color: var(--secondary-text);
      border: 1px solid var(--border-gray);
    }
    .badge-member {
      background-color: var(--lighter-teal);
      color: var(--dark-teal);
    }
    .row-member {
      border-left: 3px solid var(--lighter-teal);
    }
    .row-member td:first-child {
      padding-left: calc(1rem + 12px);
    }
    .row-group {
      border-left: 3px solid var(--primary-teal);
    }
    .row-group td:first-child {
      padding-left: calc(1rem - 3px);
    }

    .footer {
      background-color: var(--dark-bg);
      color: var(--white);
      padding: 1.5rem 2rem;
      margin-top: 3rem;
      font-size: 0.8rem;
    }
    .footer a {
      color: #B1B9C2;
      text-decoration: none;
    }
    .footer a:hover { color: var(--primary-teal); }

    .table-filter {
      width: 100%;
      padding: 0.5rem 0.75rem;
      font-size: 0.9rem;
      font-family: var(--font-body);
      border: 1px solid var(--border-gray);
      border-radius: var(--border-radius);
      margin-bottom: 0.75rem;
    }
    .table-filter:focus {
      outline: none;
      border-color: var(--lighter-teal);
      box-shadow: var(--focus-ring);
    }
    .results-table th.sortable {
      cursor: pointer;
      user-select: none;
    }
    .results-table th.sortable:hover {
      color: var(--primary-teal);
    }
    .results-table th .sort-arrow {
      font-size: 0.65rem;
      margin-left: 0.3rem;
      opacity: 0.4;
    }
    .results-table th.sort-asc .sort-arrow,
    .results-table th.sort-desc .sort-arrow {
      opacity: 1;
      color: var(--primary-teal);
    }

    .resize-handle {
      position: absolute;
      right: 0;
      top: 0;
      bottom: 0;
      width: 4px;
      cursor: col-resize;
      background: transparent;
    }
    .resize-handle:hover,
    .resize-handle.active {
      background: var(--primary-teal);
    }
    .results-table.resizing {
      user-select: none;
    }

    .col-filter-wrap { position: relative; display: inline; }
    .col-filter-text { cursor: pointer; border-bottom: 1px dashed rgba(0,0,0,0.3); }
    .col-filter-text:hover { color: var(--primary-teal); }
    .col-filter-dropdown {
      display: none; position: absolute; top: 100%; left: 0; z-index: 100;
      background: #fff; border: 1px solid var(--border-gray); border-radius: 6px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.12); padding: 0.5rem 0.75rem;
      min-width: 160px; font-size: 0.82rem; font-weight: normal; text-transform: none;
    }
    .col-filter-dropdown.open { display: block; }
    .col-filter-dropdown label { display: block; padding: 0.25rem 0; cursor: pointer; white-space: nowrap; }

    @media (max-width: 768px) {
      .container { padding: 0 1rem; }
      .search-form { flex-direction: column; }
      .form-group { min-width: 100%; }
      .results-table { font-size: 0.8rem; }
      .results-table th, .results-table td { padding: 0.5rem 0.6rem; }
    }
  </style>
</head>
<body>
  <nav class="navbar">
    <div>
      <span class="navbar-brand">Data Collection Access Logging</span>
      <span class="navbar-env navbar-env-{{ env }}">{{ env }}</span>
    </div>
  </nav>

  <div class="container" style="margin-top: 2rem;">
    <div class="nav-tabs">
      <a href="./" class="{{ 'active' if active_tab == 'ws_forensic' else '' }}">Forensic: Data Collection</a>
      <a href="group-audit" class="{{ 'active' if active_tab == 'group_audit' else '' }}">Group Membership Audit</a>
    </div>

    {% block content %}{% endblock %}
  </div>

  <script>
  document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.results-table').forEach(function(table) {
      var wrapper = table.parentNode;

      var filterRow = document.createElement('div');
      filterRow.style.cssText = 'display:flex; align-items:center; gap:0.5rem;';

      var filter = document.createElement('input');
      filter.type = 'text';
      filter.className = 'table-filter';
      filter.placeholder = 'Filter rows (space-separated keywords)...';
      filter.style.flex = '1';
      filterRow.appendChild(filter);

      var toggleWrap = document.createElement('div');
      toggleWrap.style.cssText = 'display:flex; border:1px solid var(--border-gray); border-radius:4px; overflow:hidden; font-size:0.8rem; font-weight:600; cursor:pointer; flex-shrink:0;';

      var andBtn = document.createElement('span');
      andBtn.textContent = 'AND';
      andBtn.style.cssText = 'padding:0.4rem 0.6rem; background:var(--primary-teal); color:#fff; transition:all 0.15s;';

      var orBtn = document.createElement('span');
      orBtn.textContent = 'OR';
      orBtn.style.cssText = 'padding:0.4rem 0.6rem; background:#fff; color:#888; transition:all 0.15s;';

      toggleWrap.appendChild(andBtn);
      toggleWrap.appendChild(orBtn);
      filterRow.appendChild(toggleWrap);

      wrapper.insertBefore(filterRow, table);

      var useAnd = true;
      function updateToggle() {
        andBtn.style.background = useAnd ? 'var(--primary-teal)' : '#fff';
        andBtn.style.color = useAnd ? '#fff' : '#888';
        orBtn.style.background = useAnd ? '#fff' : 'var(--primary-teal)';
        orBtn.style.color = useAnd ? '#888' : '#fff';
        filter.dispatchEvent(new Event('input'));
      }
      andBtn.addEventListener('click', function() { useAnd = true; updateToggle(); });
      orBtn.addEventListener('click', function() { useAnd = false; updateToggle(); });

      filter.addEventListener('input', function() {
        var terms = this.value.toLowerCase().split(/\s+/).filter(function(t) { return t; });
        table.querySelectorAll('tbody tr').forEach(function(row) {
          var text = row.textContent.toLowerCase();
          var match = terms.length === 0 || (useAnd
            ? terms.every(function(t) { return text.indexOf(t) > -1; })
            : terms.some(function(t) { return text.indexOf(t) > -1; }));
          row.style.display = match ? '' : 'none';
        });
      });

      var didResize = false;

      table.querySelectorAll('thead th').forEach(function(th, colIdx) {
        if (th.classList.contains('no-sort')) return;
        th.classList.add('sortable');
        var arrow = document.createElement('span');
        arrow.className = 'sort-arrow';
        arrow.innerHTML = '&#9650;';
        th.appendChild(arrow);
        arrow.addEventListener('click', function(e) {
          e.stopPropagation();
          if (didResize) { didResize = false; return; }
          var tbody = table.querySelector('tbody');
          // Collapse all expanded detail rows before sorting
          tbody.querySelectorAll('.member-detail-row').forEach(function(d) { d.remove(); });
          tbody.querySelectorAll('.expand-toggle').forEach(function(t) { t.innerHTML = '&#9654;'; });
          var allRows = Array.from(tbody.querySelectorAll('tr'));
          var groups = [];
          allRows.forEach(function(row) {
            if (!row.classList.contains('member-detail-row')) {
              groups.push({ main: row, details: [] });
            } else if (groups.length) {
              groups[groups.length - 1].details.push(row);
            }
          });
          var asc = !th.classList.contains('sort-asc');
          table.querySelectorAll('th').forEach(function(h) {
            h.classList.remove('sort-asc', 'sort-desc');
          });
          th.classList.add(asc ? 'sort-asc' : 'sort-desc');
          th.querySelector('.sort-arrow').innerHTML = asc ? '&#9650;' : '&#9660;';
          groups.sort(function(a, b) {
            var av = (a.main.cells[colIdx] || {}).textContent || '';
            var bv = (b.main.cells[colIdx] || {}).textContent || '';
            var ad = Date.parse(av), bd = Date.parse(bv);
            if (!isNaN(ad) && !isNaN(bd)) return asc ? ad - bd : bd - ad;
            var an = parseFloat(av), bn = parseFloat(bv);
            if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
            return asc ? av.localeCompare(bv) : bv.localeCompare(av);
          });
          groups.forEach(function(g) {
            tbody.appendChild(g.main);
            g.details.forEach(function(d) { tbody.appendChild(d); });
          });
        });

        var handle = document.createElement('div');
        handle.className = 'resize-handle';
        th.appendChild(handle);

        handle.addEventListener('mousedown', function(e) {
          e.preventDefault();
          e.stopPropagation();
          var startX = e.pageX;
          var startWidth = th.offsetWidth;
          handle.classList.add('active');
          table.classList.add('resizing');
          table.style.tableLayout = 'fixed';

          function onMouseMove(e) {
            th.style.width = Math.max(40, startWidth + e.pageX - startX) + 'px';
          }
          function onMouseUp() {
            handle.classList.remove('active');
            table.classList.remove('resizing');
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
            didResize = true;
            setTimeout(function() { didResize = false; }, 100);
          }
          document.addEventListener('mousemove', onMouseMove);
          document.addEventListener('mouseup', onMouseUp);
        });
      });
    });

    // Persist search value and org override across tabs
    var params = new URLSearchParams(window.location.search);
    var dcValue = params.get('workspace_name') || params.get('dc_id') || '';
    var orgValue = params.get('org_override') || '';
    if (dcValue || orgValue) {
      document.querySelectorAll('.nav-tabs a').forEach(function(link) {
        var href = link.getAttribute('href');
        if (link.classList.contains('active')) return;
        var p = new URLSearchParams();
        if (href === './' || href === '' || href === 'forensic-v2') {
          if (dcValue) p.set('workspace_name', dcValue);
        } else if (href === 'dc-access') {
          if (dcValue) p.set('dc_id', dcValue);
        }
        if (orgValue) p.set('org_override', orgValue);
        if (p.toString()) link.href = href + '?' + p.toString();
      });
    }
  });
  </script>

  <footer class="footer">
    <div class="container" style="display: flex; justify-content: space-between; align-items: center;">
      <span>Verily Workbench</span>
    </div>
  </footer>
</body>
</html>
"""

DC_ACCESS_CONTENT = """
  <div class="page-header">
    <h2>Data Collection Access by Group Membership</h2>
    <p>Shows which individuals hold which roles on a data collection,
    via which group memberships, and when that access was granted.</p>
  </div>

  <div class="search-card">
    <form action="dc-access" method="get" class="search-form">
      <div class="form-group">
        <label for="dc_id">Data Collection ID</label>
        <input type="text" class="form-input" id="dc_id" name="dc_id" placeholder="e.g. dc-example-123" value="{{ dc_id or '' }}" required />
      </div>
      <div class="form-group">
        <label for="org_override">Org Override <span style="font-weight:normal; color:#888;">(optional — defaults to {{ default_org or 'config value' }})</span></label>
        <input type="text" class="form-input" id="org_override" name="org_override" placeholder="e.g. my-org-id" value="{{ org_override or '' }}" />
      </div>
      <button type="submit" class="btn btn-primary">Look up</button>
    </form>
  </div>

  {% if error %}
    <div class="alert alert-error">{{ error }}</div>
  {% endif %}

  {% if rows is not none and rows|length == 0 %}
    <div class="alert alert-info">No group-based access found for data collection "{{ dc_id }}".</div>
  {% endif %}

  {% if rows %}
    <table class="results-table">
      <thead>
        <tr>
          <th>User Email</th>
          <th>Role on Collection</th>
          <th>Group Name</th>
          <th>Access Granted At</th>
          <th>Granted By</th>
          <th>Grant Reason</th>
        </tr>
      </thead>
      <tbody>
        {% for r in rows %}
        <tr>
          <td>{{ r.user_email }}</td>
          <td>{{ r.role_on_collection }}</td>
          <td>{{ r.group_name }}</td>
          <td>{{ r.access_granted_at or '—' }}</td>
          <td>{{ r.granted_by or '—' }}</td>
          <td>{{ r.grant_reason or '—' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  {% endif %}
"""

GROUP_MEMBERSHIP_CONTENT = """
  <div class="page-header">
    <h2>Group Membership with Grant Timestamps</h2>
    <p>Lists all individuals who currently have access via membership
    in a group and when that access was conferred.</p>
  </div>

  <div class="search-card">
    <form action="group" method="get" class="search-form">
      <div class="form-group">
        <label for="group_name">Group Name</label>
        <input type="text" class="form-input" id="group_name" name="group_name" placeholder="e.g. bhs-limited-readers" value="{{ group_name or '' }}" required />
      </div>
      <div class="form-group">
        <label for="org_override">Org Override <span style="font-weight:normal; color:#888;">(optional — defaults to {{ default_org or 'config value' }})</span></label>
        <input type="text" class="form-input" id="org_override" name="org_override" placeholder="e.g. my-org-id" value="{{ org_override or '' }}" />
      </div>
      <button type="submit" class="btn btn-primary">Look up</button>
    </form>
  </div>

  {% if error %}
    <div class="alert alert-error">{{ error }}</div>
  {% endif %}

  {% if rows is not none and rows|length == 0 %}
    <div class="alert alert-info">No current members found for this group.</div>
  {% endif %}

  {% if rows %}
    <table class="results-table">
      <thead>
        <tr>
          <th>Member Email</th>
          <th>Group Internal Name</th>
          <th>Group Role</th>
          <th>Access Granted At</th>
          <th>Granted By</th>
          <th>Grant Reason</th>
        </tr>
      </thead>
      <tbody>
        {% for r in rows %}
        <tr>
          <td>{{ r.member_email }}</td>
          <td>{{ r.group_internal_name }}</td>
          <td>{{ r.group_role }}</td>
          <td>{{ r.access_granted_at or '—' }}</td>
          <td>{{ r.granted_by or '—' }}</td>
          <td>{{ r.grant_reason or '—' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  {% endif %}

"""


FORENSIC_V2_CONTENT = """
  <div class="page-header">
    <h3>Forensic View v2: Full Access Timeline</h3>
    <p>Unified timeline of data collection access — workspace-level grants/revocations and group membership changes from the activity log.</p>
  </div>

  <div class="search-card">
    <form action="forensic-v2" method="get" class="search-form">
      <div class="form-group">
        <label for="workspace_name">Data Collection ID</label>
        <input type="text" class="form-input" id="workspace_name" name="workspace_name" placeholder="e.g. demo-dc-1" value="{{ workspace_name or '' }}" required />
      </div>
      <div class="form-group">
        <label for="org_override">Org Override <span style="font-weight:normal; color:#888;">(optional — defaults to {{ default_org or 'config value' }})</span></label>
        <input type="text" class="form-input" id="org_override" name="org_override" placeholder="e.g. my-org-id" value="{{ org_override or '' }}" />
      </div>
      <button type="submit" class="btn btn-primary">Look up</button>
    </form>
  </div>

  {% if error %}
    <div class="alert alert-error">{{ error }}</div>
  {% endif %}

  {% if rows is not none and rows|length == 0 %}
    <div class="alert alert-info">No events found for data collection "{{ workspace_name }}".</div>
  {% endif %}

  {% if rows %}
    <div style="margin-top: 1.25rem; margin-bottom: 1.25rem; display: flex; flex-direction: column; gap: 0.75rem; font-size: 0.85rem;">
      <div style="display: flex; align-items: center; gap: 0.75rem;">
        <span style="color: #555; min-width: 5rem;">Action:</span>
        <label style="cursor:pointer;"><input type="checkbox" class="v2-action-filter" value="DC ACCESS GRANTED" checked> DC ACCESS GRANTED</label>
        <label style="cursor:pointer;"><input type="checkbox" class="v2-action-filter" value="DC ACCESS REVOKED" checked> DC ACCESS REVOKED</label>
        <label style="cursor:pointer;"><input type="checkbox" class="v2-action-filter" value="ADDED TO GROUP" checked> ADDED TO GROUP</label>
        <label style="cursor:pointer;"><input type="checkbox" class="v2-action-filter" value="REMOVED FROM GROUP" checked> REMOVED FROM GROUP</label>
      </div>
      <div style="display: flex; align-items: center; gap: 0.75rem;">
        <span style="color: #555; min-width: 5rem;">Type:</span>
        <label style="cursor:pointer;"><input type="checkbox" class="v2-type-filter" value="GROUP" checked> GROUP</label>
        <label style="cursor:pointer;"><input type="checkbox" class="v2-type-filter" value="MEMBER" checked> MEMBER</label>
        <label style="cursor:pointer;"><input type="checkbox" class="v2-type-filter" value="INDIVIDUAL" checked> INDIVIDUAL</label>
      </div>
      <div style="display: flex; align-items: center; gap: 0.75rem;">
        <span style="color: #555; min-width: 5rem;">Status:</span>
        <label style="cursor:pointer;"><input type="checkbox" id="v2-hide-revoked"> Hide revocations</label>
      </div>
    </div>
    <table class="results-table">
      <thead>
        <tr>
          <th>Timestamp</th>
          <th style="min-width: 130px;">Action</th>
          <th>Type</th>
          <th>Subject</th>
          <th>Group</th>
          <th style="min-width: 120px;">Role</th>
          <th>Acted By</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {% for r in rows %}
        <tr data-action="{{ r.action }}" data-subject-type="{{ r.subject_type }}" data-revoked="{{ 'true' if 'REVOK' in r.action or 'REMOVED' in r.action else 'false' }}">
          <td>{{ r.event_timestamp_fmt or '—' }}</td>
          <td><span class="badge-grant" style="{{ 'background:#ffebee; color:#c62828;' if 'REVOK' in r.action or 'REMOVED' in r.action else 'background:#e8f5e9; color:#2e7d32;' }}">{{ r.action }}</span></td>
          <td><span class="badge-grant {{ 'badge-group' if r.subject_type == 'GROUP' else ('badge-member' if r.subject_type == 'MEMBER' else 'badge-individual') }}">{{ r.subject_type }}</span></td>
          <td>{{ r.subject }}</td>
          <td>{{ r.group_name or '—' }}</td>
          <td>{{ r.role or '—' }}</td>
          <td>{{ r.actor_email or '—' }}</td>
          <td>{{ r.reason or '—' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <script>
    (function() {
      function applyV2Filters() {
        var actions = {};
        document.querySelectorAll('.v2-action-filter').forEach(function(cb) { actions[cb.value] = cb.checked; });
        var types = {};
        document.querySelectorAll('.v2-type-filter').forEach(function(cb) { types[cb.value] = cb.checked; });
        var hideRevoked = document.getElementById('v2-hide-revoked').checked;
        document.querySelectorAll('tbody tr[data-action]').forEach(function(row) {
          var show = actions[row.dataset.action] !== false
            && types[row.dataset.subjectType] !== false
            && !(hideRevoked && row.dataset.revoked === 'true');
          row.style.display = show ? '' : 'none';
        });
      }
      document.querySelectorAll('.v2-action-filter, .v2-type-filter').forEach(function(cb) { cb.addEventListener('change', applyV2Filters); });
      document.getElementById('v2-hide-revoked').addEventListener('change', applyV2Filters);
    })();
    </script>
  {% endif %}
"""


GROUP_AUDIT_CONTENT = """
  <div class="page-header">
    <h2>Group Membership Audit</h2>
    <p>Full history of group membership changes — shows all grants and revocations from the activity log.</p>
  </div>

  <div class="search-card">
    <form action="group-audit" method="get" class="search-form">
      <div class="form-group">
        <label for="group_name">Group Name</label>
        <input type="text" class="form-input" id="group_name" name="group_name" placeholder="e.g. demo-readers" value="{{ group_name or '' }}" required />
      </div>
      <div class="form-group">
        <label for="org_override">Org Override <span style="font-weight:normal; color:#888;">(optional — defaults to {{ default_org or 'config value' }})</span></label>
        <input type="text" class="form-input" id="org_override" name="org_override" placeholder="e.g. my-org-id" value="{{ org_override or '' }}" />
      </div>
      <button type="submit" class="btn btn-primary">Look up</button>
    </form>
  </div>

  {% if error %}
    <div class="alert alert-error">{{ error }}</div>
  {% endif %}

  {% if rows is not none and rows|length == 0 %}
    <div class="alert alert-info">No membership events found for group "{{ group_name }}".</div>
  {% endif %}

  {% if rows %}
    {% set ga_roles = [] %}
    {% for r in rows %}{% if r.group_role and r.group_role not in ga_roles %}{% if ga_roles.append(r.group_role) %}{% endif %}{% endif %}{% endfor %}
    <div style="margin-top: 1rem; margin-bottom: 1rem; font-size: 0.85rem;">
      <label style="cursor:pointer;"><input type="checkbox" id="ga-current-only"> Current members only</label>
    </div>
    <table class="results-table">
      <thead>
        <tr>
          <th>Timestamp</th>
          <th style="min-width: 130px;">
            <div class="col-filter-wrap"><span class="col-filter-text" data-filter-target="ga-action-dropdown">Action</span>
              <div class="col-filter-dropdown" id="ga-action-dropdown">
                <label><input type="checkbox" class="ga-action-filter" value="GRANTED" checked> GRANTED</label>
                <label><input type="checkbox" class="ga-action-filter" value="REVOKED" checked> REVOKED</label>
              </div>
            </div>
          </th>
          <th>Member Email</th>
          <th>Group Name</th>
          <th style="min-width: 120px;">
            <div class="col-filter-wrap"><span class="col-filter-text" data-filter-target="ga-role-dropdown">Role</span>
              <div class="col-filter-dropdown" id="ga-role-dropdown">
                {% for role in ga_roles|sort %}
                <label><input type="checkbox" class="ga-role-filter" value="{{ role }}" checked> {{ role }}</label>
                {% endfor %}
              </div>
            </div>
          </th>
          <th>Acted By</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        {% for r in rows %}
        <tr data-action="{{ r.action }}" data-member="{{ r.member_email }}" data-role="{{ r.group_role or '' }}">
          <td>{{ r.change_timestamp or '—' }}</td>
          <td><span class="badge-grant {{ 'badge-group' if r.action == 'GRANTED' else 'badge-individual' }}" style="{{ 'background:#ffebee; color:#c62828;' if r.action == 'REVOKED' else '' }}">{{ r.action }}</span></td>
          <td>{{ r.member_email }}</td>
          <td>{{ r.user_facing_group_name or '—' }}</td>
          <td>{{ r.group_role or '—' }}</td>
          <td>{{ r.acted_by or '—' }}</td>
          <td>{{ r.reason or '—' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <script>
    (function() {
      // Column filter dropdowns
      document.querySelectorAll('.col-filter-text').forEach(function(text) {
        text.addEventListener('click', function(e) {
          e.stopPropagation();
          var dropdown = document.getElementById(this.dataset.filterTarget);
          var wasOpen = dropdown.classList.contains('open');
          document.querySelectorAll('.col-filter-dropdown.open').forEach(function(d) { d.classList.remove('open'); });
          if (!wasOpen) { dropdown.classList.add('open'); }
        });
      });
      document.querySelectorAll('.col-filter-dropdown').forEach(function(dd) {
        dd.addEventListener('click', function(e) { e.stopPropagation(); });
      });
      document.addEventListener('click', function() {
        document.querySelectorAll('.col-filter-dropdown.open').forEach(function(d) { d.classList.remove('open'); });
      });

      // Build map of each member's latest action (rows are sorted by timestamp DESC)
      var latestAction = {};
      document.querySelectorAll('tbody tr[data-member]').forEach(function(row) {
        var member = row.dataset.member;
        if (!latestAction[member]) latestAction[member] = row.dataset.action;
      });

      function applyGAFilters() {
        var actions = {};
        document.querySelectorAll('.ga-action-filter').forEach(function(cb) { actions[cb.value] = cb.checked; });
        var roles = {};
        document.querySelectorAll('.ga-role-filter').forEach(function(cb) { roles[cb.value] = cb.checked; });
        var currentOnly = document.getElementById('ga-current-only').checked;
        document.querySelectorAll('tbody tr[data-action]').forEach(function(row) {
          var role = row.dataset.role;
          var show = actions[row.dataset.action] !== false
            && (role === '' || roles[role] !== false)
            && !(currentOnly && latestAction[row.dataset.member] === 'REVOKED');
          row.style.display = show ? '' : 'none';
        });
      }
      document.querySelectorAll('.ga-action-filter, .ga-role-filter').forEach(function(cb) { cb.addEventListener('change', applyGAFilters); });
      document.getElementById('ga-current-only').addEventListener('change', applyGAFilters);
    })();
    </script>
  {% endif %}
"""


WORKSPACE_FORENSIC_CONTENT = """
  <div class="page-header">
    <h3>Forensic View: Data Collection Access Grant History</h3>
    <p>Shows all data collection access grants — groups, their members at time of grant, and individual users. Expand a group row to see who was already in the group when it was granted access.</p>
  </div>

  <div class="search-card">
    <form action="./" method="get" class="search-form">
      <div class="form-group">
        <label for="workspace_name">Data Collection ID</label>
        <input type="text" class="form-input" id="workspace_name" name="workspace_name" placeholder="e.g. 1000-genomes-data-collection" value="{{ workspace_name or '' }}" required />
      </div>
      <div class="form-group">
        <label for="org_override">Org Override <span style="font-weight:normal; color:#888;">(optional — defaults to {{ default_org or 'config value' }})</span></label>
        <input type="text" class="form-input" id="org_override" name="org_override" placeholder="e.g. my-org-id" value="{{ org_override or '' }}" />
      </div>
      <button type="submit" class="btn btn-primary">Look up</button>
    </form>
  </div>

  {% if error %}
    <div class="alert alert-error">{{ error }}</div>
  {% endif %}

  {% if rows is not none and rows|length == 0 %}
    <div class="alert alert-info">No access grants found for data collection "{{ workspace_name }}".</div>
  {% endif %}

  {% if rows %}
    {% set roles = rows|map(attribute='granted_role')|map('default', '')|list %}
    {% set unique_roles = [] %}
    {% for r in roles %}{% set base = r.split(' (')[0] %}{% if base and base not in unique_roles %}{% if unique_roles.append(base) %}{% endif %}{% endif %}{% endfor %}
    <div style="margin-top: 1rem; margin-bottom: 1rem; display: flex; align-items: center; gap: 1.5rem; font-size: 0.85rem;">
      <div style="display: flex; align-items: center; gap: 0.5rem;">
        <span style="color: #555;">Column:</span>
        <button type="button" id="toggle-group-name" style="padding: 0.25rem 0.6rem; border: 1px solid var(--border-gray); border-radius: 4px; background: var(--primary-teal); color: #fff; cursor: pointer; font-size: 0.8rem;">Group Name</button>
        <button type="button" id="toggle-internal-name" style="padding: 0.25rem 0.6rem; border: 1px solid var(--border-gray); border-radius: 4px; background: #fff; color: #333; cursor: pointer; font-size: 0.8rem;">Internal Name</button>
      </div>
      <label style="cursor:pointer;"><input type="checkbox" id="hide-revoked"> Hide revoked</label>
    </div>
    <table class="results-table">
      <thead>
        <tr>
          <th style="width: 2rem;" class="no-sort"></th>
          <th>Event Date</th>
          <th style="min-width: 140px;">
            <div class="col-filter-wrap"><span class="col-filter-text" data-filter-target="grant-level-dropdown">Grant Level</span>
              <div class="col-filter-dropdown" id="grant-level-dropdown">
                <label><input type="checkbox" class="grant-level-filter" value="GROUP" checked> GROUP</label>
                <label><input type="checkbox" class="grant-level-filter" value="MEMBER" checked> MEMBER</label>
                <label><input type="checkbox" class="grant-level-filter" value="INDIVIDUAL" checked> INDIVIDUAL</label>
              </div>
            </div>
          </th>
          <th data-col="group-name">Group Name</th>
          <th data-col="internal-name" style="display:none;">Internal Name</th>
          <th>Granted To</th>
          <th style="min-width: 140px;">
            <div class="col-filter-wrap"><span class="col-filter-text" data-filter-target="role-dropdown">DC Role</span>
              <div class="col-filter-dropdown" id="role-dropdown">
                {% for role in unique_roles|sort %}
                <label><input type="checkbox" class="role-filter" value="{{ role }}" checked> {{ role }}</label>
                {% endfor %}
              </div>
            </div>
          </th>
          <th style="min-width: 140px;">Org</th>
          <th>Granted By</th>
        </tr>
      </thead>
      <tbody>
        {% for r in rows %}
        <tr class="{{ 'row-group' if r.grant_level == 'GROUP' else ('row-member' if r.grant_level == 'MEMBER' else '') }}" data-grant-level="{{ r.grant_level }}" data-revoked="{{ 'true' if r.granted_role and 'REVOKED' in r.granted_role else 'false' }}" data-role="{{ r.granted_role.split(' (')[0] if r.granted_role else '' }}" {% if r.grant_level == 'GROUP' and r.internal_name %}data-group-name="{{ r.internal_name }}" data-timestamp="{{ r.change_date }}"{% endif %}>
          <td>{% if r.grant_level == 'GROUP' and r.internal_name %}<span class="expand-toggle" style="cursor:pointer; user-select:none; font-size:0.75rem;">&#9654;</span>{% endif %}</td>
          <td>{{ r.change_date or '—' }}</td>
          <td><span class="badge-grant {{ 'badge-group' if r.grant_level == 'GROUP' else ('badge-member' if r.grant_level == 'MEMBER' else 'badge-individual') }}">{{ r.grant_level }}</span></td>
          <td data-col="group-name">{{ r.user_facing_group_name or '—' }}</td>
          <td data-col="internal-name" style="display:none;">{{ r.internal_name or '—' }}</td>
          <td>{{ r.granted_to }}</td>
          <td>{% if r.granted_role and '(REVOKED' in r.granted_role %}{{ r.granted_role.split(' (')[0] }}<br><span style="color:#c62828; font-size:0.8rem;">REVOKED {{ r.granted_role.split('REVOKED ')[1].rstrip(')') }}</span>{% else %}{{ r.granted_role or '—' }}{% endif %}</td>
          <td>{{ r.org or '—' }}</td>
          <td>{{ r.granted_by or '—' }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <script>
    document.querySelectorAll('.expand-toggle').forEach(function(toggle) {
      toggle.addEventListener('click', function() {
        var row = this.closest('tr');
        var groupName = row.dataset.groupName;
        var timestamp = row.dataset.timestamp;
        var existing = row.nextElementSibling;

        if (existing && existing.classList.contains('member-detail-row')) {
          existing.style.display = existing.style.display === 'none' ? '' : 'none';
          this.innerHTML = existing.style.display === 'none' ? '&#9654;' : '&#9660;';
          return;
        }

        this.innerHTML = '&#8230;';
        var colCount = row.cells.length;
        fetch('api/group-members-at?group_name=' + encodeURIComponent(groupName) + '&timestamp=' + encodeURIComponent(timestamp))
          .then(function(r) { return r.json(); })
          .then(function(members) {
            var detailRow = document.createElement('tr');
            detailRow.className = 'member-detail-row';
            var td = document.createElement('td');
            td.colSpan = colCount;
            td.style.padding = '0.5rem 1rem 1rem 2.5rem';
            td.style.background = 'rgba(8,122,106,0.03)';

            if (members.error) {
              td.textContent = 'Error: ' + members.error;
            } else if (members.length === 0) {
              td.innerHTML = '<em style="color:var(--secondary-text)">No members found in this group at that time.</em>';
            } else {
              var html = '<table style="width:100%; font-size:0.85rem; border-collapse:collapse;">';
              html += '<thead><tr style="border-bottom:1px solid var(--border-gray);">';
              html += '<th style="text-align:left;padding:0.4rem 0.6rem;font-weight:600;color:var(--secondary-text);font-size:0.75rem;text-transform:uppercase;">Member Email</th>';
              html += '<th style="text-align:left;padding:0.4rem 0.6rem;font-weight:600;color:var(--secondary-text);font-size:0.75rem;text-transform:uppercase;">Added At</th>';
              html += '<th style="text-align:left;padding:0.4rem 0.6rem;font-weight:600;color:var(--secondary-text);font-size:0.75rem;text-transform:uppercase;">Added By</th>';
              html += '<th style="text-align:left;padding:0.4rem 0.6rem;font-weight:600;color:var(--secondary-text);font-size:0.75rem;text-transform:uppercase;">Reason</th>';
              html += '</tr></thead><tbody>';
              members.forEach(function(m) {
                html += '<tr style="border-bottom:1px solid var(--border-gray);">';
                html += '<td style="padding:0.4rem 0.6rem;">' + (m.member_email || '—') + '</td>';
                html += '<td style="padding:0.4rem 0.6rem;">' + (m.added_at || '—') + '</td>';
                html += '<td style="padding:0.4rem 0.6rem;">' + (m.added_by || '—') + '</td>';
                html += '<td style="padding:0.4rem 0.6rem;">' + (m.reason || '—') + '</td>';
                html += '</tr>';
              });
              html += '</tbody></table>';
              td.innerHTML = '<strong style="font-size:0.8rem;color:var(--secondary-text);">' + members.length + ' member(s) at time of grant</strong>' + html;
            }

            detailRow.appendChild(td);
            row.parentNode.insertBefore(detailRow, row.nextSibling);
            toggle.innerHTML = '&#9660;';
          })
          .catch(function() {
            toggle.innerHTML = '&#9654;';
          });
      });
    });

    // Toggle between Group Name and Internal Name columns
    var btnGroup = document.getElementById('toggle-group-name');
    var btnInternal = document.getElementById('toggle-internal-name');
    if (btnGroup && btnInternal) {
      function showCol(col) {
        var show = col === 'group-name';
        document.querySelectorAll('[data-col="group-name"]').forEach(function(el) { el.style.display = show ? '' : 'none'; });
        document.querySelectorAll('[data-col="internal-name"]').forEach(function(el) { el.style.display = show ? 'none' : ''; });
        btnGroup.style.background = show ? 'var(--primary-teal)' : '#fff';
        btnGroup.style.color = show ? '#fff' : '#333';
        btnInternal.style.background = show ? '#fff' : 'var(--primary-teal)';
        btnInternal.style.color = show ? '#333' : '#fff';
      }
      btnGroup.addEventListener('click', function() { showCol('group-name'); });
      btnInternal.addEventListener('click', function() { showCol('internal-name'); });
    }

    // Column filter dropdowns — text click opens filter, sort arrow still sorts
    document.querySelectorAll('.col-filter-text').forEach(function(text) {
      text.addEventListener('click', function(e) {
        e.stopPropagation();
        var dropdown = document.getElementById(this.dataset.filterTarget);
        var wasOpen = dropdown.classList.contains('open');
        document.querySelectorAll('.col-filter-dropdown.open').forEach(function(d) { d.classList.remove('open'); });
        if (!wasOpen) { dropdown.classList.add('open'); }
      });
    });
    document.querySelectorAll('.col-filter-dropdown').forEach(function(dd) {
      dd.addEventListener('click', function(e) { e.stopPropagation(); });
    });
    document.addEventListener('click', function() {
      document.querySelectorAll('.col-filter-dropdown.open').forEach(function(d) { d.classList.remove('open'); });
    });

    // Grant level, role, and revoked filters
    function applyFilters() {
      var checkedLevels = {};
      document.querySelectorAll('.grant-level-filter').forEach(function(cb) {
        checkedLevels[cb.value] = cb.checked;
      });
      var checkedRoles = {};
      document.querySelectorAll('.role-filter').forEach(function(cb) {
        checkedRoles[cb.value] = cb.checked;
      });
      var hideRevoked = document.getElementById('hide-revoked').checked;
      document.querySelectorAll('tbody tr[data-grant-level]').forEach(function(row) {
        var level = row.dataset.grantLevel;
        var role = row.dataset.role;
        var revoked = row.dataset.revoked === 'true';
        var show = checkedLevels[level] !== false
          && (role === '' || checkedRoles[role] !== false)
          && !(hideRevoked && revoked);
        row.style.display = show ? '' : 'none';
      });
    }
    document.querySelectorAll('.grant-level-filter, .role-filter').forEach(function(cb) {
      cb.addEventListener('change', applyFilters);
    });
    document.getElementById('hide-revoked').addEventListener('change', applyFilters);
    </script>
  {% endif %}
"""


def _render(content_template, **kwargs):
    kwargs.setdefault("env", ENV)
    full_template = BASE_TEMPLATE.replace("{% block content %}{% endblock %}", content_template)
    return render_template_string(full_template, **kwargs)


def _run_query(query_template, params, org_suffix=None):
    if org_suffix is None:
        org_suffix = ORG_SUFFIX
    sql = query_template.replace('{user_activity_log_ctes}', USER_ACTIVITY_LOG_CTES)
    sql = sql.replace('{wb_groups_cte}', WB_GROUPS_CTE)
    sql = sql.format(env=ENV, bq_project=BQ_PROJECT, org_suffix=org_suffix)
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    result = bq_client.query(sql, job_config=job_config).result()
    return [dict(row) for row in result]


@app.route("/dc-access")
def dc_access():
    dc_id = request.args.get("dc_id", "").strip()
    org_override = request.args.get("org_override", "").strip()
    org_suffix = f"_{org_override}" if org_override else None

    if not dc_id:
        return _render(DC_ACCESS_CONTENT, active_tab="dc", dc_id=None, rows=None, error=None,
                       org_override=org_override, default_org=ORG)

    try:
        dc_params = [bigquery.ScalarQueryParameter("dc_user_facing_id", "STRING", dc_id)]
        exists = _run_query(DC_EXISTS_QUERY, dc_params, org_suffix=org_suffix)
        if exists[0]["cnt"] == 0:
            return _render(DC_ACCESS_CONTENT, active_tab="dc", dc_id=dc_id, rows=None,
                           error=f'Data collection "{dc_id}" was not found.',
                           org_override=org_override, default_org=ORG)
        rows = _run_query(DC_ACCESS_QUERY, dc_params, org_suffix=org_suffix)
    except Exception as e:
        return _render(DC_ACCESS_CONTENT, active_tab="dc", dc_id=dc_id, rows=None, error=str(e),
                       org_override=org_override, default_org=ORG)

    return _render(DC_ACCESS_CONTENT, active_tab="dc", dc_id=dc_id, rows=rows, error=None,
                   org_override=org_override, default_org=ORG)


@app.route("/group")
def group_membership():
    group_name = request.args.get("group_name", "").strip()
    org_override = request.args.get("org_override", "").strip()
    org_suffix = f"_{org_override}" if org_override else None

    if not group_name:
        return _render(GROUP_MEMBERSHIP_CONTENT, active_tab="group", group_name=None, rows=None, error=None,
                       org_override=org_override, default_org=ORG)

    try:
        rows = _run_query(GROUP_MEMBERSHIP_QUERY, [
            bigquery.ScalarQueryParameter("group_name", "STRING", group_name),
        ], org_suffix=org_suffix)
    except Exception as e:
        return _render(GROUP_MEMBERSHIP_CONTENT, active_tab="group", group_name=group_name, rows=None, error=str(e),
                       org_override=org_override, default_org=ORG)

    return _render(GROUP_MEMBERSHIP_CONTENT, active_tab="group", group_name=group_name, rows=rows, error=None,
                   org_override=org_override, default_org=ORG)



@app.route("/forensic-v2")
def forensic_v2_view():
    workspace_name = request.args.get("workspace_name", "").strip()
    org_override = request.args.get("org_override", "").strip()
    org_suffix = f"_{org_override}" if org_override else None

    if not workspace_name:
        return _render(FORENSIC_V2_CONTENT, active_tab="forensic_v2",
                       workspace_name=None, rows=None, error=None,
                       org_override=org_override, default_org=ORG)

    try:
        rows = _run_query(FORENSIC_V2_QUERY, [
            bigquery.ScalarQueryParameter("workspace_name", "STRING", workspace_name),
        ], org_suffix=org_suffix)
    except Exception as e:
        return _render(FORENSIC_V2_CONTENT, active_tab="forensic_v2",
                       workspace_name=workspace_name, rows=None, error=str(e),
                       org_override=org_override, default_org=ORG)

    return _render(FORENSIC_V2_CONTENT, active_tab="forensic_v2",
                   workspace_name=workspace_name, rows=rows, error=None,
                   org_override=org_override, default_org=ORG)


@app.route("/group-audit")
def group_audit():
    group_name = request.args.get("group_name", "").strip()
    org_override = request.args.get("org_override", "").strip()
    org_suffix = f"_{org_override}" if org_override else None

    if not group_name:
        return _render(GROUP_AUDIT_CONTENT, active_tab="group_audit", group_name=None, rows=None, error=None,
                       org_override=org_override, default_org=ORG)

    try:
        rows = _run_query(GROUP_AUDIT_QUERY, [
            bigquery.ScalarQueryParameter("group_name", "STRING", group_name),
        ], org_suffix=org_suffix)
    except Exception as e:
        return _render(GROUP_AUDIT_CONTENT, active_tab="group_audit", group_name=group_name, rows=None, error=str(e),
                       org_override=org_override, default_org=ORG)

    return _render(GROUP_AUDIT_CONTENT, active_tab="group_audit", group_name=group_name, rows=rows, error=None,
                   org_override=org_override, default_org=ORG)


@app.route("/")
def workspace_forensic_view():
    workspace_name = request.args.get("workspace_name", "").strip()
    org_override = request.args.get("org_override", "").strip()
    org_suffix = f"_{org_override}" if org_override else None

    if not workspace_name:
        return _render(WORKSPACE_FORENSIC_CONTENT, active_tab="ws_forensic",
                       workspace_name=None, rows=None, error=None,
                       org_override=org_override, default_org=ORG)

    try:
        rows = _run_query(WORKSPACE_FORENSIC_QUERY, [
            bigquery.ScalarQueryParameter("workspace_name", "STRING", workspace_name),
        ], org_suffix=org_suffix)
    except Exception as e:
        return _render(WORKSPACE_FORENSIC_CONTENT, active_tab="ws_forensic",
                       workspace_name=workspace_name, rows=None, error=str(e),
                       org_override=org_override, default_org=ORG)

    return _render(WORKSPACE_FORENSIC_CONTENT, active_tab="ws_forensic",
                   workspace_name=workspace_name, rows=rows, error=None,
                   org_override=org_override, default_org=ORG)


@app.route("/api/group-members-at")
def group_members_at():
    group_name = request.args.get("group_name", "").strip()
    timestamp = request.args.get("timestamp", "").strip()
    if not group_name or not timestamp:
        return jsonify({"error": "group_name and timestamp are required"}), 400

    try:
        rows = _run_query(GROUP_MEMBERS_AT_QUERY, [
            bigquery.ScalarQueryParameter("group_name", "STRING", group_name),
            bigquery.ScalarQueryParameter("as_of_timestamp", "TIMESTAMP", timestamp),
        ])
        for row in rows:
            for k, v in row.items():
                if hasattr(v, 'isoformat'):
                    row[k] = v.isoformat()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
