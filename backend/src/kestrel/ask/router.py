"""POST /api/service/ask -- PRD C4.

The endpoint owns no logic beyond sequencing: resolve, dispatch, compose,
narrate, guard. Every decline path returns 200 with `declined` set rather
than an error, because declining is an answer the product is designed to
give (C4.4), not a failure.

Two shapes of the same thing. The JSON endpoint answers in one response and
is the fallback; the streaming one emits each measurement of an
investigation as it completes, because six model calls is a long time to
show a spinner and the measurements are worth watching.
"""

import json
import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from kestrel.ask import answer, catalogue, dispatch, gemini, investigate, narrator, resolver
from kestrel.ask.gemini import LanguageModel, LanguageUnavailable
from kestrel.ask.types import AskAnswer, AskIntent, AskMetric, AskMode, AskRequest, StepRecord
from kestrel.dependencies import get_curated_db
from kestrel.exceptions import AppError

router = APIRouter(prefix="/api/service/ask", tags=["ask"])


def get_language_model() -> LanguageModel | None:
    return gemini.get_client()


@router.get("/capability")
def get_capability(
    model: Annotated[LanguageModel | None, Depends(get_language_model)],
) -> dict[str, object]:
    """Whether the language capability is configured.

    PRD C4.6: the frontend asks this so it can hide the ask surface and
    leave every dashboard figure working, rather than offering a box that
    errors on submit.
    """
    return {"available": model is not None, "supported_metrics": resolver.SUPPORTED_METRICS}


def _unavailable() -> AppError:
    return AppError(
        code="ASK_UNAVAILABLE",
        message="The language model could not be reached. Every dashboard "
        "figure remains available.",
        status=503,
    )


def _require_model(model: LanguageModel | None) -> LanguageModel:
    if model is None:
        raise AppError(
            code="ASK_UNAVAILABLE",
            message="The language capability is not configured. Every dashboard "
            "figure remains available.",
            status=503,
        )
    return model


def _decline(question: str) -> AskAnswer:
    return AskAnswer(
        question=question,
        answer=answer.decline(resolver.SUPPORTED_METRICS),
        declined=True,
        supported_metrics=resolver.SUPPORTED_METRICS,
    )


def _resolve(
    model: LanguageModel,
    conn: sqlite3.Connection,
    payload: AskRequest,
) -> tuple[AskIntent, catalogue.Catalogue]:
    """Read the question. Raises rather than declining on an outage.

    Done before any streaming starts, so an unreachable model is still a
    503 rather than an error event inside a 200 that has already begun.
    """
    known = catalogue.build(conn)
    try:
        intent = resolver.resolve(
            model,
            payload.question,
            known,
            window=payload.window,
            scope_region_id=payload.region_id,
        )
    except LanguageUnavailable as exc:
        # Not a decline: the question was never read. Saying the data
        # cannot answer it would be a claim we have not earned.
        raise _unavailable() from exc
    return intent, known


def _lookup(
    model: LanguageModel,
    conn: sqlite3.Connection,
    payload: AskRequest,
    intent: AskIntent,
) -> AskAnswer:
    """One measurement, one answer -- the path the product has always had."""
    # C5.3: the dashboard's period fills a gap the question leaves, the
    # same way its region does. A period named in the question is more
    # specific and wins.
    if intent.period == "latest" and payload.period is not None:
        intent = intent.model_copy(update={"period": payload.period})

    try:
        result = dispatch.run(conn, intent)
    except dispatch.Unanswerable:
        return _decline(payload.question)

    text = answer.compose(result, intent.limit)
    return AskAnswer(
        question=payload.question,
        intent=intent,
        answer=text,
        prose=narrator.write(model, payload.question, text, result),
        result=result,
    )


def _investigated(
    model: LanguageModel,
    conn: sqlite3.Connection,
    payload: AskRequest,
    intent: AskIntent,
    known: catalogue.Catalogue,
) -> AskAnswer:
    """Several measurements, chosen one at a time by the model.

    An investigation that measured nothing declines like any other
    unanswerable question: there is no path from "I could not measure
    that" to a paragraph of prose about it (C4.4).
    """
    try:
        found = investigate.run(
            model,
            conn,
            payload.question,
            known,
            window=payload.window,
            scope_region_id=payload.region_id,
            scope_period=payload.period,
        )
    except LanguageUnavailable as exc:
        raise _unavailable() from exc

    if found.declined:
        return _decline(payload.question).model_copy(update={"steps": found.steps})

    return AskAnswer(
        question=payload.question,
        intent=intent,
        answer=found.answer,
        prose=found.explanation,
        # The last measurement taken is the supporting detail the panel
        # tabulates; the full trail is in `steps` (C4.5).
        result=found.steps[-1].result,
        steps=found.steps,
    )


@router.post("", response_model=AskAnswer)
def post_ask(
    payload: AskRequest,
    conn: Annotated[sqlite3.Connection, Depends(get_curated_db)],
    model: Annotated[LanguageModel | None, Depends(get_language_model)],
) -> AskAnswer:
    resolved = _require_model(model)
    intent, known = _resolve(resolved, conn, payload)

    if intent.metric is AskMetric.UNSUPPORTED:
        return _decline(payload.question)

    if intent.mode is AskMode.INVESTIGATE:
        return _investigated(resolved, conn, payload, intent, known)

    return _lookup(resolved, conn, payload, intent)


def _event(kind: str, body: dict) -> str:
    """One server-sent event.

    The kind rides inside the JSON payload rather than in an SSE `event:`
    line, so the client parses one shape and switches on one field.
    """
    return "data: " + json.dumps({"type": kind, **body}, default=str) + "\n\n"


def _final(
    model: LanguageModel, payload: AskRequest, intent: AskIntent, records: list[StepRecord]
) -> AskAnswer:
    measured = [record for record in records if record.result is not None]
    if not measured:
        return _decline(payload.question).model_copy(update={"steps": records})
    return AskAnswer(
        question=payload.question,
        intent=intent,
        answer="\n\n".join(record.summary for record in measured),
        prose=investigate.conclude(model, payload.question, records),
        result=measured[-1].result,
        steps=records,
    )


@router.post("/stream")
def post_ask_stream(
    payload: AskRequest,
    conn: Annotated[sqlite3.Connection, Depends(get_curated_db)],
    model: Annotated[LanguageModel | None, Depends(get_language_model)],
) -> StreamingResponse:
    """The same answers, with an investigation's steps emitted as they land."""
    resolved = _require_model(model)
    intent, known = _resolve(resolved, conn, payload)

    def stream() -> Iterator[str]:
        if intent.metric is AskMetric.UNSUPPORTED:
            yield _event("answer", _decline(payload.question).model_dump())
            return

        if intent.mode is not AskMode.INVESTIGATE:
            yield _event("answer", _lookup(resolved, conn, payload, intent).model_dump())
            return

        records: list[StepRecord] = []
        try:
            for record in investigate.investigate(
                resolved, conn, payload.question, known,
                window=payload.window,
                scope_region_id=payload.region_id,
                scope_period=payload.period,
            ):
                records.append(record)
                # The step without its rows: the trail is for reading, and
                # the supporting figures ride on the final answer instead.
                yield _event("step", record.model_dump(exclude={"result"}))

            yield _event("answer", _final(resolved, payload, intent, records).model_dump())
        except LanguageUnavailable:
            # The response has already begun, so this cannot become a 503.
            # Say what happened rather than letting the stream stop silently.
            yield _event(
                "error",
                {
                    "message": "The language model became unreachable partway "
                    "through. Every dashboard figure remains available."
                },
            )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        # Proxies buffer by default, which would defeat the point.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
