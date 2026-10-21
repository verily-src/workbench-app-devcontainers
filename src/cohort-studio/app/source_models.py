from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class DerivedSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    op: Literal["bin", "formula", "map"]
    name: str = Field(pattern=r"^[A-Za-z0-9 _.\-]{1,60}$")
    column: str | None = None
    breaks: list[float] | None = Field(default=None, max_length=1001)
    labels: list[str] | None = Field(default=None, max_length=1000)
    left: str | None = None
    operator: Literal["+", "-", "*", "/"] | None = None
    right: str | None = None
    mapping: dict[str, str] | None = Field(default=None, max_length=1000)
    default: str | None = None

    @model_validator(mode="after")
    def validate_operation(self):
        if not self.name.strip():
            raise ValueError("Column name is required.")
        if self.op == "bin":
            if not self.column or not self.breaks or len(self.breaks) < 2:
                raise ValueError("Binning needs a column and at least two break points.")
            if any(a >= b for a, b in zip(self.breaks, self.breaks[1:])):
                raise ValueError("Break points must be strictly ascending.")
            if self.labels is not None and len(self.labels) != len(self.breaks) - 1:
                raise ValueError("Provide one label per bin.")
        if self.op == "formula" and not (self.left and self.operator and self.right):
            raise ValueError("A formula needs left, operator and right.")
        if self.op == "map" and not (self.column and self.mapping):
            raise ValueError("Mapping needs a column and at least one value mapping.")
        return self


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


class DerivedSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["derived"]
    base: SourceRef
    spec: DerivedSpec
    settings: list[ColumnSetting] = Field(default_factory=list, max_length=200)


SourceRef = Annotated[Union[TableSource, JoinSource, DerivedSource], Field(discriminator="kind")]
SourceStep.model_rebuild()
JoinSource.model_rebuild()
DerivedSource.model_rebuild()
SOURCE_ADAPTER = TypeAdapter(SourceRef)


def source_dict(source) -> dict:
    model = SOURCE_ADAPTER.validate_python(source)
    count = 0

    def check(node, depth):
        nonlocal count
        count += 1
        if count > 16 or depth > 4:
            raise ValueError("Saved sources support at most 16 sources and four levels.")
        if isinstance(node, DerivedSource):
            check(node.base, depth + 1)
        if isinstance(node, JoinSource):
            check(node.base, depth + 1)
            for step in node.steps:
                check(step.source, depth + 1)

    check(model, 0)
    result = model.model_dump(by_alias=True, exclude_none=True)

    def compact(node):
        if not node.get("settings"):
            node.pop("settings", None)
        if node["kind"] == "derived":
            compact(node["base"])
        if node["kind"] == "join":
            compact(node["base"])
            for step in node["steps"]:
                compact(step["source"])

    compact(result)
    return result
