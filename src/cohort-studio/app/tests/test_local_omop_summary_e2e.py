import os

import httpx
import pytest
from sqlalchemy import create_engine, text


pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def local_omop_url():
    value = os.environ.get("STUDIO_LOCAL_URL", "").rstrip("/")
    if not value:
        pytest.skip("Set STUDIO_LOCAL_URL to the running compose.local.yaml app.")
    return value


def _gi_bleed_reference_counts():
    port = os.environ.get("STUDIO_LOCAL_PG_PORT", "55432")
    url = os.environ.get(
        "STUDIO_LOCAL_DB_URL",
        f"postgresql+psycopg://cohort_local:cohort_local@127.0.0.1:{port}/cohort_local",
    )
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(text("""
                SELECT count(DISTINCT p.person_id),
                       count(DISTINCT p.person_id) FILTER (
                           WHERE p.gender_concept_id = 8532)
                FROM cdm.condition_occurrence AS c
                JOIN cdm.person AS p USING (person_id)
                JOIN cdm.observation_period AS o USING (person_id)
                WHERE c.condition_concept_id = 192671
                  AND c.condition_start_date BETWEEN o.observation_period_start_date
                                                 AND o.observation_period_end_date
            """)).one()
    finally:
        engine.dispose()


def test_local_omop_summary_follows_cohort_filters(local_omop_url: str):
    assert _gi_bleed_reference_counts() == (40, 20)
    api = f"{local_omop_url}/api/omop/local-postgres"
    criteria = [{"domain": "condition", "concept_ids": [192671]}]

    def summary(**demographics):
        spec = {"criteria": criteria}
        if demographics:
            spec["demographics"] = demographics
        response = client.post(f"{api}/cohort/summary", json={"spec": spec})
        assert response.status_code == 200, response.text
        return response.json()

    with httpx.Client(timeout=60) as client:
        found = client.get(f"{api}/concepts", params={"q": "192671"}).json()
        assert any(c["concept_id"] == 192671 for c in found["concepts"])

        everyone = summary()
        assert everyone["scope"] == "database"
        assert (everyone["persons"], everyone["total_persons"]) == (40, 100)
        assert {"gender", "age_at_index"} <= set(everyone["charts"])

        female = summary(gender_concept_ids=[8532])
        assert female["persons"] == 20 == _gi_bleed_reference_counts()[1]
        assert sum(item["persons"] for item in female["charts"]["gender"]) == 20

        zero = summary(gender_concept_ids=[8532], age_min=200)
        assert zero["persons"] == 0
        assert all(item["persons"] == 0 for item in zero["charts"]["gender"])

        people = client.post(f"{api}/cohort/open", json={"spec": {
            "criteria": criteria, "demographics": {"gender_concept_ids": [8532]}},
            "name": "GI bleed women"})
        assert people.status_code == 200, people.text
        assert people.json()["rows"] == 20

        person = client.post(f"{api}/domain/open", json={
            "table": "person", "spec": None, "concept_names": False})
        assert person.status_code == 200, person.text
        assert person.json()["rows"] == 100
