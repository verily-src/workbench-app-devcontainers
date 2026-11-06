"""Calculated-field expressions: one validated grammar, three engines.

An expression is tokenized and parsed by hand into pydantic node models (the
models validate function names, units, arity and literal values), then typed
against the columns' kinds, then evaluated with pandas/numpy or compiled to
PostgreSQL or DuckDB SQL. User text never reaches SQL: columns are quoted
identifiers chosen by the caller, PostgreSQL constants are bound parameters and
DuckDB constants are validated literals.

Types are number, text, bool and date. A column takes the type its context
needs (a text column used in DATEDIFF is parsed as YYYY-MM-DD dates; one used in
arithmetic is parsed as numbers); invalid values become null. Boolean results
are stored as the text "true"/"false" so categorical filters agree on every
engine. Date arithmetic follows PostgreSQL ``age()``: whole months count only
once the end's day of month reaches the start's.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Annotated, Callable, Literal, Union

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

MAX_LENGTH = 1000
MAX_NODES = 250
MAX_DEPTH = 24      # nested parentheses, calls and CASEs
MAX_TREE_DEPTH = 80
MAX_SQL = 30000

UNITS = ("day", "week", "month", "year")
TYPE_LABEL = {"number": "a number", "text": "text", "bool": "a true/false condition", "date": "a date"}
# fn: (argument types, result type). "*" = the unified type of those arguments.
FUNCTIONS = {
    "abs": (("number",), "number"),
    "sqrt": (("number",), "number"),
    "ln": (("number",), "number"),
    "year": (("date",), "number"),
    "month": (("date",), "number"),
    "today": ((), "date"),
    "age_at": (("date", "date"), "number"),
    "datediff": (("date", "date"), "number"),
    "date_trunc": (("date",), "date"),
    "if": (("bool", "*", "*"), "*"),
    "coalesce": None,  # 2–10 arguments of one type
}
UNIT_FUNCTIONS = {"datediff", "date_trunc"}
HELP = ("abs, sqrt, ln, coalesce, if, year, month, today, age_at, datediff, date_trunc "
        "(and col(\"name\") for any column)")


def _clean(error: ValidationError) -> str:
    first = error.errors()[0]
    message = str(first.get("msg", "Invalid calculation expression."))
    return message.removeprefix("Value error, ")


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class NumberLit(_Node):
    kind: Literal["number"] = "number"
    value: float


class TextLit(_Node):
    kind: Literal["text"] = "text"
    value: str = Field(max_length=500)


class DateLit(_Node):
    kind: Literal["date"] = "date"
    value: date

    @field_validator("value", mode="before")
    @classmethod
    def _iso(cls, value):
        if isinstance(value, str):
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError(f"DATE '{value}' must be written YYYY-MM-DD.")
            try:
                value = date.fromisoformat(value)
            except ValueError:
                raise ValueError(f"DATE '{value}' is not a real date.") from None
        return value

    @field_validator("value")
    @classmethod
    def _range(cls, value):
        if not 1000 <= value.year <= 9999:
            raise ValueError("Dates must fall between the years 1000 and 9999.")
        return value


class BoolLit(_Node):
    kind: Literal["bool"] = "bool"
    value: bool


class NullLit(_Node):
    kind: Literal["null"] = "null"


class Keyword(_Node):
    """NULL / TRUE / FALSE as written; a column of that exact name wins (old recipes)."""
    kind: Literal["keyword"] = "keyword"
    text: str = Field(pattern=r"^(?i:null|true|false)$")


class Column(_Node):
    kind: Literal["column"] = "column"
    name: str = Field(min_length=1, max_length=512)


class Param(_Node):
    kind: Literal["param"] = "param"
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")


class Negate(_Node):
    kind: Literal["negate"] = "negate"
    operand: "Node"


class Arithmetic(_Node):
    kind: Literal["arithmetic"] = "arithmetic"
    op: Literal["+", "-", "*", "/"]
    left: "Node"
    right: "Node"


class Comparison(_Node):
    kind: Literal["comparison"] = "comparison"
    op: Literal["=", "!=", "<", "<=", ">", ">="]
    left: "Node"
    right: "Node"


class Logical(_Node):
    kind: Literal["logical"] = "logical"
    op: Literal["and", "or"]
    left: "Node"
    right: "Node"


class Not(_Node):
    kind: Literal["not"] = "not"
    operand: "Node"


class IsNull(_Node):
    kind: Literal["is_null"] = "is_null"
    operand: "Node"
    negated: bool = False


class When(_Node):
    condition: "Node"
    result: "Node"


class Case(_Node):
    kind: Literal["case"] = "case"
    whens: list[When] = Field(min_length=1, max_length=20)
    otherwise: "Node | None" = None


class Call(_Node):
    kind: Literal["call"] = "call"
    function: Literal["abs", "sqrt", "ln", "year", "month", "today", "age_at",
                      "datediff", "date_trunc", "if", "coalesce"]
    unit: Literal["day", "week", "month", "year"] | None = None
    args: list["Node"] = Field(default_factory=list, max_length=10)

    @field_validator("function", mode="before")
    @classmethod
    def _known(cls, value):
        if isinstance(value, str) and value.lower() in FUNCTIONS:
            return value.lower()
        raise ValueError(f"Unknown function {value}(). Use {HELP}.")

    @field_validator("unit", mode="before")
    @classmethod
    def _unit(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and value.lower() in UNITS:
            return value.lower()
        raise ValueError(f"Unknown unit {value!r}: use day, week, month or year.")

    @model_validator(mode="after")
    def _arity(self):
        name = self.function.upper()
        if self.function in UNIT_FUNCTIONS and self.unit is None:
            raise ValueError(f"{name} needs a unit first: day, week, month or year.")
        if self.function not in UNIT_FUNCTIONS and self.unit is not None:
            raise ValueError(f"{name} does not take a unit.")
        if self.function == "coalesce":
            if not 2 <= len(self.args) <= 10:
                raise ValueError("COALESCE takes 2 to 10 values.")
            return self
        expected = len(FUNCTIONS[self.function][0])
        if len(self.args) != expected:
            shown = {"datediff": "DATEDIFF(unit, start, end)", "date_trunc": "DATE_TRUNC(unit, date)",
                     "age_at": "AGE_AT(birth_date, index_date)", "if": "IF(condition, then, else)",
                     "today": "TODAY()"}.get(self.function, f"{name}(value)")
            raise ValueError(f"Write {shown}.")
        return self


Node = Annotated[Union[NumberLit, TextLit, DateLit, BoolLit, NullLit, Keyword, Column, Param, Negate,
                       Arithmetic, Comparison, Logical, Not, IsNull, Case, Call],
                 Field(discriminator="kind")]
for _model in (Negate, Arithmetic, Comparison, Logical, Not, IsNull, When, Case, Call):
    _model.model_rebuild()


class Expression(_Node):
    """The whole parsed expression, with its size limits."""
    source: str = Field(min_length=1, max_length=MAX_LENGTH)
    root: Node

    @model_validator(mode="after")
    def _bounded(self):
        stack, nodes, deepest = [(self.root, 0)], 0, 0
        while stack and nodes <= MAX_NODES:
            node, depth = stack.pop()
            nodes, deepest = nodes + 1, max(deepest, depth)
            stack.extend((child, depth + 1) for child in _children(node))
        if nodes > MAX_NODES:
            raise ValueError("Calculation expression is too complex.")
        if deepest > MAX_TREE_DEPTH:
            raise ValueError("Calculation expression is too long: split it into two calculated fields.")
        return self


def _children(node):
    if isinstance(node, (Negate, Not, IsNull)):
        return [node.operand]
    if isinstance(node, (Arithmetic, Comparison, Logical)):
        return [node.left, node.right]
    if isinstance(node, Case):
        out = [part for when in node.whens for part in (when.condition, when.result)]
        return out + ([node.otherwise] if node.otherwise is not None else [])
    if isinstance(node, Call):
        return list(node.args)
    return []


# ---------------------------------------------------------------- parsing

_TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<number>(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)
  | (?P<string>'(?:[^']|'')*'|"(?:[^"]|"")*")
  | (?P<param>@[A-Za-z_][A-Za-z0-9_]*)
  | (?P<name>[^\W\d]\w*)
  | (?P<op><=|>=|!=|<>|==|[-+*/(),=<>])
""", re.X)
_COMPARE = {"=": "=", "==": "=", "!=": "!=", "<>": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}


@dataclass
class _Tok:
    kind: str
    text: str
    pos: int

    @property
    def word(self):
        return self.text.lower() if self.kind == "name" else None


def _tokens(text: str) -> list[_Tok]:
    out, pos = [], 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match:
            raise ValueError(f"Unexpected character {text[pos]!r} at position {pos + 1}.")
        kind = match.lastgroup
        if kind != "space":
            out.append(_Tok(kind, match.group(), pos))
        pos = match.end()
    out.append(_Tok("end", "", len(text)))
    return out


def _make(model, **values):
    try:
        return model(**values)
    except ValidationError as e:
        raise ValueError(_clean(e)) from None


class _Parser:
    def __init__(self, text):
        self.toks = _tokens(text)
        self.i = 0
        self.depth = 0

    def peek(self, ahead=0):
        return self.toks[min(self.i + ahead, len(self.toks) - 1)]

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def at_word(self, *words):
        return self.peek().word in words

    def expect_word(self, word, context):
        if not self.at_word(word):
            raise ValueError(f"Expected {word.upper()} {context}{self._where()}.")
        self.take()

    def expect_op(self, op, context):
        if self.peek().text != op or self.peek().kind != "op":
            raise ValueError(f"Expected '{op}' {context}{self._where()}.")
        self.take()

    def _where(self):
        tok = self.peek()
        return " at the end" if tok.kind == "end" else f" near {tok.text!r} (position {tok.pos + 1})"

    def parse(self):
        node = self.expr()
        if self.peek().kind != "end":
            raise ValueError(f"Unexpected {self.peek().text!r} at position {self.peek().pos + 1}.")
        return node

    def expr(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ValueError("Calculation expression is too deeply nested.")
        try:
            return self.or_()
        finally:
            self.depth -= 1

    def or_(self):
        node = self.and_()
        while self.at_word("or"):
            self.take()
            node = _make(Logical, op="or", left=node, right=self.and_())
        return node

    def and_(self):
        node = self.not_()
        while self.at_word("and"):
            self.take()
            node = _make(Logical, op="and", left=node, right=self.not_())
        return node

    def not_(self):
        if self.at_word("not"):
            self.take()
            self.depth += 1
            if self.depth > MAX_DEPTH:
                raise ValueError("Calculation expression is too deeply nested.")
            try:
                return _make(Not, operand=self.not_())
            finally:
                self.depth -= 1
        return self.comparison()

    def comparison(self):
        node = self.additive()
        tok = self.peek()
        if tok.kind == "op" and tok.text in _COMPARE:
            self.take()
            node = _make(Comparison, op=_COMPARE[tok.text], left=node, right=self.additive())
        elif self.at_word("is"):
            self.take()
            negated = False
            if self.at_word("not"):
                self.take()
                negated = True
            self.expect_word("null", "after IS / IS NOT")
            node = _make(IsNull, operand=node, negated=negated)
        nxt = self.peek()
        if (nxt.kind == "op" and nxt.text in _COMPARE) or nxt.word == "is":
            raise ValueError("Combine comparisons with AND / OR, e.g. a > 1 AND a < 5.")
        return node

    def additive(self):
        node = self.term()
        while self.peek().kind == "op" and self.peek().text in "+-":
            op = self.take().text
            node = _make(Arithmetic, op=op, left=node, right=self.term())
        return node

    def term(self):
        node = self.unary()
        while self.peek().kind == "op" and self.peek().text in "*/":
            op = self.take().text
            if self.peek().kind == "op" and self.peek().text == "*":
                raise ValueError("Powers (**) are not supported.")
            node = _make(Arithmetic, op=op, left=node, right=self.unary())
        return node

    def unary(self):
        tok = self.peek()
        if tok.kind == "op" and tok.text in "+-":
            self.take()
            self.depth += 1
            if self.depth > MAX_DEPTH:
                raise ValueError("Calculation expression is too deeply nested.")
            try:
                operand = self.unary()
            finally:
                self.depth -= 1
            if tok.text == "+":   # keeps the numeric context: +text_column is a number
                return _make(Arithmetic, op="+", left=NumberLit(value=0.0), right=operand)
            return _make(Negate, operand=operand)
        return self.primary()

    def primary(self):
        tok = self.take()
        if tok.kind == "number":
            try:
                value = float(tok.text)
            except (OverflowError, ValueError):
                value = math.inf
            if not math.isfinite(value):
                raise ValueError("Constants must be finite numbers.")
            return _make(NumberLit, value=value)
        if tok.kind == "string":
            return _make(TextLit, value=_unquote(tok.text))
        if tok.kind == "param":
            return _make(Param, name=tok.text[1:])
        if tok.kind == "op" and tok.text == "(":
            node = self.expr()
            self.expect_op(")", "to close '('")
            return node
        if tok.kind == "name":
            word = tok.word
            nxt = self.peek()
            if nxt.kind == "op" and nxt.text == "(":
                self.take()
                return self.call(tok.text)
            if word == "case" and self.at_word("when"):
                return self.case()
            if word == "date" and nxt.kind == "string":
                self.take()
                return _make(DateLit, value=_unquote(nxt.text))
            if word in {"null", "true", "false"}:
                return _make(Keyword, text=tok.text)
            return _make(Column, name=tok.text)
        if tok.kind == "end":
            raise ValueError("The expression ends too early.")
        raise ValueError(f"Unexpected {tok.text!r} at position {tok.pos + 1}.")

    def case(self):
        whens = []
        while self.at_word("when"):
            self.take()
            condition = self.expr()
            self.expect_word("then", "after the CASE WHEN condition")
            whens.append(_make(When, condition=condition, result=self.expr()))
        otherwise = None
        if self.at_word("else"):
            self.take()
            otherwise = self.expr()
        self.expect_word("end", "to close CASE")
        return _make(Case, whens=whens, otherwise=otherwise)

    def call(self, name):
        function = name.lower()
        if function == "col":
            tok = self.take()
            if tok.kind != "string":
                raise ValueError('Write col("column name") with the name in quotes.')
            self.expect_op(")", 'to close col("…")')
            return _make(Column, name=_unquote(tok.text))
        unit, args = None, []
        if function in UNIT_FUNCTIONS:
            tok = self.peek()
            if tok.kind in {"name", "string"}:
                self.take()
                unit = tok.text if tok.kind == "name" else _unquote(tok.text)
                if self.peek().text == ",":
                    self.take()
            elif tok.kind == "op" and tok.text == ")":
                pass
            else:
                raise ValueError(f"{function.upper()} needs a unit first: day, week, month or year.")
        if not (self.peek().kind == "op" and self.peek().text == ")"):
            while True:
                args.append(self.expr())
                if self.peek().kind == "op" and self.peek().text == ",":
                    self.take()
                    continue
                break
        self.expect_op(")", f"to close {name}(")
        return _make(Call, function=name, unit=unit, args=args)


def _unquote(text: str) -> str:
    quote = text[0]
    return text[1:-1].replace(quote * 2, quote)


def _parse_tree(expression: str) -> Expression:
    if not isinstance(expression, str) or not expression.strip() or len(expression) > MAX_LENGTH:
        raise ValueError("Enter an expression of at most 1,000 characters.")
    try:
        root = _Parser(expression).parse()
    except RecursionError:
        raise ValueError("Calculation expression is too deeply nested.") from None
    return _make(Expression, source=expression, root=root)


# ---------------------------------------------------------------- binding and types

@dataclass
class Calculation:
    root: object
    result_type: str
    types: dict = field(default_factory=dict)      # id(node) -> type
    hints: dict = field(default_factory=dict)      # column -> type of its values
    today: date = field(default_factory=date.today)


def column_types(frame: pd.DataFrame) -> dict[str, str]:
    """number, text, bool or date, from a frame's dtypes (or its values when object)."""
    import datetime as dt
    out = {}
    for name in frame.columns:
        series = frame[name]
        if pd.api.types.is_bool_dtype(series.dtype):
            out[name] = "bool"
        elif pd.api.types.is_datetime64_any_dtype(series.dtype):
            out[name] = "date"
        elif pd.api.types.is_numeric_dtype(series.dtype):
            out[name] = "number"
        else:
            sample = series.dropna().head(50).tolist()
            if sample and all(isinstance(v, (bool, np.bool_)) for v in sample):
                out[name] = "bool"
            elif sample and all(isinstance(v, (dt.date, dt.datetime)) for v in sample):
                out[name] = "date"
            elif sample and all(isinstance(v, (int, float, Decimal, np.number))
                                and not isinstance(v, (bool, np.bool_)) for v in sample):
                out[name] = "number"
            else:
                out[name] = "text"
    return out


def check_syntax(expression: str, parameters=()) -> None:
    """Grammar, functions, units, arity, limits and @parameter names (no columns)."""
    tree = _parse_tree(expression)
    _resolve(tree.root, None, _param_values(parameters))


def _param_values(parameters) -> dict:
    out = {}
    for item in parameters or ():
        item = item if isinstance(item, dict) else item.model_dump()
        out[item["name"]] = item
    return out


def _resolve(node, columns, params):
    """Replace parameters with literals and check column names (when columns given)."""
    if isinstance(node, Keyword):
        text = node.text
        if columns is not None and text in columns:
            return Column(name=text)
        word = text.lower()
        return NullLit() if word == "null" else BoolLit(value=word == "true")
    if isinstance(node, Param):
        if node.name not in params:
            raise ValueError(f"Unknown parameter @{node.name}. Add it under Parameters first.")
        item = params[node.name]
        if item["kind"] == "number":
            return _make(NumberLit, value=item["value"])
        return _make(DateLit, value=str(item["value"])[:10])
    if isinstance(node, Column):
        if columns is not None and node.name not in columns:
            raise ValueError(f"Unknown column: {node.name}")
        return node
    updates = {}
    for name in ("operand", "left", "right", "otherwise"):
        child = getattr(node, name, None)
        if child is not None:
            updates[name] = _resolve(child, columns, params)
    if isinstance(node, Case):
        updates["whens"] = [When(condition=_resolve(w.condition, columns, params),
                                 result=_resolve(w.result, columns, params)) for w in node.whens]
    if isinstance(node, Call):
        updates["args"] = [_resolve(arg, columns, params) for arg in node.args]
    return node.model_copy(update=updates) if updates else node


def parse(expression: str, columns, types: dict | None = None, parameters=()) -> Calculation:
    tree = _parse_tree(expression)
    names = set(columns)
    root = _resolve(tree.root, names, _param_values(parameters))
    hints = {name: (types or {}).get(name, "text") for name in names}
    calc = Calculation(root=root, result_type="number", hints=hints)
    calc.result_type = _Typer(calc).resolve(root, None, "The expression")
    return calc


_CASTS = {"number": {"number", "text"}, "text": {"text"}, "bool": {"bool", "text"},
          "date": {"date", "text"}}   # target -> column kinds that convert to it


class _Typer:
    def __init__(self, calc):
        self.calc = calc

    def natural(self, node):
        if isinstance(node, NumberLit) or isinstance(node, (Negate, Arithmetic)):
            return "number"
        if isinstance(node, TextLit):
            return "text"
        if isinstance(node, DateLit):
            return "date"
        if isinstance(node, (BoolLit, Comparison, Logical, Not, IsNull)):
            return "bool"
        if isinstance(node, (NullLit, Column)):
            return None
        if isinstance(node, Case):
            return self.unify_natural([w.result for w in node.whens] + [node.otherwise], "CASE results")
        fn = node.function
        if fn == "coalesce":
            return self.unify_natural(node.args, "COALESCE values")
        if fn == "if":
            return self.unify_natural(node.args[1:], "IF results")
        return FUNCTIONS[fn][1]

    def unify_natural(self, nodes, what):
        kinds = {k for k in (self.natural(n) for n in nodes if n is not None) if k}
        if len(kinds) > 1:
            raise ValueError(f"{what} must all be one type, not {' and '.join(sorted(TYPE_LABEL[k] for k in kinds))}.")
        return kinds.pop() if kinds else None

    def hint(self, node):
        if isinstance(node, Column):
            return self.calc.hints.get(node.name, "text")
        if isinstance(node, Comparison):
            return self.shared_hint([node.left, node.right])
        branches = []
        if isinstance(node, Case):
            branches = [w.result for w in node.whens] + [node.otherwise]
        elif isinstance(node, Call) and node.function == "coalesce":
            branches = node.args
        elif isinstance(node, Call) and node.function == "if":
            branches = node.args[1:]
        return self.shared_hint(branches)

    def shared_hint(self, nodes):
        """One type for several type-less values; text columns convert to the others."""
        kinds = {self.hint(b) for b in nodes if b is not None and self.natural(b) is None} - {None}
        if len(kinds) > 1:
            typed = kinds - {"text"}   # text columns convert to any other type
            if len(typed) > 1:
                raise ValueError(f"These columns hold different types ({', '.join(sorted(typed))}); "
                                 "compare or combine values of one type.")
            return typed.pop()
        return kinds.pop() if kinds else None

    def resolve(self, node, want, role):
        kind = self.natural(node)
        if kind is None:
            kind = want or self.hint(node)
            if kind is None:
                raise ValueError(f"{role} can't be only NULL.")
        elif want and kind != want:
            raise ValueError(f"{role} must be {TYPE_LABEL[want]}, not {TYPE_LABEL[kind]}.")
        self.calc.types[id(node)] = kind
        if isinstance(node, Column):
            hint = self.calc.hints.get(node.name, "text")
            if hint not in _CASTS[kind]:
                advice = {("date", "number"): " Use YEAR(), MONTH() or DATEDIFF().",
                          ("number", "text"): " Compare it with a number.",
                          ("date", "text"): " Compare it with DATE 'YYYY-MM-DD'.",
                          ("number", "bool"): " Compare it, e.g. column = 1."}.get((hint, kind), "")
                held = {"number": "numbers", "text": "text", "bool": "true/false values", "date": "dates"}[hint]
                raise ValueError(f"Column {node.name} holds {held}, "
                                 f"so it can't be used as {TYPE_LABEL[kind]}.{advice}")
        elif isinstance(node, (Negate,)):
            self.resolve(node.operand, "number", "A negated value")
        elif isinstance(node, Arithmetic):
            self.resolve(node.left, "number", f"Each side of '{node.op}'")
            self.resolve(node.right, "number", f"Each side of '{node.op}'")
        elif isinstance(node, Comparison):
            if isinstance(node.left, NullLit) or isinstance(node.right, NullLit):
                raise ValueError("Use IS NULL or IS NOT NULL to test for missing values.")
            left, right = self.natural(node.left), self.natural(node.right)
            if left and right and left != right:
                raise ValueError(f"Can't compare {TYPE_LABEL[left]} with {TYPE_LABEL[right]}.")
            operand = left or right or self.hint(node) or "text"
            if node.op not in {"=", "!="} and operand not in {"number", "date"}:
                raise ValueError(f"'{node.op}' compares numbers or dates; use = or != for {TYPE_LABEL[operand]}.")
            self.resolve(node.left, operand, f"The left side of '{node.op}'")
            self.resolve(node.right, operand, f"The right side of '{node.op}'")
        elif isinstance(node, Logical):
            self.resolve(node.left, "bool", f"Each side of {node.op.upper()}")
            self.resolve(node.right, "bool", f"Each side of {node.op.upper()}")
        elif isinstance(node, Not):
            self.resolve(node.operand, "bool", "NOT's value")
        elif isinstance(node, IsNull):
            self.resolve(node.operand, None, "IS NULL's value")
        elif isinstance(node, Case):
            for when in node.whens:
                self.resolve(when.condition, "bool", "A CASE WHEN condition")
                self.resolve(when.result, kind, "Each CASE result")
            if node.otherwise is not None:
                self.resolve(node.otherwise, kind, "Each CASE result")
        elif isinstance(node, Call):
            name = node.function.upper()
            if node.function == "coalesce":
                for arg in node.args:
                    self.resolve(arg, kind, "Each COALESCE value")
            elif node.function == "if":
                self.resolve(node.args[0], "bool", "IF's condition")
                self.resolve(node.args[1], kind, "Each IF result")
                self.resolve(node.args[2], kind, "Each IF result")
            else:
                for arg, arg_kind in zip(node.args, FUNCTIONS[node.function][0]):
                    self.resolve(arg, arg_kind, f"{name}'s argument")
        return kind


# ---------------------------------------------------------------- pandas

DATE_PATTERN = r"^[1-9][0-9]{3}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
_PY_DATE = re.compile(DATE_PATTERN + r"(?:[ T]|\Z)")
_TRUE = ("true", "t", "yes", "y", "1", "1.0")
_FALSE = ("false", "f", "no", "n", "0", "0.0")


def _null(kind, n):
    if kind == "number":
        return np.full(n, np.nan)
    if kind == "date":
        return np.full(n, np.datetime64("NaT"), dtype="datetime64[D]")
    if kind == "bool":
        return np.zeros(n, dtype=bool), np.ones(n, dtype=bool)
    return np.full(n, None, dtype=object)


def _mask(kind, value):
    if kind == "number":
        return np.isnan(value)
    if kind == "date":
        return np.isnat(value)
    if kind == "bool":
        return value[1]
    return pd.isna(value)


def _text_values(series: pd.Series) -> np.ndarray:
    out = np.full(len(series), None, dtype=object)
    present = series.notna().to_numpy()
    out[present] = [str(v) for v in series[present].tolist()]
    return out


def _dates_from_text(text: np.ndarray) -> np.ndarray:
    out = np.full(len(text), np.datetime64("NaT"), dtype="datetime64[D]")
    picked = [(i, s.strip(" ")) for i, s in enumerate(text) if s is not None]
    picked = [(i, s) for i, s in picked if _PY_DATE.match(s)]
    if not picked:
        return out
    index = np.array([i for i, _ in picked])
    year = np.array([int(s[:4]) for _, s in picked])
    month = np.array([int(s[5:7]) for _, s in picked])
    day = np.array([int(s[8:10]) for _, s in picked])
    start = ((year - 1970) * 12 + month - 1).astype("datetime64[M]").astype("datetime64[D]")
    value = start + (day - 1).astype("timedelta64[D]")
    valid = value.astype("datetime64[M]") == start.astype("datetime64[M]")
    out[index[valid]] = value[valid]
    return out


def _dates_from_column(series: pd.Series) -> np.ndarray:
    import datetime as dt
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        values = series
        if getattr(series.dt, "tz", None) is not None:
            values = series.dt.tz_localize(None)
        return values.to_numpy().astype("datetime64[D]")
    out = np.full(len(series), np.datetime64("NaT"), dtype="datetime64[D]")
    for i, value in enumerate(series.tolist()):
        if isinstance(value, dt.datetime):
            out[i] = np.datetime64(value.date(), "D")
        elif isinstance(value, dt.date):
            out[i] = np.datetime64(value, "D")
        elif value is not None and not (isinstance(value, float) and math.isnan(value)):
            out[i] = _dates_from_text(np.array([str(value)], dtype=object))[0]
    return out


def _ymd(d):
    year = d.astype("datetime64[Y]").astype(np.int64) + 1970
    month = d.astype("datetime64[M]").astype(np.int64) % 12 + 1
    day = (d - d.astype("datetime64[M]").astype("datetime64[D]")).astype(np.int64) + 1
    return year, month, day


def _months_between(start, end):
    """Whole months as PostgreSQL age() counts them; see ``sql`` for the key trick."""
    nulls = np.isnat(start) | np.isnat(end)
    filler = np.datetime64("2000-01-01")
    sy, sm, sd = _ymd(np.where(nulls, filler, start))
    ey, em, ed = _ymd(np.where(nulls, filler, end))
    key = ((ey * 12 + em) * 100 + ed) - ((sy * 12 + sm) * 100 + sd)
    months = np.trunc(key / 100.0)
    months[nulls] = np.nan
    return months


def evaluate(calc: Calculation, frame: pd.DataFrame) -> pd.Series:
    n = len(frame)
    types = calc.types

    def column(node):
        kind, series = types[id(node)], frame[node.name]
        hint = calc.hints.get(node.name, "text")
        if kind == "number":
            values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
            return np.where(np.isfinite(values), values, np.nan)
        if kind == "date":
            return _dates_from_column(series) if hint == "date" else _dates_from_text(_text_values(series))
        text = _text_values(series)
        if kind == "bool":
            lowered = np.array([v.strip().lower() if v is not None else None for v in text], dtype=object)
            true, false = np.isin(lowered, _TRUE), np.isin(lowered, _FALSE)
            return true, ~(true | false)
        return text

    def literal(kind, value):
        if kind == "number":
            return np.full(n, float(value))
        if kind == "date":
            return np.full(n, np.datetime64(value, "D"), dtype="datetime64[D]")
        if kind == "bool":
            return np.full(n, bool(value)), np.zeros(n, dtype=bool)
        return np.full(n, value, dtype=object)

    def pick(kind, out, chosen, value):
        if kind == "bool":
            return np.where(chosen, value[0], out[0]), np.where(chosen, value[1], out[1])
        out = out.copy()
        out[chosen] = value[chosen]
        return out

    def truthy(value):
        return value[0] & ~value[1]

    def run(node):
        kind = types.get(id(node))
        if isinstance(node, NumberLit):
            return literal("number", node.value)
        if isinstance(node, TextLit):
            return literal("text", node.value)
        if isinstance(node, DateLit):
            return literal("date", node.value)
        if isinstance(node, BoolLit):
            return literal("bool", node.value)
        if isinstance(node, NullLit):
            return _null(kind, n)
        if isinstance(node, Column):
            return column(node)
        if isinstance(node, Negate):
            return -run(node.operand)
        if isinstance(node, Arithmetic):
            left, right = run(node.left), run(node.right)
            if node.op == "+":
                return left + right
            if node.op == "-":
                return left - right
            if node.op == "*":
                return left * right
            return left / np.where(right == 0, np.nan, right)
        if isinstance(node, Comparison):
            left, right = run(node.left), run(node.right)
            operand = types[id(node.left)]
            if operand == "bool":
                lv, lm = left
                rv, rm = right
                equal = lv == rv
                nulls = lm | rm
            else:
                nulls = _mask(operand, left) | _mask(operand, right)
                if operand == "text":
                    equal = np.array([a == b for a, b in zip(left, right)], dtype=bool)
                else:
                    filler = np.datetime64("2000-01-01") if operand == "date" else 0.0
                    left, right = np.where(nulls, filler, left), np.where(nulls, filler, right)
                    equal = left == right
            if node.op == "=":
                result = equal
            elif node.op == "!=":
                result = ~equal
            else:
                result = {"<": np.less, "<=": np.less_equal, ">": np.greater,
                          ">=": np.greater_equal}[node.op](left, right)
            return np.asarray(result, dtype=bool) & ~nulls, nulls
        if isinstance(node, Logical):
            (lv, lm), (rv, rm) = run(node.left), run(node.right)
            if node.op == "and":
                false = (~lv & ~lm) | (~rv & ~rm)
                true = lv & ~lm & rv & ~rm
            else:
                true = (lv & ~lm) | (rv & ~rm)
                false = ~lv & ~lm & ~rv & ~rm
            return true, ~(true | false)
        if isinstance(node, Not):
            value, nulls = run(node.operand)
            return ~value & ~nulls, nulls
        if isinstance(node, IsNull):
            nulls = _mask(types[id(node.operand)], run(node.operand))
            return (~nulls if node.negated else nulls), np.zeros(n, dtype=bool)
        if isinstance(node, Case):
            out = run(node.otherwise) if node.otherwise is not None else _null(kind, n)
            for when in reversed(node.whens):
                out = pick(kind, out, truthy(run(when.condition)), run(when.result))
            return out
        fn = node.function
        if fn == "if":
            return pick(kind, run(node.args[2]), truthy(run(node.args[0])), run(node.args[1]))
        if fn == "coalesce":
            values = [run(arg) for arg in node.args]
            out = values[-1]
            for value in reversed(values[:-1]):
                out = pick(kind, out, ~_mask(kind, value), value)
            return out
        if fn == "today":
            return literal("date", calc.today)
        args = [run(arg) for arg in node.args]
        if fn == "abs":
            return np.abs(args[0])
        if fn == "sqrt":
            return np.sqrt(np.where(args[0] >= 0, args[0], np.nan))
        if fn == "ln":
            return np.log(np.where(args[0] > 0, args[0], np.nan))
        if fn in {"year", "month"}:
            d = args[0]
            nulls = np.isnat(d)
            year, month, _ = _ymd(np.where(nulls, np.datetime64("2000-01-01"), d))
            out = (year if fn == "year" else month).astype(float)
            out[nulls] = np.nan
            return out
        if fn == "date_trunc":
            d = args[0]
            if node.unit == "week":
                days = d.astype(np.int64)
                return np.where(np.isnat(d), d, d - ((days + 3) % 7).astype("timedelta64[D]"))
            if node.unit == "month":
                return d.astype("datetime64[M]").astype("datetime64[D]")
            if node.unit == "year":
                return d.astype("datetime64[Y]").astype("datetime64[D]")
            return d
        start, end = args
        unit = "year" if fn == "age_at" else node.unit
        if unit in {"day", "week"}:
            days = (end - start).astype("timedelta64[D]")
            out = np.where(np.isnat(days), np.nan, days.astype(np.int64).astype(float))
            return np.trunc(out / 7) if unit == "week" else out
        months = _months_between(start, end)
        return months if unit == "month" else np.trunc(months / 12)

    with np.errstate(all="ignore"):
        value = run(calc.root)
    kind = calc.result_type
    if kind == "number":
        return pd.Series(np.where(np.isfinite(value), value, np.nan), index=frame.index, dtype="float64")
    if kind == "bool":
        values, nulls = value
        text = np.where(values, "true", "false").astype(object)
        text[nulls] = None
        return pd.Series(text, index=frame.index, dtype=object)
    if kind == "date":
        return pd.Series(value.astype(object), index=frame.index, dtype=object)
    return pd.Series(value, index=frame.index, dtype=object)


# ---------------------------------------------------------------- SQL

class _Dialect:
    def __init__(self, column: Callable[[str], str], bind: Callable[[object], str] | None):
        self.ref, self.bind = column, bind

    def text(self, value: str) -> str:
        if self.bind:
            return f"CAST({self.bind(value)} AS text)"
        return "'" + value.replace("'", "''") + "'"

    def number(self, value: float) -> str:
        if not math.isfinite(value):
            raise ValueError("Constants must be finite numbers.")
        if self.bind:
            return f"CAST({self.bind(float(value))} AS {self.double})"
        return f"CAST({float(value)!r} AS DOUBLE)"

    def date(self, value: date) -> str:
        if self.bind:
            return f"CAST({self.bind(value.isoformat())} AS date)"
        return f"DATE '{date.fromisoformat(value.isoformat()).isoformat()}'"


class _Postgres(_Dialect):
    double, string, datetype = "double precision", "text", "date"

    def as_number(self, ref):
        value = f"TRIM(({ref})::text)"
        pattern = r"^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$"
        return f"CASE WHEN {value} ~ '{pattern}' THEN ({value})::double precision END"

    def text_to_date(self, ref):
        t = f"BTRIM(CAST({ref} AS text))"
        part = lambda start, length: f"CAST(SUBSTRING({t} FROM {start} FOR {length}) AS integer)"
        first = f"MAKE_DATE({part(1, 4)}, {part(6, 2)}, 1)"
        candidate = f"({first} + ({part(9, 2)} - 1))"
        return (f"CASE WHEN {t} ~ '{DATE_PATTERN}($|[ T])' THEN CASE WHEN "
                f"EXTRACT(MONTH FROM {candidate}) = {part(6, 2)} THEN {candidate} END END")

    def trunc(self, unit, value):
        return f"CAST(DATE_TRUNC('{unit}', CAST({value} AS timestamp)) AS date)"


class _DuckDB(_Dialect):
    double, string, datetype = "DOUBLE", "VARCHAR", "DATE"

    def as_number(self, ref):
        value = f"TRY_CAST({ref} AS DOUBLE)"
        return f"CASE WHEN ISFINITE({value}) THEN {value} ELSE NULL END"

    def text_to_date(self, ref):
        t = f"TRIM(CAST({ref} AS VARCHAR))"
        return (f"CASE WHEN regexp_matches({t}, '{DATE_PATTERN}($|[ T])') "
                f"THEN TRY_CAST(SUBSTR({t}, 1, 10) AS DATE) END")

    def trunc(self, unit, value):
        return f"CAST(DATE_TRUNC('{unit}', {value}) AS DATE)"


def sql(calc: Calculation, dialect: str, column: Callable[[str], str],
        bind: Callable[[object], str] | None = None) -> str:
    """SQL for the calculation. ``column`` returns a quoted column reference;
    ``bind`` (PostgreSQL) returns a placeholder for a constant."""
    d = _Postgres(column, bind) if dialect == "postgres" else _DuckDB(column, None)
    types = calc.types
    sql_type = {"number": d.double, "text": d.string, "date": d.datetype, "bool": "BOOLEAN"}

    def col(node):
        kind, hint, ref = types[id(node)], calc.hints.get(node.name, "text"), d.ref(node.name)
        if kind == "number":
            return d.as_number(ref)
        if kind == "date":
            return f"CAST({ref} AS {d.datetype})" if hint == "date" else d.text_to_date(ref)
        if kind == "bool":
            lowered = f"LOWER(TRIM(CAST({ref} AS {d.string})))"
            true = ", ".join(f"'{v}'" for v in _TRUE)
            false = ", ".join(f"'{v}'" for v in _FALSE)
            return f"CASE WHEN {lowered} IN ({true}) THEN TRUE WHEN {lowered} IN ({false}) THEN FALSE END"
        return f"CAST({ref} AS {d.string})"

    def months(start, end):
        # key(d) = (year * 12 + month) * 100 + day orders dates like the dates themselves,
        # and trunc((key(end) - key(start)) / 100) counts a month only once the end's day
        # reaches the start's day, i.e. PostgreSQL age() years * 12 + months, in either
        # direction. Each date appears three times, which keeps nested SQL small.
        def key(value):
            return (f"((EXTRACT(YEAR FROM {value}) * 12 + EXTRACT(MONTH FROM {value})) * 100 "
                    f"+ EXTRACT(DAY FROM {value}))")
        return f"TRUNC(CAST({key(end)} - {key(start)} AS {d.double}) / 100)"

    def run(node):
        # Checked per node: sqrt() and DATEDIFF repeat their arguments, so nested
        # calls grow the SQL geometrically and must stop before it gets large.
        out = compile_node(node)
        if len(out) > MAX_SQL:
            raise ValueError("Calculation expression is too complex.")
        return out

    def compile_node(node):
        kind = types.get(id(node))
        if isinstance(node, NumberLit):
            return d.number(node.value)
        if isinstance(node, TextLit):
            return d.text(node.value)
        if isinstance(node, DateLit):
            return d.date(node.value)
        if isinstance(node, BoolLit):
            return "TRUE" if node.value else "FALSE"
        if isinstance(node, NullLit):
            return f"CAST(NULL AS {sql_type[kind]})"
        if isinstance(node, Column):
            return col(node)
        if isinstance(node, Negate):
            return f"(-({run(node.operand)}))"
        if isinstance(node, Arithmetic):
            left, right = run(node.left), run(node.right)
            if node.op == "/":
                right = f"NULLIF(({right}), 0.0)"
            return f"(({left}) {node.op} ({right}))"
        if isinstance(node, Comparison):
            op = "<>" if node.op == "!=" else node.op
            return f"(({run(node.left)}) {op} ({run(node.right)}))"
        if isinstance(node, Logical):
            return f"(({run(node.left)}) {node.op.upper()} ({run(node.right)}))"
        if isinstance(node, Not):
            return f"(NOT ({run(node.operand)}))"
        if isinstance(node, IsNull):
            return f"(({run(node.operand)}) IS {'NOT ' if node.negated else ''}NULL)"
        if isinstance(node, Case):
            whens = " ".join(f"WHEN ({run(w.condition)}) THEN ({run(w.result)})" for w in node.whens)
            otherwise = f" ELSE ({run(node.otherwise)})" if node.otherwise is not None else ""
            return f"CASE {whens}{otherwise} END"
        fn = node.function
        if fn == "today":
            return d.date(calc.today)
        args = [run(arg) for arg in node.args]
        if fn == "if":
            return f"CASE WHEN ({args[0]}) THEN ({args[1]}) ELSE ({args[2]}) END"
        if fn == "coalesce":
            return f"COALESCE({', '.join(args)})"
        if fn == "abs":
            return f"ABS({args[0]})"
        if fn == "sqrt":
            return f"CASE WHEN ({args[0]}) >= 0 THEN SQRT({args[0]}) END"
        if fn == "ln":
            return f"CASE WHEN ({args[0]}) > 0 THEN LN({args[0]}) END"
        if fn in {"year", "month"}:
            return f"CAST(EXTRACT({fn.upper()} FROM ({args[0]})) AS {d.double})"
        if fn == "date_trunc":
            return f"({args[0]})" if node.unit == "day" else d.trunc(node.unit, f"({args[0]})")
        start, end = (f"({arg})" for arg in args)
        unit = "year" if fn == "age_at" else node.unit
        if unit == "day":
            return f"CAST({end} - {start} AS {d.double})"
        if unit == "week":
            return f"TRUNC(CAST({end} - {start} AS {d.double}) / 7)"
        if unit == "month":
            return months(start, end)
        return f"TRUNC({months(start, end)} / 12)"

    body = run(calc.root)
    kind = calc.result_type
    if kind == "bool":
        result = f"CASE ({body}) WHEN TRUE THEN 'true' WHEN FALSE THEN 'false' END"
    else:
        result = f"CAST(({body}) AS {sql_type[kind]})"
    if len(result) > MAX_SQL:
        raise ValueError("Calculation expression is too complex.")
    return result


def setting(name: str, result_type: str) -> dict | None:
    """The column setting a calculated column gets, from its result type."""
    if result_type == "number":
        return {"name": name, "logical_type": "number", "filter_kind": "range"}
    if result_type == "date":
        return {"name": name, "filter_kind": "date"}
    if result_type == "bool":
        return {"name": name, "filter_kind": "categorical"}
    return None   # text: the usual inference picks categorical or none
