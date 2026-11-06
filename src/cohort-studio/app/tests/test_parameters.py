"""Parameters: named values that filters follow. Pydantic validates them, and
saved views may only bind filters to defined parameters of the right kind."""
import pytest
from pydantic import ValidationError

import main

SOURCE = {"kind": "aurora", "resource_id": "db", "table": "person"}
PARAMS = [{"name": "min_age", "kind": "number", "value": 50},
          {"name": "index_date", "kind": "date", "value": "2024-01-01T00:00:00"}]


def _view(filters, parameters=PARAMS, cohorts=()):
    return main.ViewDataset.model_validate({"source": SOURCE, "filters": filters,
                                            "parameters": parameters, "cohorts": list(cohorts)})


def test_bound_filters_and_parameters_round_trip():
    view = _view([
        {"column": "age", "kind": "range", "min": 50, "max": 120, "param": {"min": "min_age"}},
        {"kind": "any", "groups": [[{"column": "visit", "kind": "date", "start": "2024-01-01",
                                     "param": {"start": "index_date"}}]]},
    ])
    assert view.parameters[1].value == "2024-01-01"            # normalized date
    assert view.filters[0].param.min == "min_age"
    dumped = view.model_dump(exclude_none=True)
    assert dumped["filters"][0]["param"] == {"min": "min_age"}


@pytest.mark.parametrize("filters, parameters, message", [
    ([{"column": "age", "kind": "range", "min": 1, "max": 2, "param": {"min": "nope"}}], PARAMS,
     "'nope', which is not a number parameter"),
    ([{"column": "age", "kind": "range", "min": 1, "max": 2, "param": {"min": "index_date"}}], PARAMS,
     "not a number parameter"),
    ([{"column": "visit", "kind": "date", "start": "2024-01-01", "param": {"start": "min_age"}}], PARAMS,
     "not a date parameter"),
    ([{"column": "age", "kind": "range", "min": 1, "max": 2, "param": {"start": "index_date"}}], PARAMS,
     "doesn't have"),
    ([], PARAMS + [{"name": "min_age", "kind": "number", "value": 1}], "unique"),
    ([], [{"name": "1bad", "kind": "number", "value": 1}], "String should match pattern"),
    ([], [{"name": "d", "kind": "date", "value": 5}], "YYYY-MM-DD date"),
    ([], [{"name": "n", "kind": "number", "value": "ten"}], "is a number"),
    ([], [{"name": "d", "kind": "date", "value": "2024-02-31"}], "not a valid YYYY-MM-DD date"),
])
def test_bad_parameters_and_bindings_are_rejected(filters, parameters, message):
    with pytest.raises(ValidationError, match=message):
        _view(filters, parameters)


def test_cohort_filters_are_checked_too():
    with pytest.raises(ValidationError, match="not a number parameter"):
        _view([], cohorts=[{"name": "c", "filters": [
            {"column": "age", "kind": "range", "min": 1, "max": 2, "param": {"max": "gone"}}]}])


def test_query_accepts_bound_filters_and_uses_their_values(client):
    """Engines see the resolved value; the binding rides along unused."""
    import datasets
    import pandas as pd
    ds = datasets.open_dataset(pd.DataFrame({"age": [30, 55, 70]}), "ages")
    try:
        response = client.post(f"/api/datasets/{ds['dataset_id']}/query", json={"filters": [
            {"column": "age", "kind": "range", "min": 50, "max": 200, "param": {"min": "min_age"}}]})
        assert response.status_code == 200, response.text
        assert response.json()["filtered"] == 2
    finally:
        datasets.close_dataset(ds["dataset_id"])
