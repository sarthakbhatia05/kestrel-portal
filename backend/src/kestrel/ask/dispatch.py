"""AskIntent -> the canonical metric implementations.

PRD C4.3: an answer here must come from the same code that serves the
dashboard. So this module builds the same request objects the router
builds and calls the same compute functions; it contains no arithmetic and
no SQL of its own.
"""

import sqlite3
from datetime import date

from kestrel.ask.types import AskGrain, AskIntent, AskMetric, MetricResults
from kestrel.config import get_settings
from kestrel.dependencies import parse_period
from kestrel.metrics import excursions, fill_rate, near_expiry, otif, returns
from kestrel.metrics.types import (
    ExcursionsGrain,
    ExcursionsRequest,
    Grain,
    MetricRequest,
    NearExpiryGrain,
    NearExpiryRequest,
    ReturnsGrain,
    ReturnsRequest,
)


class Unanswerable(Exception):
    """The intent cannot be served as asked. Callers decline (C4.4)."""


_DEFAULT_GRAIN: dict[AskMetric, AskGrain] = {
    AskMetric.FILL_RATE: AskGrain.OUTLET,
    AskMetric.OTIF: AskGrain.OUTLET,
    AskMetric.RETURNS: AskGrain.CATEGORY,
    AskMetric.NEAR_EXPIRY: AskGrain.CATEGORY,
    AskMetric.EXCURSIONS: AskGrain.MONTH,
}

_LEGAL_GRAINS: dict[AskMetric, set[AskGrain]] = {
    AskMetric.FILL_RATE: {AskGrain.REGION, AskGrain.WAREHOUSE, AskGrain.ROUTE, AskGrain.OUTLET},
    AskMetric.OTIF: {AskGrain.REGION, AskGrain.WAREHOUSE, AskGrain.ROUTE, AskGrain.OUTLET},
    AskMetric.RETURNS: {AskGrain.CATEGORY, AskGrain.REASON, AskGrain.REGION},
    AskMetric.NEAR_EXPIRY: {AskGrain.WAREHOUSE, AskGrain.CATEGORY},
    AskMetric.EXCURSIONS: {AskGrain.MONTH, AskGrain.ROUTE, AskGrain.WAREHOUSE},
}


def resolve_grain(intent: AskIntent) -> AskGrain:
    """The grain to break down by, or Unanswerable.

    A grain the metric does not support is not quietly swapped for one that
    it does: "returns by outlet" is a different question from "returns by
    category", and answering the second while being asked the first is the
    failure C4.4 exists to prevent.
    """
    if intent.metric is AskMetric.UNSUPPORTED:
        raise Unanswerable("No metric was resolved.")
    if intent.grain is None:
        return _DEFAULT_GRAIN[intent.metric]
    if intent.grain not in _LEGAL_GRAINS[intent.metric]:
        raise Unanswerable(
            f"{intent.metric.value} cannot be broken down by {intent.grain.value}."
        )
    return intent.grain


def run(conn: sqlite3.Connection, intent: AskIntent) -> MetricResults:
    grain = resolve_grain(intent)
    settings = get_settings()

    if intent.metric is AskMetric.NEAR_EXPIRY:
        # Inventory is as-at a weekly snapshot, not a period (PRD 5.5), so
        # the intent's period is deliberately unused here.
        latest = near_expiry.latest_snapshot_date(conn)
        if latest is None:
            raise Unanswerable("No inventory snapshots are present.")
        return near_expiry.compute(
            conn,
            NearExpiryRequest(
                grain=NearExpiryGrain(grain.value),
                snapshot_date=date.fromisoformat(latest),
                threshold_days=settings.near_expiry_days,
                region_id=intent.region_id,
                ascending=intent.ascending,
                limit=intent.limit,
                q=intent.q,
            ),
        )

    period = parse_period(intent.period, conn)
    common = {
        "period_start": period.start,
        "period_end": period.end,
        "period_label": period.label,
        "region_id": intent.region_id,
        "include_excluded": intent.include_excluded,
        "ascending": intent.ascending,
        "limit": intent.limit,
        "q": intent.q,
    }

    if intent.metric is AskMetric.FILL_RATE:
        return fill_rate.compute(
            conn, MetricRequest(grain=Grain(grain.value), unit=intent.unit, **common)
        )
    if intent.metric is AskMetric.OTIF:
        return otif.compute(
            conn,
            MetricRequest(
                grain=Grain(grain.value),
                tolerance_minutes=settings.on_time_tolerance_minutes,
                **common,
            ),
        )
    if intent.metric is AskMetric.RETURNS:
        return returns.compute(conn, ReturnsRequest(grain=ReturnsGrain(grain.value), **common))
    return excursions.compute(
        conn, ExcursionsRequest(grain=ExcursionsGrain(grain.value), **common)
    )
