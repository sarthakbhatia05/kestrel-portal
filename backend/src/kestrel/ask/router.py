"""POST /api/service/ask -- PRD C4.

The endpoint owns no logic beyond sequencing: resolve, dispatch, compose,
narrate, guard. Every decline path returns 200 with `declined` set rather
than an error, because declining is an answer the product is designed to
give (C4.4), not a failure.
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from kestrel.ask import answer, catalogue, dispatch, gemini, narrator, resolver
from kestrel.ask.gemini import LanguageModel, LanguageUnavailable
from kestrel.ask.types import AskAnswer, AskMetric, AskRequest
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


@router.post("", response_model=AskAnswer)
def post_ask(
    payload: AskRequest,
    conn: Annotated[sqlite3.Connection, Depends(get_curated_db)],
    model: Annotated[LanguageModel | None, Depends(get_language_model)],
) -> AskAnswer:
    if model is None:
        raise AppError(
            code="ASK_UNAVAILABLE",
            message="The language capability is not configured. Every dashboard "
            "figure remains available.",
            status=503,
        )

    try:
        intent = resolver.resolve(
            model,
            payload.question,
            catalogue.build(conn),
            window=payload.window,
            scope_region_id=payload.region_id,
        )
    except LanguageUnavailable as exc:
        # Not a decline: the question was never read. Saying the data
        # cannot answer it would be a claim we have not earned.
        raise AppError(
            code="ASK_UNAVAILABLE",
            message="The language model could not be reached. Every dashboard "
            "figure remains available.",
            status=503,
        ) from exc
    declined = AskAnswer(
        question=payload.question,
        answer=answer.decline(resolver.SUPPORTED_METRICS),
        declined=True,
        supported_metrics=resolver.SUPPORTED_METRICS,
    )
    if intent.metric is AskMetric.UNSUPPORTED:
        return declined

    try:
        result = dispatch.run(conn, intent)
    except dispatch.Unanswerable:
        return declined

    text = answer.compose(result, intent.limit)
    return AskAnswer(
        question=payload.question,
        intent=intent,
        answer=text,
        prose=narrator.write(model, payload.question, text, result),
        result=result,
    )
