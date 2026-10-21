from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class ColumnSetting(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=512)
    logical_type: Literal["number", "text"] | None = None
    label: str | None = Field(default=None, max_length=128)
    filter_kind: Literal["categorical", "range", "none"] | None = None


class TableSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["aurora", "s3", "bq", "catalog"]
    resource_id: str = Field(min_length=1, max_length=256)
    table: str = Field(min_length=1, max_length=2048)
    schema_name: str | None = Field(default=None, alias="schema", max_length=128)
    uuid: str | None = None
    settings: list[ColumnSetting] = Field(default_factory=list, max_length=200)


class SourceCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    left: str = Field(min_length=1)
    op: Literal["=", "!=", "<", "<=", ">", ">="] = "="
    right: str = Field(min_length=1)


class SourceStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: SourceRef
    how: Literal["inner", "left", "right", "full", "semi", "anti"] = "left"
    conditions: list[SourceCondition] = Field(min_length=1, max_length=12)
    columns: list[str] | None = None
    alias: str = Field(min_length=1, max_length=256)


class JoinSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["join"]
    base: SourceRef
    steps: list[SourceStep] = Field(min_length=1, max_length=6)
    settings: list[ColumnSetting] = Field(default_factory=list, max_length=200)


SourceRef = Annotated[Union[TableSource, JoinSource], Field(discriminator="kind")]
SourceStep.model_rebuild()
JoinSource.model_rebuild()
SOURCE_ADAPTER = TypeAdapter(SourceRef)


def source_dict(source) -> dict:
    model = SOURCE_ADAPTER.validate_python(source)
    count = 0

    def check(node, depth):
        nonlocal count
        count += 1
        if count > 16 or depth > 4:
            raise ValueError("Saved joins support at most 16 sources and four levels.")
        if isinstance(node, JoinSource):
            check(node.base, depth + 1)
            for step in node.steps:
                check(step.source, depth + 1)

    check(model, 0)
    result = model.model_dump(by_alias=True, exclude_none=True)

    def compact(node):
        if not node.get("settings"):
            node.pop("settings", None)
        if node["kind"] == "join":
            compact(node["base"])
            for step in node["steps"]:
                compact(step["source"])

    compact(result)
    return result
