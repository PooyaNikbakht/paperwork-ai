import base64

import pytest

from app.models import INVOICE, RECEIPT
from app.providers.anthropic import FALLBACK_BETA, AnthropicProvider, supports_refusal_fallback
from app.providers.base import SYSTEM_PROMPT, ProviderError
from app.providers.mock import MockProvider
from tests.conftest import sample_source
from tests.fakes import Recorder, anthropic_client, api_error, claude_message, json_response


async def invoice_output():
    """A realistic structured output: what demo mode produces for the Northpeak invoice."""
    return await MockProvider().extract(sample_source("01-northpeak-office-supply.pdf"), INVOICE)


async def test_extracts_a_pdf_with_structured_outputs():
    data = await invoice_output()
    rec = Recorder(json_response(claude_message(data)))
    provider = AnthropicProvider(anthropic_client(rec), model="claude-opus-5-5", effort="medium")

    out = await provider.extract(sample_source("01-northpeak-office-supply.pdf"), INVOICE)

    assert out["vendor_name"]["value"] == "Northpeak Office Supply Ltd."
    assert out["total"]["value"] == 1014.14
    assert len(out["line_items"]) == 5

    body = rec.body
    assert body["model"] == "claude-opus-5-5"
    assert body["system"] == SYSTEM_PROMPT
    # Effort and the JSON schema travel together in output_config.
    assert body["output_config"]["effort"] == "medium"
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert "line_items" in fmt["schema"]["properties"]
    # Not allowed on this model family: sampling params, thinking config, forced tools, prefill.
    for key in ("temperature", "top_p", "top_k", "thinking", "tool_choice", "tools"):
        assert key not in body
    assert [m["role"] for m in body["messages"]] == ["user"]
    doc_block, text_block = body["messages"][0]["content"]
    assert doc_block["type"] == "document"
    assert doc_block["source"]["type"] == "base64"
    assert doc_block["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(doc_block["source"]["data"]).startswith(b"%PDF-")
    assert text_block["type"] == "text" and "vendor_name" in text_block["text"]
    # Server-side refusal fallback is on for Opus.
    assert body["fallbacks"] == "default"
    assert FALLBACK_BETA in rec.requests[-1].headers["anthropic-beta"]


async def test_images_go_in_as_image_blocks_and_haiku_has_no_fallback():
    src = sample_source("07-harbour-street-hardware-photo.jpg")
    data = await MockProvider().extract(src, RECEIPT)
    rec = Recorder(json_response(claude_message(data, model="claude-haiku-5-5")))
    provider = AnthropicProvider(anthropic_client(rec), model="claude-haiku-5-5")

    out = await provider.extract(src, RECEIPT)

    assert out["merchant_name"]["value"] == "Harbour Street Hardware"
    block = rec.body["messages"][0]["content"][0]
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/jpeg"
    assert "fallbacks" not in rec.body
    assert "anthropic-beta" not in rec.requests[-1].headers


def test_fallback_support_by_model():
    assert supports_refusal_fallback("claude-opus-5-5")
    assert not supports_refusal_fallback("claude-haiku-5-5")


async def test_fallback_block_is_ignored():
    data = await invoice_output()
    rec = Recorder(json_response(claude_message(data, fallback_block=True)))
    provider = AnthropicProvider(anthropic_client(rec), model="claude-opus-5-5")
    out = await provider.extract(sample_source("01-northpeak-office-supply.pdf"), INVOICE)
    assert out["invoice_number"]["value"] == "NP-24817"


async def test_classify_uses_low_effort():
    rec = Recorder(json_response(claude_message({"document_type": "receipt"})))
    provider = AnthropicProvider(anthropic_client(rec), model="claude-opus-5-5")
    assert await provider.classify(sample_source("08-greenleaf-market-receipt.pdf")) == "receipt"
    assert rec.body["output_config"]["effort"] == "low"
    rec2 = Recorder(json_response(claude_message({"document_type": "form"})))
    provider = AnthropicProvider(anthropic_client(rec2), model="claude-opus-5-5")
    assert await provider.classify(sample_source("12-catering-order-form.pdf")) == "custom"


async def test_refusal_raises_without_fallback_to_mock():
    rec = Recorder(json_response(claude_message(None, stop_reason="refusal")))
    provider = AnthropicProvider(anthropic_client(rec), model="claude-opus-5-5")
    with pytest.raises(ProviderError) as err:
        await provider.extract(sample_source("01-northpeak-office-supply.pdf"), INVOICE)
    assert err.value.code == "refused"
    assert not err.value.fallback_ok


async def test_max_tokens_is_reported():
    rec = Recorder(json_response(claude_message(None, stop_reason="max_tokens")))
    provider = AnthropicProvider(anthropic_client(rec), model="claude-opus-5-5")
    with pytest.raises(ProviderError) as err:
        await provider.extract(sample_source("01-northpeak-office-supply.pdf"), INVOICE)
    assert err.value.code == "too_long"


async def test_schema_mismatch_is_a_provider_error():
    rec = Recorder(json_response(claude_message({"unexpected": True})))
    provider = AnthropicProvider(anthropic_client(rec), model="claude-opus-5-5")
    with pytest.raises(ProviderError) as err:
        await provider.extract(sample_source("01-northpeak-office-supply.pdf"), INVOICE)
    assert err.value.code == "provider_error"
    assert err.value.fallback_ok


@pytest.mark.parametrize(
    ("status", "error_type", "code", "fallback_ok"),
    [
        (401, "authentication_error", "provider_auth", True),
        (429, "rate_limit_error", "provider_busy", True),
        (529, "overloaded_error", "provider_error", True),
        (400, "invalid_request_error", "provider_rejected", False),
    ],
)
async def test_api_errors_become_provider_errors(status, error_type, code, fallback_ok):
    rec = Recorder(api_error(status, error_type))
    provider = AnthropicProvider(anthropic_client(rec), model="claude-opus-5-5")
    with pytest.raises(ProviderError) as err:
        await provider.extract(sample_source("01-northpeak-office-supply.pdf"), INVOICE)
    assert err.value.code == code
    assert err.value.fallback_ok is fallback_ok
