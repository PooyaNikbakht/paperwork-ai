"""Application settings, read from environment variables (and an optional .env file)."""

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["anthropic", "openai", "mock"]

BACKEND_DIR = Path(__file__).resolve().parent.parent
SAMPLE_DIR = BACKEND_DIR / "sample"

# Values applied when PUBLIC_DEMO=true, unless the variable is set explicitly.
PUBLIC_DEMO_PRESET: dict[str, Any] = {
    "max_upload_mb": 10,
    "max_pages": 10,
    "max_files_per_batch": 15,
    "batches_per_ip_per_hour": 20,
    "live_docs_per_ip_per_hour": 20,
    "live_docs_per_day": 200,
    "data_ttl_seconds": 3600,
    "sample_provider": "mock",
    "dedupe_across_batches": False,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Provider selection. Empty means: pick by available key, else mock.
    llm_provider: Literal["anthropic", "openai", "offline", "mock", ""] = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    anthropic_max_tokens: int = 16000
    openai_api_key: str = ""
    openai_model: str = ""
    provider_timeout_seconds: float = 180.0

    # HTTP
    cors_origins: str = "http://localhost:3040"
    trust_proxy_headers: bool = False

    # Storage
    data_dir: Path = BACKEND_DIR / "data"
    # 0 keeps batches until they are deleted by hand.
    data_ttl_seconds: int = 0
    cleanup_interval_seconds: int = 300

    # Upload limits
    max_upload_mb: int = 20
    max_pages: int = 30
    max_files_per_batch: int = 50

    # Extraction
    extraction_concurrency: int = 3
    # "mock" runs the sample batch in demo mode even when a live provider is configured.
    sample_provider: Literal["active", "mock"] = "active"
    # Look for duplicates in approved documents from other batches too.
    dedupe_across_batches: bool = True
    low_confidence: float = 0.7

    # Abuse and cost controls (0 means no cap)
    batches_per_ip_per_hour: int = 0
    live_docs_per_ip_per_hour: int = 0
    live_docs_per_day: int = 0
    fallback_to_mock: bool = True

    # Demo mode pacing, so statuses visibly move through the pipeline.
    mock_delay_seconds: float = 0.9

    public_demo: bool = Field(default=False)

    @model_validator(mode="after")
    def _apply_public_preset(self) -> Self:
        if self.public_demo:
            for name, value in PUBLIC_DEMO_PRESET.items():
                if name not in self.model_fields_set:
                    setattr(self, name, value)
        return self

    @property
    def provider(self) -> ProviderName:
        """The active provider, following the shared rules in STANDARDS.md."""
        if self.llm_provider in ("offline", "mock"):
            return "mock"
        if self.llm_provider in ("anthropic", "openai"):
            return self.llm_provider
        if self.anthropic_api_key:
            return "anthropic"
        if self.openai_api_key:
            return "openai"
        return "mock"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
