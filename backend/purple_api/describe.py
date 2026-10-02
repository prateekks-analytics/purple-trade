"""Plain-English rendering and validation, generated from the tree (never from the AI)."""
from __future__ import annotations

from .schema import (
    All, AnyOf, Compare, ConstOperand, Cross, IndicatorOperand, Not,
    PositionOperand, PriceOperand, Strategy,
)

_OP_WORDS = {"<": "<", "<=": "≤", "==": "=", "!=": "≠", ">=": "≥", ">": ">"}
_FIELD = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}


def _ago(offset: int) -> str:
    if offset == 0:
        return ""
    return " (previous bar)" if offset == 1 else f" ({offset} bars ago)"


def _num(v: float) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v):,}"


def operand_text(o) -> str:
    if isinstance(o, PriceOperand):
        return f"{_FIELD[o.field]}{_ago(o.offset)}"
    if isinstance(o, IndicatorOperand):
        src = "" if o.source == "close" else f" of {_FIELD[o.source]}"
        label = {"sma": "SMA", "ema": "EMA", "rsi": "RSI",
                 "highest": "Highest", "lowest": "Lowest"}[o.name]
        return f"{label}({o.period}){src}{_ago(o.offset)}"
    if isinstance(o, ConstOperand):
        return _num(o.value)
    if isinstance(o, PositionOperand):
        return "Days held" if o.field == "bars_held" else "Trade P&L %"
    raise TypeError(o)


def _pnl_const(c: Compare) -> str | None:
    if isinstance(c.left, PositionOperand) and c.left.field == "pnl_pct" and isinstance(c.right, ConstOperand):
        sign = "+" if c.right.value > 0 else ""
        return f"Trade P&L {_OP_WORDS[c.op]} {sign}{_num(c.right.value)}%"
    return None


def condition_text(c) -> str:
    if isinstance(c, Compare):
        return _pnl_const(c) or f"{operand_text(c.left)} {_OP_WORDS[c.op]} {operand_text(c.right)}"
    if isinstance(c, Cross):
        return f"{operand_text(c.left)} crosses {c.direction} {operand_text(c.right)}"
    if isinstance(c, Not):
        return f"NOT ({condition_text(c.item)})"
    if isinstance(c, (All, AnyOf)):
        joiner = " AND " if isinstance(c, All) else " OR "
        parts = [condition_text(i) for i in c.items]
        if len(parts) == 1:
            return parts[0]
        return joiner.join(f"({p})" if (" AND " in p or " OR " in p) else p for p in parts)
    raise TypeError(c)


def condition_lines(c, depth: int = 0) -> list[str]:
    """Indented outline, easier to read than one long sentence."""
    pad = "  " * depth
    if isinstance(c, (All, AnyOf)) and len(c.items) > 1:
        head = "ALL of:" if isinstance(c, All) else "ANY of:"
        lines = [f"{pad}{head}"]
        for i in c.items:
            lines += condition_lines(i, depth + 1)
        return lines
    if isinstance(c, (All, AnyOf)):
        return condition_lines(c.items[0], depth)
    return [f"{pad}• {condition_text(c)}"]


def describe(s: Strategy) -> dict:
    return {
        "entry": condition_text(s.entry),
        "exit": condition_text(s.exit),
        "entry_lines": condition_lines(s.entry),
        "exit_lines": condition_lines(s.exit),
        "execution": (
            f"Signals use the completed daily close. Orders fill at the next day's open. "
            f"Long only, whole shares, {_num(s.sizing.value)}% of equity per trade. "
            f"Costs: {_num(s.costs.fee_bps)} bps fee + {_num(s.costs.slippage_bps)} bps slippage per side."
        ),
    }


# ---------- validation ----------

def _walk(c):
    yield c
    if isinstance(c, (All, AnyOf)):
        for i in c.items:
            yield from _walk(i)
    elif isinstance(c, Not):
        yield from _walk(c.item)


def _operands(c):
    for node in _walk(c):
        if isinstance(node, (Compare, Cross)):
            yield node.left
            yield node.right


def validate(s: Strategy) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    if any(isinstance(o, PositionOperand) for o in _operands(s.entry)):
        errors.append("Entry rules cannot use 'Days held' or 'Trade P&L' — there is no open trade yet.")

    for side, cond in (("Entry", s.entry), ("Exit", s.exit)):
        for node in _walk(cond):
            if isinstance(node, (Compare, Cross)):
                if isinstance(node.left, ConstOperand) and isinstance(node.right, ConstOperand):
                    errors.append(f"{side}: '{condition_text(node)}' compares two fixed numbers.")
                if isinstance(node, Cross) and isinstance(node.left, PositionOperand | ConstOperand):
                    errors.append(f"{side}: 'crosses' needs a price or indicator on the left.")
                if isinstance(node, Compare) and node.op == "==" and not _is_integer_valued(node):
                    warnings.append(
                        f"{side}: '{condition_text(node)}' — equality is tested after rounding to 2 decimals; "
                        "indicators rarely land exactly on a value. Consider 'crosses' or ≤/≥ if that is what you mean."
                    )
                for o in (node.left, node.right):
                    if isinstance(o, IndicatorOperand) and o.name == "rsi" and isinstance(node.right, ConstOperand):
                        if not 0 <= node.right.value <= 100:
                            errors.append(f"{side}: RSI is always between 0 and 100 ('{condition_text(node)}').")

    uses_position_exit = any(isinstance(o, PositionOperand) for o in _operands(s.exit))
    if not uses_position_exit:
        warnings.append("No stop-loss or time limit in the exit rules — a losing trade can stay open indefinitely.")

    if s.questions:
        errors.append(f"{len(s.questions)} open question(s) must be answered or dismissed before approval.")

    return {"ok": not errors, "errors": errors, "warnings": warnings, "warmup_bars": warmup_bars(s)}


def _is_integer_valued(node: Compare) -> bool:
    ints = ("bars_held", "volume")
    def is_int(o):
        return (isinstance(o, PositionOperand) and o.field in ints) or (isinstance(o, PriceOperand) and o.field == "volume")
    return is_int(node.left) or is_int(node.right)


def warmup_bars(s: Strategy) -> int:
    need = 0
    for o in list(_operands(s.entry)) + list(_operands(s.exit)):
        if isinstance(o, IndicatorOperand):
            extra = 1 if o.name == "rsi" else 0
            need = max(need, o.period + extra + o.offset)
        elif isinstance(o, PriceOperand):
            need = max(need, o.offset + 1)
    return need
