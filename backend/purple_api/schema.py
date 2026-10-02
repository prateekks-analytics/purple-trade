"""Strategy domain: a typed condition tree that is the single source of truth.

The graph shown in the UI, the plain-English rules and the backtest engine are
all derived from this structure, so what the user reviews is exactly what runs.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

PriceField = Literal["open", "high", "low", "close", "volume"]
IndicatorName = Literal["sma", "ema", "rsi", "highest", "lowest"]
CompareOp = Literal["<", "<=", "==", "!=", ">=", ">"]
PositionField = Literal["bars_held", "pnl_pct"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- operands ----------

class PriceOperand(_Strict):
    kind: Literal["price"] = "price"
    field: PriceField = "close"
    offset: int = Field(0, ge=0, le=250, description="Bars back; 1 = previous bar")


class IndicatorOperand(_Strict):
    kind: Literal["indicator"] = "indicator"
    name: IndicatorName
    period: int = Field(..., ge=1, le=500)
    source: PriceField = "close"
    offset: int = Field(0, ge=0, le=250)


class ConstOperand(_Strict):
    kind: Literal["const"] = "const"
    value: float


class PositionOperand(_Strict):
    """Only meaningful while holding a position (exit rules)."""
    kind: Literal["position"] = "position"
    field: PositionField


Operand = Annotated[
    Union[PriceOperand, IndicatorOperand, ConstOperand, PositionOperand],
    Field(discriminator="kind"),
]


# ---------- conditions ----------

class Compare(_Strict):
    kind: Literal["compare"] = "compare"
    left: Operand
    op: CompareOp
    right: Operand


class Cross(_Strict):
    """left moves from <= right (previous bar) to > right (this bar), or the mirror."""
    kind: Literal["cross"] = "cross"
    left: Operand
    direction: Literal["above", "below"]
    right: Operand


class All(_Strict):
    kind: Literal["all"] = "all"
    items: list["Condition"] = Field(..., min_length=1)


class AnyOf(_Strict):
    kind: Literal["any"] = "any"
    items: list["Condition"] = Field(..., min_length=1)


class Not(_Strict):
    kind: Literal["not"] = "not"
    item: "Condition"


Condition = Annotated[
    Union[Compare, Cross, All, AnyOf, Not],
    Field(discriminator="kind"),
]

All.model_rebuild()
AnyOf.model_rebuild()
Not.model_rebuild()


# ---------- strategy ----------

class Sizing(_Strict):
    mode: Literal["percent_equity"] = "percent_equity"
    value: float = Field(100, gt=0, le=100)


class Costs(_Strict):
    fee_bps: float = Field(3, ge=0, le=500, description="Per side, on traded value")
    slippage_bps: float = Field(5, ge=0, le=500, description="Per side, adverse to fill")


class Strategy(_Strict):
    name: str = Field("Untitled strategy", max_length=120)
    entry: Condition
    exit: Condition
    sizing: Sizing = Sizing()
    costs: Costs = Costs()
    initial_capital: float = Field(100_000, gt=0, le=1e10)
    questions: list[str] = Field(
        default_factory=list,
        description="Open ambiguities. Approval is blocked until this list is empty.",
    )


def strategy_json_schema() -> dict:
    return Strategy.model_json_schema()
