#!/opt/venv/bin/python
"""Sends one Google API request from inside the sandbox, for `opencode-sandbox selftest`.

usage: data-probe.py METHOD URL [JSON-BODY]   prints "denied" when OpenShell blocks it,
                                              else "HTTP <status>"
       data-probe.py --query SQL [PROJECT]    runs SQL with the BigQuery client, prints the row count
"""
import json
import sys

import google.auth
from google.auth.transport.requests import AuthorizedSession

credentials, default_project = google.auth.default()

if sys.argv[1] == "--query":
    from google.cloud import bigquery

    client = bigquery.Client(project=sys.argv[3] if len(sys.argv) > 3 else default_project,
                             credentials=credentials)
    print(f"rows={len(list(client.query(sys.argv[2]).result()))}")
else:
    body = sys.argv[3] if len(sys.argv) > 3 else None
    response = AuthorizedSession(credentials).request(
        sys.argv[1], sys.argv[2], data=body, headers={"Content-Type": "application/json"} if body else None)
    print("denied" if "policy_denied" in response.text else f"HTTP {response.status_code}")
