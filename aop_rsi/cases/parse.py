"""Deterministic parsing of what an email states: the as-of date and a stated quantity.

Enough for the baselines and for case signatures. The optimizer's LLM nodes do
this with context at deployment; here it is code so E0′–E2 run without a model.
"""
from __future__ import annotations

import datetime as dt
import re

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
_MON3 = {m[:3]: i for m, i in _MONTHS.items()}

_P_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_P_US = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_P_DMY_ABBR = re.compile(r"\b(\d{1,2})-([A-Z][a-z]{2})-(\d{4})\b")
_P_MDY_LONG = re.compile(r"\b([A-Z][a-z]+) (\d{1,2}), (\d{4})\b")
_P_DMY_LONG = re.compile(r"\b(\d{1,2}) ([A-Z][a-z]+) (\d{4})\b")
_P_WDM = re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{1,2}) ([A-Z][a-z]{2}) (\d{4})\b")
_P_REL = re.compile(r"\b(end of last month|month-end|last day of last month|yesterday)\b", re.I)


_HEADER_LINE = re.compile(r"^\s*(-{3,}.*-{3,}|From:.*|Date:.*|Sent:.*|To:.*|Subject:.*)$", re.M)


def strip_headers(body: str) -> str:
    """Drop forwarded-message header lines so their dates are not read as the as-of."""
    return _HEADER_LINE.sub("", body)


def parse_as_of(body: str, sent: str) -> tuple[str | None, str]:
    """Return (ISO date or None, kind) with kind ∈ {explicit, relative, none}."""
    body = strip_headers(body)
    s = dt.date.fromisoformat(sent)
    if m := _P_ISO.search(body):
        return _iso(int(m[1]), int(m[2]), int(m[3])), "explicit"
    if m := _P_US.search(body):
        return _iso(int(m[3]), int(m[1]), int(m[2])), "explicit"
    if m := _P_DMY_ABBR.search(body):
        return _iso(int(m[3]), _MON3.get(m[2].lower(), 0), int(m[1])), "explicit"
    if m := _P_WDM.search(body):
        return _iso(int(m[3]), _MON3.get(m[2].lower(), 0), int(m[1])), "explicit"
    if m := _P_MDY_LONG.search(body):
        if (mo := _MONTHS.get(m[1].lower())):
            return _iso(int(m[3]), mo, int(m[2])), "explicit"
    if m := _P_DMY_LONG.search(body):
        if (mo := _MONTHS.get(m[2].lower())):
            return _iso(int(m[3]), mo, int(m[1])), "explicit"
    if m := _P_REL.search(body):
        phrase = m[1].lower()
        if phrase == "yesterday":
            return (s - dt.timedelta(days=1)).isoformat(), "relative"
        return (dt.date(s.year, s.month, 1) - dt.timedelta(days=1)).isoformat(), "relative"
    return None, "none"


def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


_P_QTY = re.compile(
    r"(?:records show|on our books|our figure is|we show|we have)[^\d\-]{0,12}?(-?[\d][\d,]*(?:\.\d+)?)\s*(k|mm)?\b", re.I)
_P_QTY2 = re.compile(r"(-?[\d][\d,]*(?:\.\d+)?)\s*(k|mm)?\s+(?:units|shares)\b", re.I)


def parse_stated_qty(body: str) -> int | None:
    body = strip_headers(body)
    m = _P_QTY.search(body) or _P_QTY2.search(body)
    if not m:
        return None
    num = float(m[1].replace(",", ""))
    mult = {"k": 1_000, "mm": 1_000_000}.get((m[2] or "").lower(), 1)
    return int(round(num * mult))
