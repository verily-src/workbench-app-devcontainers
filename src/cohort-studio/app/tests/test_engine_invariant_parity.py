import pandas as pd
import datasets


def test_boolean_filter_and_chart_api(client):
    frame = pd.DataFrame({"flag": [True, False, None] * 20000,
                          "pid": [1, 2, 3] * 20000})
    opened = datasets.open_dataset(frame, "bool.csv")
    dataset_id = opened["dataset_id"]
    try:
        response = client.post(f"/api/datasets/{dataset_id}/query", json={
            "filters": [{"kind": "categorical", "column": "flag", "values": ["True"]}],
            "charts": [{"kind": "bar", "x": "flag"},
                       {"kind": "bar", "x": "flag", "measure": {"agg": "sum", "column": "pid"}},
                       {"kind": "heatmap", "x": "flag", "y": "pid"}], "entity_column": "pid"})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["filtered"] == 20000
        assert result["entity"]["filtered"] == 1
        assert {v["category"]: v["selected"] for v in result["charts"][0]["data"]} == {
            "True": 20000, "False": 0}
        assert {v["category"]: v["value"] for v in result["charts"][1]["data"]}["True"] == 20000
        assert result["charts"][2]["data"] == [["True", "1", 20000]]
    finally:
        datasets.close_dataset(dataset_id)
