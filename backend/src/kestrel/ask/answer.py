"""The deterministic answer of record.

Assembled in Python from the computed result, never generated. Every
sentence here states the figure, the period (or snapshot), the scope, the
unit and the exclusions applied, which is PRD C4.2 stated once rather than
hoped for in a prompt. Model prose, when it survives the guard, is framing
laid over this -- the answer is complete and correct without it (C4.6).
"""

from typing import Any

from kestrel.ask.types import MetricResults


def _pct(value: float | None) -> str:
    return "not available" if value is None else f"{value * 100:.1f}%"


def _num(value: float) -> str:
    """Whole numbers without a decimal tail, so a count reads as a count."""
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"


def _inr(value: float) -> str:
    return f"INR {value:,.0f}"


def _exclusions(codes: list[str]) -> str:
    return f" Exclusions applied: {', '.join(codes)}." if codes else ""


def _rows_clause(result: MetricResults, value_of: Any, limit: int | None) -> str:
    """Name the breakdown rows when the question asked for a ranking.

    Without this, "the worst five outlets" would be answered with a
    national headline and a table -- true, but not the answer to the
    question that was asked.
    """
    if not limit or not result.rows:
        return ""
    named = ", ".join(f"{row.label} {value_of(row)}" for row in result.rows[:limit])
    return f" Breakdown: {named}."


def compose(result: MetricResults, limit: int | None = None) -> str:
    metric = result.basis.metric
    if metric == "fill_rate":
        b = result.basis
        return (
            f"Fill rate was {_pct(result.headline)} for {b.period_label} "
            f"({b.scope}, {b.unit.value}): {_num(result.numerator)} of "
            f"{_num(result.denominator)} {b.unit.value} delivered."
            + _exclusions(b.exclusions_applied)
            + _rows_clause(result, lambda r: _pct(r.value), limit)
        )
    if metric == "otif":
        b, h = result.basis, result.headline
        unmeasured = (
            f" {b.unmeasured_count} deliveries could not be measured and are "
            "excluded from the rate."
            if b.unmeasured_count
            else ""
        )
        return (
            f"OTIF was {_pct(h.otif)} for {b.period_label} ({b.scope}): "
            f"{h.otif_count} of {h.due_count} due deliveries arrived both on time "
            f"and in full (on time {_pct(h.on_time_rate)}, in full "
            f"{_pct(h.in_full_rate)}), against a {b.tolerance_minutes}-minute "
            "on-time tolerance."
            + _exclusions(b.exclusions_applied)
            + unmeasured
            + _rows_clause(result, lambda r: _pct(r.otif), limit)
        )
    if metric == "returns":
        b, h = result.basis, result.headline
        return (
            f"Returns ran at {_pct(h.returns_rate)} of dispatched value for "
            f"{b.period_label} ({b.scope}): {_inr(h.credit_note_value_inr)} credited "
            f"against {_inr(h.dispatch_value_inr)} dispatched, of which "
            f"{_inr(h.cold_chain_value_inr)} was cold-chain related. "
            f"{b.pending_count} pending ({_inr(b.pending_value_inr)}) and "
            f"{b.rejected_count} rejected ({_inr(b.rejected_value_inr)}) credit notes "
            "are excluded from the rate."
            + _exclusions(b.exclusions_applied)
            + _rows_clause(result, lambda r: _pct(r.returns_rate), limit)
        )
    if metric == "near_expiry":
        b, h = result.basis, result.headline
        return (
            f"Near-expiry stock was {_pct(h.near_expiry_rate)} of available cases as "
            f"at the {b.snapshot_date} snapshot ({b.scope}, within "
            f"{b.threshold_days} days of expiry): {_num(h.near_expiry_cases)} of "
            f"{_num(h.total_available_cases)} cases, worth "
            f"{_inr(h.near_expiry_value_inr)}. Damaged ({_num(b.damaged_cases)} cases) "
            f"and blocked ({_num(b.blocked_cases)} cases) stock is reported separately "
            "and is not in the rate."
            + _rows_clause(result, lambda r: _pct(r.near_expiry_rate), limit)
        )
    b, h = result.basis, result.headline
    return (
        f"Temperature excursions ran at {_pct(h.excursion_rate)} of chilled deliveries "
        f"for {b.period_label} ({b.scope}): {h.excursion_count} excursions across "
        f"{h.chilled_count} chilled deliveries."
        + _exclusions(b.exclusions_applied)
        + _rows_clause(result, lambda r: _pct(r.excursion_rate), limit)
    )


def decline(supported: list[str]) -> str:
    """PRD C4.4: decline explicitly, naming what is supported.

    A confidently wrong figure reproduces the exact failure this product
    exists to eliminate, so there is no fallback that tries harder.
    """
    return (
        "I cannot answer that from the measured data. I can answer questions "
        "about: " + "; ".join(supported) + "."
    )
