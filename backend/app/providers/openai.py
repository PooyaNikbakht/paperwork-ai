"""OpenAI adapter: the Responses API with the file sent natively (PDF as `input_file`, photos as
`input_image`) and pydantic structured outputs through `responses.parse`."""

import logging
from typing import Any

import openai
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


def file_part(doc: SourceFile) -> dict[str, Any]:
    if doc.is_pdf:
        return {
            "type": "input_file",
            "filename": doc.filename[:200] or "document.pdf",
            "file_data": f"data:application/pdf;base64,{doc.b64}",
        }
    return {
        "type": "input_image",
        "image_url": f"data:{doc.media_type};base64,{doc.b64}",
        "detail": "high",
    }


class OpenAIProvider:
    name: ProviderName = "openai"

    def __init__(self, client: openai.AsyncOpenAI, *, model: str) -> None:
        if not model:
            raise ValueError("OPENAI_MODEL is required for the OpenAI provider")
        self.client = client
        self.model = model

    def build_input(self, doc: SourceFile, instructions: str) -> list[dict[str, Any]]:
        return [
            {
                "role": "user",
                "content": [file_part(doc), {"type": "input_text", "text": instructions}],
            }
        ]

    async def _parse(
        self, doc: SourceFile, instructions: str, output: type[pydantic.BaseModel]
    ) -> Any:
        try:
            response = await self.client.responses.parse(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=self.build_input(doc, instructions),  # type: ignore[arg-type]
                text_format=output,
            )
        except openai.APIConnectionError as exc:  # includes timeouts
            raise ProviderError("provider_unavailable", "Couldn't reach OpenAI.") from exc
        except openai.RateLimitError as exc:
            raise ProviderError("provider_busy", "OpenAI is busy right now.") from exc
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise ProviderError("provider_auth", "The OpenAI API key was rejected.") from exc
        except openai.BadRequestError as exc:
            logger.warning("OpenAI rejected the request: %s", exc.message)
            raise ProviderError(
                "provider_rejected", "OpenAI couldn't read this file.", fallback_ok=False
            ) from exc
        except openai.APIStatusError as exc:
            logger.warning("OpenAI API error %s: %s", exc.status_code, exc.message)
            raise ProviderError("provider_error", "OpenAI returned an error.") from exc
        except pydantic.ValidationError as exc:
            raise ProviderError(
                "provider_error", "OpenAI's answer didn't match the schema."
            ) from exc

        for item in response.output:
            if item.type == "message":
                for part in item.content:
                    if part.type == "refusal":
                        raise ProviderError(
                            "refused",
                            "The model declined to read this document.",
                            fallback_ok=False,
                        )
        if response.status == "incomplete":
            raise ProviderError(
                "too_long", "This document is too long to read in one go.", fallback_ok=False
            )
        if response.output_parsed is None:
            raise ProviderError("provider_error", "OpenAI returned no data.")
        return response.output_parsed

    async def classify(self, doc: SourceFile) -> DocType:
        result = await self._parse(doc, CLASSIFY_INSTRUCTIONS, AIClassification)
        return doc_type_for(result.document_type)

    async def extract(self, doc: SourceFile, spec: DocSpec) -> dict[str, Any]:
        result = await self._parse(doc, extraction_instructions(spec), output_model(spec))
        return result.model_dump()
