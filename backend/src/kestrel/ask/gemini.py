"""The only module that talks to a language model.

Every other module in this package takes a client as an argument, so the
whole ask pipeline is testable without a network call, and the product
degrades cleanly when no key is configured (PRD C4.6): `get_client`
returns None and the ask surface reports itself unavailable while every
dashboard figure keeps working.
"""

import json
import logging
from typing import Any, Protocol

from pydantic import BaseModel

from kestrel.config import get_settings

logger = logging.getLogger(__name__)


class LanguageUnavailable(Exception):
    """The model could not be reached.

    Distinct from a question the product does not support: a decline says
    "this data cannot answer that", which is a claim about the data. If
    the network is down, that claim is false and must not be made.
    """


class LanguageModel(Protocol):
    """What the resolver and narrator need."""

    def generate_json(
        self, *, system: str, prompt: str, schema: type[BaseModel]
    ) -> dict[str, Any]: ...

    def generate_text(self, *, system: str, prompt: str) -> str: ...


class GeminiClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._sdk: Any = None

    def _client(self) -> Any:
        """The SDK client, built once and held.

        Held deliberately rather than built per call: the client owns an
        httpx transport that it closes when it is collected, and a
        temporary built inline can be collected while the request it
        started is still in flight ("Cannot send a request, as the client
        has been closed").
        """
        if self._sdk is None:
            # Imported lazily so the package -- and every test in this
            # suite -- loads without the SDK installed.
            from google import genai

            self._sdk = genai.Client(api_key=self._api_key)
        return self._sdk

    def _config(self, system: str, **extra: Any) -> Any:
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=system,
            # Deterministic decoding: the same question should resolve to
            # the same request twice running.
            temperature=0.0,
            **extra,
        )

    def generate_json(
        self, *, system: str, prompt: str, schema: type[BaseModel]
    ) -> dict[str, Any]:
        response = self._client().models.generate_content(
            model=self._model,
            contents=prompt,
            config=self._config(
                system,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        return json.loads(response.text)

    def generate_text(self, *, system: str, prompt: str) -> str:
        response = self._client().models.generate_content(
            model=self._model,
            contents=prompt,
            config=self._config(system),
        )
        return (response.text or "").strip()


def get_client() -> LanguageModel | None:
    """A client, or None when no key is configured."""
    settings = get_settings()
    if not settings.gemini_api_key:
        return None
    return GeminiClient(settings.gemini_api_key, settings.gemini_model)
