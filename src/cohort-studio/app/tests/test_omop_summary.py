import omop


RID = "omopdb"
GI_BLEED = 192671
REPEATED = 40481087


def _summary(client, spec):
    response = client.post(f"/api/omop/{RID}/cohort/summary", json={"spec": spec})
    assert response.status_code == 200, response.text
    return response.json()


def test_summary_uses_selected_members_for_all_charts(client):
    all_people = _summary(client, {"criteria": None})
    assert all_people["persons"] == 100
    assert all_people["charts"]["domains"] == []
    spec = {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED]}]}
    result = _summary(client, spec)
    assert result["scope"] == "database"
    assert result["persons"] == 40
    assert result["total_persons"] == 100
    assert sum(item["persons"] for item in result["charts"]["gender"]) == 40
    assert sum(item["persons"] for item in result["charts"]["age_at_index"]) == 40
    condition = next(item for item in result["charts"]["domains"]
                     if item["domain"] == "condition")
    assert next(item for item in condition["concepts"]
                if item["concept_id"] == GI_BLEED)["persons"] == 40
    assert result["attrition"][-1]["persons"] == 40

    zero = _summary(client, {"criteria": [{"domain": "condition",
                                            "concept_ids": [GI_BLEED],
                                            "start": "3000-01-01"}]})
    assert zero["persons"] == 0
    assert zero["charts"]["gender"] == []
    assert all(item["persons"] == 0 for item in zero["charts"]["age_at_index"])
    assert all(item["concepts"] == [] for item in zero["charts"]["domains"])


def test_summary_counts_distinct_people_for_repeated_events_and_validates_spec(
        client, engine):
    spec = {"criteria": [{"domain": "condition", "concept_ids": [REPEATED],
                          "min_count": 3}]}
    result = _summary(client, spec)
    expected = omop.count(engine, omop.detect(engine), spec)
    assert 0 < result["persons"] < 100
    assert result["persons"] == expected["persons"]
    assert sum(item["persons"] for item in result["charts"]["gender"]) == result["persons"]
    assert sum(item["persons"] for item in result["charts"]["age_at_index"]) == result["persons"]
    assert all(item["persons"] <= result["persons"]
               for domain in result["charts"]["domains"]
               for item in domain["concepts"])

    invalid = client.post(f"/api/omop/{RID}/cohort/summary", json={
        "spec": {"criteria": [{"domain": "condition", "concept_ids": [GI_BLEED],
                                "start": "3000-1-01"}]}})
    assert invalid.status_code == 400

