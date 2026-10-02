"""Daily OHLC CSV import. Accepts the NSE website export and plain date/open/high/low/close files."""
from __future__ import annotations

import csv
import io
from datetime import datetime

from .engine import Bar

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20_000

_ALIASES = {
    "date": {"date", "timestamp", "trade date", "datetime"},
    "open": {"open", "open price", "opn"},
    "high": {"high", "high price"},
    "low": {"low", "low price"},
    "close": {"close", "close price", "closing price"},
    "volume": {"volume", "total traded quantity", "shares traded", "no. of shares", "vol"},
}
_DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%Y/%m/%d", "%d-%B-%Y")


class CsvError(ValueError):
    pass


def _norm(h: str) -> str:
    return " ".join(h.replace("﻿", "").strip().lower().split())


def _num(raw: str, col: str, line: int) -> float:
    s = (raw or "").strip().replace(",", "")
    if s in ("", "-"):
        raise CsvError(f"Line {line}: missing {col}.")
    try:
        return float(s)
    except ValueError:
        raise CsvError(f"Line {line}: {col} '{raw}' is not a number.") from None


def _date(raw: str, line: int) -> str:
    s = (raw or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise CsvError(f"Line {line}: date '{raw}' not recognised (use YYYY-MM-DD or DD-Mon-YYYY).")


def parse_csv(data: bytes) -> tuple[list[Bar], list[str]]:
    if len(data) > MAX_BYTES:
        raise CsvError("File is larger than 5 MB.")
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        raise CsvError("File is empty.") from None

    cols: dict[str, int] = {}
    for idx, h in enumerate(header):
        name = _norm(h)
        for key, names in _ALIASES.items():
            if name in names and key not in cols:
                cols[key] = idx
    missing = [k for k in ("date", "open", "close") if k not in cols]
    if missing:
        raise CsvError(f"Missing column(s): {', '.join(missing)}. Found: {', '.join(h.strip() for h in header)}.")

    warnings: list[str] = []
    if "high" not in cols or "low" not in cols:
        warnings.append("No high/low columns — they are set to max/min of open and close.")

    rows: dict[str, Bar] = {}
    for line, row in enumerate(reader, start=2):
        if not row or all(not c.strip() for c in row):
            continue
        if len(rows) >= MAX_ROWS:
            raise CsvError(f"More than {MAX_ROWS} rows.")
        get = lambda k: row[cols[k]] if cols.get(k) is not None and cols[k] < len(row) else ""
        d = _date(get("date"), line)
        o, c = _num(get("open"), "open", line), _num(get("close"), "close", line)
        hi = _num(get("high"), "high", line) if "high" in cols else max(o, c)
        lo = _num(get("low"), "low", line) if "low" in cols else min(o, c)
        vol = _num(get("volume"), "volume", line) if "volume" in cols and get("volume").strip() else 0.0
        if min(o, c, hi, lo) <= 0:
            raise CsvError(f"Line {line}: prices must be positive.")
        if hi < max(o, c) - 1e-9 or lo > min(o, c) + 1e-9:
            raise CsvError(f"Line {line}: high/low inconsistent with open/close.")
        bar = Bar(d, o, hi, lo, c, vol)
        if d in rows:
            if rows[d] != bar:
                raise CsvError(f"Date {d} appears twice with different prices.")
            continue
        rows[d] = bar

    bars = [rows[k] for k in sorted(rows)]
    if len(bars) < 2:
        raise CsvError("Need at least 2 rows of prices.")
    if list(rows) and list(rows)[0] > list(rows)[-1]:
        warnings.append("Rows were newest-first; sorted oldest-first.")
    return bars, warnings
