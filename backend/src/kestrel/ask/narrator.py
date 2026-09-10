"""Optional framing prose over an already-computed answer.

The model here writes no figures of its own: it is handed the finished
deterministic answer and asked to restate it readably. Everything it
returns goes through the numeric guard, and anything that fails is dropped
rather than repaired. The caller renders the deterministic answer either
way, so losing this costs polish and nothing else.
"""

import logging

from kestrel.ask import guard
from kestrel.ask.gemini import LanguageModel
from kestrel.ask.types import MetricResults

logger = logging.getLogger(__name__)

_SYSTEM = """You restate a supply-chain answer in one or two plain sentences
for a manager reading it in a hurry.

Rules, in order of importance:
- Use only numbers that appear verbatim in the answer you are given. Never
  compute, round differently, estimate or infer a figure.
- Do not explain why the number is what it is. The data does not say why.
- Do not repeat the exclusions or the tolerance; they are shown separately.
- No greeting, no preamble, no offer to help further. Two sentences at most.
"""


def write(
    client: LanguageModel,
    question: str,
    answer_text: str,
    result: MetricResults,
) -> str | None:
    """Guarded prose, or None if the model failed or invented a figure."""
    try:
        prose = client.generate_text(
            system=_SYSTEM,
            prompt=f"Question: {question}\n\nComputed answer: {answer_text}",
        )
    except Exception:
        logger.warning("Narration failed; falling back to the computed answer", exc_info=True)
        return None
    if not prose:
        return None
    guarded = guard.apply(prose, result)
    if guarded is None:
        logger.warning("Narration contained a figure absent from the result; dropped")
    return guarded
