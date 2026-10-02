"""Idea -> strategy proposal. The model drafts; validation and the user decide."""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from ..schema import (
    All, AnyOf, Compare, ConstOperand, Cross, IndicatorOperand, Not, PriceOperand, Strategy,
)
from .prompt import AGENT_PROMPT, REPAIR_PROMPT, SYSTEM_PROMPT
from .providers import Provider, ProviderError, default_provider

__all__ = ["propose", "translate_agent", "default_provider", "ProviderError", "number_fidelity"]


def _extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def _parse(raw: str) -> tuple[Strategy | None, list[str], str]:
    data = _extract_json(raw)
    if not isinstance(data, dict):
        raise ValueError("Top level must be a JSON object.")
    questions = [str(q) for q in (data.get("questions") or []) if str(q).strip()][:5]
    notes = str(data.get("notes") or "")
    body = data.get("strategy")
    if body is None:
        if not questions:
            raise ValueError("strategy is null but no questions were given.")
        return None, questions, notes
    if not isinstance(body, dict):
        raise ValueError("strategy must be an object or null.")
    # Small models sometimes nest envelope fields inside the strategy; lift them out.
    body = dict(body)
    inner_notes = str(body.pop("notes", "") or "")
    notes = notes or inner_notes
    for q in body.pop("questions", None) or []:
        if str(q).strip() and str(q) not in questions:
            questions.append(str(q))
    body["questions"] = questions[:5]
    return Strategy.model_validate(body), questions[:5], notes


def _numbers_in_strategy(s: Strategy) -> set[float]:
    nums: set[float] = set()

    def op(o):
        if isinstance(o, ConstOperand):
            nums.add(abs(o.value))
        elif isinstance(o, IndicatorOperand):
            nums.update({float(o.period), float(o.offset)})
        elif isinstance(o, PriceOperand):
            nums.add(float(o.offset))

    def walk(c):
        if isinstance(c, (Compare, Cross)):
            op(c.left)
            op(c.right)
        elif isinstance(c, (All, AnyOf)):
            for i in c.items:
                walk(i)
        elif isinstance(c, Not):
            walk(c.item)

    walk(s.entry)
    walk(s.exit)
    nums.update({s.sizing.value, s.costs.fee_bps, s.costs.slippage_bps, s.initial_capital})
    return nums


_STATE_WORDS = re.compile(r"\b(?:is|are|stays?|remains?|closes?|trades?)\s+(?:above|below|over|under|greater|less|higher|lower)\b", re.I)
_CROSS_WORDS = re.compile(r"\b(?:cross\w*|drops?|falls?|rises?|breaks?|moves?|goes)\b", re.I)


def wording_checks(text: str, s: Strategy) -> list[str]:
    """Deterministic cross-checks between the user's words and the drafted rules."""
    out: list[str] = []
    has_cross = any(isinstance(n, Cross) for n in _nodes(s.entry)) or any(isinstance(n, Cross) for n in _nodes(s.exit))
    if has_cross and _STATE_WORDS.search(text) and not _CROSS_WORDS.search(text):
        out.append("You described a state ('is above/below'), but the rules use 'crosses' (only the day it happens). "
                   "Check whether a plain comparison was intended.")
    return out


def _nodes(c):
    yield c
    if isinstance(c, (All, AnyOf)):
        for i in c.items:
            yield from _nodes(i)
    elif isinstance(c, Not):
        yield from _nodes(c.item)


def drop_false_questions(text: str, questions: list[str]) -> list[str]:
    """Remove 'X not stated - using N' questions when the user did state N."""
    typed = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)}
    keep = []
    for q in questions:
        if re.search(r"not stated|periods? .*used|using \d", q, re.I):
            nums = {float(x) for x in re.findall(r"\d+(?:\.\d+)?", q)}
            if nums and nums <= typed:
                continue
        keep.append(q)
    return keep


def number_fidelity(text: str, s: Strategy) -> list[str]:
    """Every number the user typed should appear somewhere in the strategy."""
    found = {float(x.replace(",", "")) for x in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", text)}
    have = _numbers_in_strategy(s)
    missing = sorted(n for n in found if not any(abs(n - h) < 1e-9 for h in have))
    return [f"You mentioned {n:g} but it does not appear in the rules — check it was not dropped or changed."
            for n in missing]


def propose(message: str, current: Strategy | None, history: list[dict],
            provider: Provider | None = None, check_wording: bool = True) -> dict:
    provider = provider or default_provider()
    msgs: list[dict] = []
    for h in history[-6:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": h["content"]})
    user = message if current is None else (
        f"Current strategy JSON:\n{current.model_dump_json()}\n\nRequested change / answer:\n{message}"
    )
    msgs.append({"role": "user", "content": user})

    raw = provider.complete(SYSTEM_PROMPT, msgs)
    attempts = 1
    try:
        strategy, questions, notes = _parse(raw)
    except (ValueError, ValidationError) as e:
        attempts = 2
        err = str(e)[:1500]
        msgs += [{"role": "assistant", "content": raw}, {"role": "user", "content": REPAIR_PROMPT.format(error=err)}]
        raw = provider.complete(SYSTEM_PROMPT, msgs)
        try:
            strategy, questions, notes = _parse(raw)
        except (ValueError, ValidationError) as e2:
            return {"ok": False, "strategy": None, "questions": [], "notes": "",
                    "error": f"The model's answer did not match the strategy format after a retry: {str(e2)[:300]}",
                    "fidelity": [], "attempts": attempts, "provider": provider.name, "model": provider.model}

    if check_wording:
        questions = drop_false_questions(message, questions)
        if strategy:
            strategy = strategy.model_copy(update={"questions": questions})
    fidelity = (number_fidelity(message, strategy) + wording_checks(message, strategy)) if strategy and check_wording else []
    return {"ok": True, "strategy": strategy.model_dump() if strategy else None, "questions": questions,
            "notes": notes, "error": None, "fidelity": fidelity, "attempts": attempts,
            "provider": provider.name, "model": provider.model}


def code_percent_checks(code: str, s: Strategy) -> list[str]:
    """Fractions like 0.05 in bot code usually mean 5%; each should appear as a P&L rule."""
    code = re.sub(r"//@version=\d+", "", code)
    fractions = {round(float(x) * 100, 4) for x in re.findall(r"(?<![\w.])0\.\d{1,4}(?![\d.])", code)}
    have = {round(abs(o.value), 4) for n in list(_nodes(s.entry)) + list(_nodes(s.exit))
            if isinstance(n, Compare) for o in (n.right, n.left) if isinstance(o, ConstOperand)}
    return [f"The code contains {p / 100:g} (= {p:g}%), but no rule uses {p:g}%. Check the take-profit / stop values."
            for p in sorted(fractions) if 0 < p < 100 and p not in have]


def translate_agent(code: str, filename: str, provider: Provider | None = None, is_code: bool = True) -> dict:
    """Translate an uploaded file (bot source or a document describing a strategy) into a proposal.
    Nothing is ever executed."""
    result = propose(AGENT_PROMPT.format(filename=filename, code=code), None, [], provider, check_wording=False)
    if result["strategy"] and is_code:
        result["fidelity"] = code_percent_checks(code, Strategy.model_validate(result["strategy"]))
    return result
