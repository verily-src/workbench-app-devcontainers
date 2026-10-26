import pytest
from pydantic import ValidationError

from main import FilterAskEntry, SaveViewRequest, ViewDataset


def test_saved_filter_ask_history_is_bounded_and_requires_one_outcome():
    source = {"kind": "aurora", "resource_id": "clinical", "table": "person"}
    entry = {"question": "Filter to liver", "answer": "Applied liver filter"}
    saved = ViewDataset.model_validate({
        "source": source, "filter_ask_history": [entry] * 25,
    })
    assert len(saved.filter_ask_history) == 25
    assert saved.model_dump(exclude_none=True)["filter_ask_history"][0] == entry
    request = SaveViewRequest.model_validate({
        "kind": "aurora", "resource_id": "clinical", "name": "saved",
        "datasets": [{"source": source, "filter_ask_history": [entry]}],
    })
    assert request.datasets[0].filter_ask_history[0].answer == entry["answer"]
    with pytest.raises(ValidationError):
        SaveViewRequest.model_validate({
            "kind": "aurora", "resource_id": "clinical", "name": "saved",
            "datasets": [{"source": source, "filter_ask_history": [entry] * 26}],
        })
    with pytest.raises(ValidationError):
        FilterAskEntry.model_validate({"question": "No outcome"})
    with pytest.raises(ValidationError):
        FilterAskEntry.model_validate({
            "question": "Both outcomes", "answer": "ok", "error": "failed",
        })
