from __future__ import annotations

from datetime import date

from typing import Annotated, Literal, Union

from pydantic import (BaseModel, ConfigDict, Field, TypeAdapter, field_validator,
                      model_validator)

from count_contract import Definition
import sql_source
import internal_data
import omop


class DerivedSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    op: Literal["bin", "formula", "expression", "map", "group_count", "group_sum", "group_mean", "group_min", "group_max"]
    name: str = Field(pattern=r"^[A-Za-z0-9 _.\-]{1,60}$")
    column: str | None = None
    measure: str | None = None
    group_by: list[str] | None = Field(default=None, min_length=1, max_length=5)
    expression: str | None = Field(default=None, min_length=1, max_length=1000)
    breaks: list[float] | None = Field(default=None, max_length=1001)
    labels: list[str] | None = Field(default=None, max_length=1000)
    left: str | None = None
    operator: Literal["+", "-", "*", "/"] | None = None
    right: str | None = None
    mapping: dict[str, str] | None = Field(default=None, max_length=1000)
    default: str | None = None
    # Values of the tab parameters an expression references as @name, resolved
    # when the field is created and kept so the recipe re-derives identically.
    parameters: list[Parameter] | None = Field(default=None, max_length=20)

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
        if self.op == "expression" and not (self.expression and self.expression.strip()):
            raise ValueError("A calculation expression is required.")
        if self.op == "expression":
            import calculations
            calculations.check_syntax(self.expression, self.parameters or [])
        if self.op == "map" and not (self.column and self.mapping):
            raise ValueError("Mapping needs a column and at least one value mapping.")
        if self.group_by and (any(not item.strip() for item in self.group_by) or len(set(self.group_by)) != len(self.group_by)):
            raise ValueError("Grouping columns must be distinct and nonempty.")
        if self.op in {"group_count", "group_sum", "group_mean", "group_min", "group_max"} and not (self.column or self.group_by):
            raise ValueError("Aggregation needs a grouping column.")
        if self.op in {"group_sum", "group_mean", "group_min", "group_max"} and not self.measure:
            raise ValueError("This aggregation needs a measure column.")
        return self


class ColumnSetting(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=512)
    logical_type: Literal["number", "text"] | None = None
    label: str | None = Field(default=None, max_length=128)
    filter_kind: Literal["categorical", "range", "date", "none"] | None = None


class TableSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["aurora", "postgres", "athena", "s3", "bq", "catalog"]
    resource_id: str = Field(min_length=1, max_length=256)
    table: str = Field(min_length=1, max_length=2048)
    schema_name: str | None = Field(default=None, alias="schema", min_length=1, max_length=128)
    uuid: str | None = None
    grain: Definition | None = None
    settings: list[ColumnSetting] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def public_source(self):
        if self.kind in {"aurora", "postgres"}:
            internal_data.require_public_source(self.schema_name, self.table)
        return self


class SQLSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["sql"]
    resource_id: str = Field(min_length=1, max_length=256)
    sql: str = Field(min_length=1, max_length=20_000)
    name: str | None = Field(default=None, max_length=128)
    grain: Definition | None = None
    settings: list[ColumnSetting] = Field(default_factory=list, max_length=200)

    @field_validator("sql")
    @classmethod
    def validate_sql(cls, value: str) -> str:
        return sql_source.normalize(value)

    @model_validator(mode="after")
    def validate_source(self):
        if not self.sql.strip():
            raise ValueError("SQL query is required.")
        if self.name is not None and not self.name.strip():
            raise ValueError("SQL source name cannot be blank.")
        return self


class MaterializedSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["materialized"]
    resource_id: str = Field(min_length=1, max_length=256)
    materialized_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    grain: Definition | None = None
    settings: list[ColumnSetting] = Field(default_factory=list, max_length=200)


class OmopCohortSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["omop_cohort"]
    resource_id: str = Field(min_length=1, max_length=256)
    spec: dict
    membership_mode: Literal["live"] = "live"
    # CDM schema of a database with several; omitted means the default schema.
    cdm_schema: str | None = Field(default=None, min_length=1, max_length=63)
    table_mapping: dict[str, str] | None = Field(default=None, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    grain: Definition | None = None
    settings: list[ColumnSetting] = Field(default_factory=list, max_length=200)

    @field_validator("spec")
    @classmethod
    def validate_spec(cls, value: dict) -> dict:
        spec = omop.parse_spec(value)
        for criterion in spec["criteria"]:
            for key in ("start", "end"):
                if criterion[key] is not None:
                    criterion[key] = criterion[key].isoformat()
        return spec

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Cohort source name cannot be blank.")
        return value


class SourceCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    left: str = Field(min_length=1)
    op: Literal["=", "!=", "<", "<=", ">", ">="] = "="
    right: str = Field(min_length=1)


FilterScalar = Union[bool, int, float, str]
JOIN_FILTER_OPS = ("=", "!=", "<", "<=", ">", ">=", "in", "not in",
                   "is null", "is not null", "contains")


class SourceFilter(BaseModel):
    """A constant-value filter on one join input, applied before joining."""
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    column: str = Field(min_length=1)
    op: Literal["=", "!=", "<", "<=", ">", ">=", "in", "not in",
                "is null", "is not null", "contains"] = "="
    value: FilterScalar | list[FilterScalar] | None = None

    @field_validator("value")
    @classmethod
    def bounded_value(cls, value):
        if isinstance(value, list) and len(value) > 100:
            raise ValueError("A filter can list at most 100 values.")
        if isinstance(value, str) and len(value) > 1000:
            raise ValueError("Filter values are limited to 1,000 characters.")
        return value


class SourceStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: SourceRef
    how: Literal["inner", "left", "right", "full", "semi", "anti"] = "left"
    conditions: list[SourceCondition] = Field(min_length=1, max_length=12)
    columns: list[str] | None = None
    alias: str = Field(min_length=1, max_length=256)
    filters: list[SourceFilter] | None = Field(default=None, max_length=12)


class JoinOutput(BaseModel):
    """Fields of the joined result: drop some, rename others (after joining)."""
    model_config = ConfigDict(extra="forbid", strict=True)
    exclude: list[str] = Field(default_factory=list, max_length=500)
    rename: dict[str, str] = Field(default_factory=dict, max_length=500)

    @model_validator(mode="after")
    def _names(self):
        for old, new in self.rename.items():
            if not old or not isinstance(new, str) or not new.strip() or len(new) > 128:
                raise ValueError("Field names must be 1–128 characters.")
        return self


class JoinSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["join"]
    allow_loaded: bool = False
    output: JoinOutput | None = None
    base: SourceRef
    base_filters: list[SourceFilter] | None = Field(default=None, max_length=12)
    steps: list[SourceStep] = Field(max_length=6)
    grain: Definition | None = None
    settings: list[ColumnSetting] = Field(default_factory=list, max_length=200)


class DerivedSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["derived"]
    base: SourceRef
    spec: DerivedSpec
    grain: Definition | None = None
    settings: list[ColumnSetting] = Field(default_factory=list, max_length=200)


def _iso_date(value: str | None) -> str | None:
    """A YYYY-MM-DD string (kept as text so filters stay JSON for caches and views)."""
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"{value!r} is not a valid YYYY-MM-DD date.") from exc


PARAM_NAME = r"^[A-Za-z_][A-Za-z0-9_]{0,39}$"


class Parameter(BaseModel):
    """A named value a tab's filters can follow (e.g. index_date, min_age)."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(pattern=PARAM_NAME)
    kind: Literal["number", "date"]
    value: float | str

    @model_validator(mode="after")
    def _value_matches_kind(self):
        if self.kind == "number":
            if isinstance(self.value, str):
                raise ValueError(f"Parameter {self.name!r} is a number.")
        else:
            if not isinstance(self.value, str):
                raise ValueError(f"Parameter {self.name!r} is a YYYY-MM-DD date.")
            self.value = _iso_date(self.value) or ""
            if not self.value:
                raise ValueError(f"Parameter {self.name!r} needs a date.")
        return self


class ParamBinding(BaseModel):
    """Which filter bounds follow a parameter. The filter keeps the resolved
    value too, so engines never see bindings."""
    model_config = ConfigDict(extra="forbid")
    min: str | None = Field(default=None, pattern=PARAM_NAME)
    max: str | None = Field(default=None, pattern=PARAM_NAME)
    start: str | None = Field(default=None, pattern=PARAM_NAME)
    end: str | None = Field(default=None, pattern=PARAM_NAME)


class Filter(BaseModel):
    """One Explore filter. Pydantic checks each kind's shape before any engine runs."""
    model_config = ConfigDict(allow_inf_nan=False)
    column: str = Field(default="", max_length=512)
    kind: Literal["categorical", "range", "date", "any"]
    values: list[str] | None = Field(default=None, max_length=5000)
    min: int | float | None = None
    max: int | float | None = None
    # kind "date": absolute YYYY-MM-DD bounds (end inclusive) or "last N units".
    start: str | None = Field(default=None, max_length=32)
    end: str | None = Field(default=None, max_length=32)
    last: int | None = Field(default=None, ge=1, le=10_000)
    unit: Literal["day", "week", "month", "year"] | None = None
    # kind "any": rows matching every filter of at least one group (OR of ANDs).
    groups: list[Annotated[list["Filter"], Field(max_length=50)]] | None = Field(default=None, max_length=20)
    param: ParamBinding | None = None

    @field_validator("start", "end")
    @classmethod
    def _iso(cls, value: str | None) -> str | None:
        return _iso_date(value)

    @model_validator(mode="after")
    def _shape(self):
        if self.kind == "any":
            if not self.groups or any(not group for group in self.groups):
                raise ValueError("A criteria group filter needs at least one non-empty group.")
            if any(f.kind == "any" for group in self.groups for f in group):
                raise ValueError("Criteria groups can't be nested.")
            return self
        if not self.column:
            raise ValueError("Filter column is required.")
        if self.groups is not None:
            raise ValueError("Only criteria group filters have groups.")
        if self.param is not None:
            wrong = (self.kind == "range" and (self.param.start or self.param.end)) or \
                    (self.kind == "date" and (self.param.min or self.param.max)) or self.kind == "categorical"
            if wrong:
                raise ValueError(f"Filter on {self.column!r} binds a parameter to a bound it doesn't have.")
        if self.kind == "range" and self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"Range filter on {self.column!r}: minimum is above maximum.")
        if self.kind == "date":
            if (self.last is None) != (self.unit is None):
                raise ValueError("A relative date filter needs both 'last' and 'unit'.")
            if self.last is not None and (self.start or self.end):
                raise ValueError("Use either a relative date (last/unit) or start/end, not both.")
            if self.start and self.end and self.end < self.start:
                raise ValueError(f"Date filter on {self.column!r}: end is before its start.")
        return self

# Group summaries filter the same way as Explore: one model for both.
SummaryFilter = Filter


class SummarySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    group_by: list[str] = Field(min_length=1, max_length=5)
    measure: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def distinct_groups(self):
        if any(not item or len(item) > 512 for item in self.group_by) or len(set(self.group_by)) != len(self.group_by):
            raise ValueError("Choose distinct grouping columns.")
        return self


class GroupSummarySource(BaseModel):
    """Every group of a summary over ``base`` (after ``filters``), opened as its own table."""
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["group_summary"]
    base: SourceRef
    filters: list[SummaryFilter] = Field(default_factory=list, max_length=200)
    spec: SummarySpec
    grain: Definition | None = None
    settings: list[ColumnSetting] = Field(default_factory=list, max_length=200)


SourceRef = Annotated[Union[TableSource, SQLSource, MaterializedSource,
                            OmopCohortSource, JoinSource, DerivedSource,
                            GroupSummarySource],
                      Field(discriminator="kind")]
SourceStep.model_rebuild()
JoinSource.model_rebuild()
DerivedSource.model_rebuild()
GroupSummarySource.model_rebuild()
SQLSource.model_rebuild()
OmopCohortSource.model_rebuild()
SOURCE_ADAPTER = TypeAdapter(SourceRef)


def source_dict(source) -> dict:
    model = SOURCE_ADAPTER.validate_python(source)
    count = 0

    def check(node, depth):
        nonlocal count
        count += 1
        if count > 16 or depth > 4:
            raise ValueError("Saved sources support at most 16 source steps and four join levels.")
        if isinstance(node, (DerivedSource, GroupSummarySource)):
            check(node.base, depth)
        if isinstance(node, JoinSource):
            check(node.base, depth + 1)
            for step in node.steps:
                check(step.source, depth + 1)

    check(model, 0)
    result = model.model_dump(by_alias=True, exclude_none=True)

    def compact(node):
        if not node.get("settings"):
            node.pop("settings", None)
        if node["kind"] in {"derived", "group_summary"}:
            compact(node["base"])
        if node["kind"] == "join":
            if not node.get("allow_loaded"):
                node.pop("allow_loaded", None)
            if not node.get("base_filters"):
                node.pop("base_filters", None)
            compact(node["base"])
            for step in node["steps"]:
                if not step.get("filters"):
                    step.pop("filters", None)
                compact(step["source"])

    compact(result)
    return result
