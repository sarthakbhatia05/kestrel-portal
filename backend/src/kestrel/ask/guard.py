"""Numeric guard on generated prose.

PRD C4.4: the product must not generate a plausible number for a question
it cannot actually answer. The language model never sees a row and never
computes anything, but it does write framing prose around a computed
result, and a model asked to describe 92.34% can still write 87.5%.

So every number in generated prose is checked against the numbers actually
present in the computed result, at the precision the prose rendered them.
Prose containing anything else is discarded whole -- the deterministic
answer is the answer of record and stands on its own without it.
"""

import re
from typing import Any

from pydantic import BaseModel

# Matches 1108, 1,200, 92.34 and the digits inside FY27.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _walk(value: Any, numbers: set[float], text_tokens: set[str]) -> None:
    if isinstance(value, BaseModel):
        _walk(value.model_dump(), numbers, text_tokens)
    elif isinstance(value, dict):
        for item in value.values():
            _walk(item, numbers, text_tokens)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk(item, numbers, text_tokens)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float)):
        numbers.add(float(value))
    else:
        # Dates, period labels and exclusion codes carry digits a sentence
        # may legitimately quote ("FY27 Q1", "X1"). They are quotable as
        # written, so they are matched as text rather than as quantities.
        text_tokens.update(_NUMBER.findall(str(value)))


def _tokens(result: Any) -> tuple[set[float], set[str]]:
    numbers: set[float] = set()
    text_tokens: set[str] = set()
    _walk(result, numbers, text_tokens)
    return numbers, text_tokens


def _matches(token: str, numbers: set[float]) -> bool:
    cleaned = token.replace(",", "")
    written = float(cleaned)
    _, _, fraction = cleaned.partition(".")
    decimals = len(fraction)
    for value in numbers:
        # A rate of 0.9234 may legitimately be written as 92.34%: both the
        # stored fraction and its percentage form count as the same figure.
        if round(value, decimals) == written or round(value * 100, decimals) == written:
            return True
    return False


def check(prose: str, result: Any) -> bool:
    """True when every number in `prose` appears in `result`."""
    numbers, text_tokens = _tokens(result)
    for token in _NUMBER.findall(prose):
        if token.replace(",", "") in text_tokens or token in text_tokens:
            continue
        if not _matches(token, numbers):
            return False
    return True


def apply(prose: str | None, result: Any) -> str | None:
    """The prose if every number in it checks out, otherwise None.

    Callers degrade to the deterministic answer on None. Nothing is
    repaired or retried: a sentence that invented one figure has already
    shown it is not describing this result.
    """
    if prose is None:
        return None
    return prose if check(prose, result) else None
