import pytest

from app.models import INVOICE, RECEIPT
from app.providers.base import SYSTEM_PROMPT, ProviderError
from app.providers.mock import MockProvider
from app.providers.openai import OpenAIProvider
from tests.conftest import sample_source
from tests.fakes import Recorder, api_error, json_response, openai_client, openai_response


async def test_extracts_a_pdf_with_the_responses_api():
    src = sample_source("02-cedar-pine-packaging.pdf")
    data = await MockProvider().extract(src, INVOICE)
    rec = Recorder(json_response(openai_response(data)))
    provider = OpenAIProvider(openai_client(rec), model="test-model")

    out = await provider.extract(src, INVOICE)

    assert out["vendor_name"]["value"] == "Cedar & Pine Packaging Co."
    assert [t["kind"] for t in out["taxes"]] == ["GST", "PST"]
    assert rec.requests[-1].url.path.endswith("/responses")
    body = rec.body
    assert body["model"] == "test-model"
    assert body["instructions"] == SYSTEM_PROMPT
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    file_part, text_part = body["input"][0]["content"]
    assert file_part["type"] == "input_file"
    assert file_part["file_data"].startswith("data:application/pdf;base64,")
    assert text_part["type"] == "input_text"


async def test_images_are_sent_as_input_image():
    src = sample_source("07-harbour-street-hardware-photo.jpg")
    data = await MockProvider().extract(src, RECEIPT)
    rec = Recorder(json_response(openai_response(data)))
    provider = OpenAIProvider(openai_client(rec), model="test-model")
    await provider.extract(src, RECEIPT)
    part = rec.body["input"][0]["content"][0]
    assert part["type"] == "input_image"
    assert part["image_url"].startswith("data:image/jpeg;base64,")


def test_model_is_required():
    with pytest.raises(ValueError):
        OpenAIProvider(openai_client(Recorder(json_response({}))), model="")


async def test_refusal_is_not_retried_in_demo_mode():
    rec = Recorder(json_response(openai_response(None, refusal="I can't help with that.")))
    provider = OpenAIProvider(openai_client(rec), model="test-model")
    with pytest.raises(ProviderError) as err:
        await provider.extract(sample_source("01-northpeak-office-supply.pdf"), INVOICE)
    assert err.value.code == "refused"
    assert not err.value.fallback_ok


async def test_classify():
    rec = Recorder(json_response(openai_response({"document_type": "invoice"})))
    provider = OpenAIProvider(openai_client(rec), model="test-model")
    assert await provider.classify(sample_source("01-northpeak-office-supply.pdf")) == "invoice"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "provider_auth"),
        (429, "provider_busy"),
        (500, "provider_error"),
        (400, "provider_rejected"),
    ],
)
async def test_api_errors_become_provider_errors(status, code):
    rec = Recorder(api_error(status, "error"))
    provider = OpenAIProvider(openai_client(rec), model="test-model")
    with pytest.raises(ProviderError) as err:
        await provider.extract(sample_source("01-northpeak-office-supply.pdf"), INVOICE)
    assert err.value.code == code
