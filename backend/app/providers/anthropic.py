"""Claude adapter: the file goes in natively (PDF as a document block, photos as an image block)
and the answer comes back as schema-valid JSON through structured outputs (`messages.parse`).

Citations can't be combined with structured outputs, so each field carries its own verbatim
quote and page, which the app then locates on the page and checks.
"""

import logging
from typing import Any

import anthropic
import pydantic

from app.models import DocSpec, DocType
from app.providers.base import (
    CLASSIFY_INSTRUCTIONS,
    SYSTEM_PROMPT,
    AIClassification,
    ProviderError,
    SourceFile,
    doc_type_for,
    extraction_instructions,
    output_model,
)
from app.settings import ProviderName

logger = logging.getLogger(__name__)

# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
# Claude Haiku 5.5 has no server-side fallback, so it is not listed.
FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-opus-5"})
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def supports_refusal_fallback(model: str) -> bool:
    return model in FALLBACK_MODELS


def file_block(doc: SourceFile) -> dict[str, Any]:
    if doc.is_pdf:
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": doc.b64},
            "title": doc.filename[:200],
        }
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": doc.media_type, "data": doc.b64},
    }


class AnthropicProvider:
    name: ProviderName = "anthropic"

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        *,
        model: str,
        effort: str = "medium",
        max_tokens: int = 16000,
    ) -> None:
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    def build_params(self, doc: SourceFile, instructions: str, effort: str) -> dict[str, Any]:
        # No temperature, top_p, thinking config, tool_choice or prefill: thinking is always on
        # for this model family, and effort is the control. The document goes before the text.
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": [file_block(doc), {"type": "text", "text": instructions}],
                }
            ],
            "output_config": {"effort": effort},
        }

    async def _parse(self, params: dict[str, Any], output: type[pydantic.BaseModel]) -> Any:
        try:
            if supports_refusal_fallback(self.model):
                response = await self.client.beta.messages.parse(
                    **params, output_format=output, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                response = await self.client.messages.parse(**params, output_format=output)
        except anthropic.APIConnectionError as exc:  # includes timeouts
            raise ProviderError("provider_unavailable", "Couldn't reach Claude.") from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("provider_busy", "Claude is busy right now.") from exc
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise ProviderError("provider_auth", "The Claude API key was rejected.") from exc
        except anthropic.BadRequestError as exc:
            logger.warning("Claude rejected the request: %s", exc.message)
            raise ProviderError(
                "provider_rejected", "Claude couldn't read this file.", fallback_ok=False
            ) from exc
        except anthropic.APIStatusError as exc:
            logger.warning("Claude API error %s: %s", exc.status_code, exc.message)
            raise ProviderError("provider_error", "Claude returned an error.") from exc
        except pydantic.ValidationError as exc:
            raise ProviderError(
                "provider_error", "Claude's answer didn't match the schema."
            ) from exc

        if response.stop_reason == "refusal":
            raise ProviderError(
                "refused", "Claude declined to read this document.", fallback_ok=False
            )
        if response.stop_reason == "max_tokens":
            raise ProviderError(
                "too_long", "This document is too long to read in one go.", fallback_ok=False
            )
        if response.parsed_output is None:
            raise ProviderError("provider_error", "Claude returned no data.")
        return response.parsed_output

    async def classify(self, doc: SourceFile) -> DocType:
        params = self.build_params(doc, CLASSIFY_INSTRUCTIONS, "low")
        result = await self._parse(params, AIClassification)
        return doc_type_for(result.document_type)

    async def extract(self, doc: SourceFile, spec: DocSpec) -> dict[str, Any]:
        model = output_model(spec)
        params = self.build_params(doc, extraction_instructions(spec), self.effort)
        result = await self._parse(params, model)
        return result.model_dump()
