from typing import Literal
from pydantic import BaseModel, ConfigDict


class CountContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_measure: Literal["rows"] = "rows"
    entity_measure: Literal["distinct_non_null"] | None = None
    entity_column: str | None = None
    chart_measure: Literal["chart_spec"] = "chart_spec"
    grain: Literal["unspecified"] = "unspecified"
    key_status: Literal["not_checked", "empty", "unique_non_null", "duplicates_or_nulls"] = "not_checked"
    evidence_scope: Literal["database", "loaded", "sample"] | None = None


def describe(entity_column=None, result=None):
    contract = CountContract(entity_measure="distinct_non_null" if entity_column is not None else None,
                             entity_column=entity_column)
    if result and entity_column is not None and result.get("entity"):
        contract.evidence_scope = ("database" if result.get("scope") == "database" else
                                   "sample" if result.get("sampled") else "loaded")
        total = result["total"]
        contract.key_status = ("empty" if total == 0 else
                               "unique_non_null" if result["entity"]["total"] == total else
                               "duplicates_or_nulls")
    return contract.model_dump()
