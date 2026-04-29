"""Centralised configuration for the NoiPA data-quality pipeline.

Single source of truth for tunable parameters: model identifiers, severity
thresholds, sandbox limits, and pipeline toggles. Every consumer reads from
the ``settings`` singleton exposed in ``state_demo/__init__.py`` (re-exported
here so ``from state_demo.config import settings`` also works).

Environment variables override defaults via pydantic-settings, with ``__`` as
the nested-key delimiter (e.g. ``THRESHOLDS__OUTLIERS__IQR_MULTIPLIER=3.5``).
API keys are wrapped in ``SecretStr`` and never serialised in plain form.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["anthropic", "openai", "google"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
CheckpointBackend = Literal["memory", "sqlite"]
ModelTier = Literal["smart", "fast"]


class ModelSettings(BaseModel):
    """Identifier registry for the four model slots used across agents."""

    model_config = ConfigDict(extra="forbid")

    default_provider: ProviderName = "openai"
    smart_model: str = "openai:gpt-4o-mini"
    fast_model: str = "openai:gpt-4o-mini"
    fallback_smart_model: str = "anthropic:claude-sonnet-4-6"
    fallback_fast_model: str = "anthropic:claude-haiku-4-5-20251001"


class CompletenessThresholds(BaseModel):
    """Missing-value severity bands used by ``compute_completeness``."""

    model_config = ConfigDict(extra="forbid")

    severity_high: float = Field(0.50, ge=0.0, le=1.0)
    severity_medium: float = Field(0.20, ge=0.0, le=1.0)
    severity_low: float = Field(0.05, ge=0.0, le=1.0)


class GenericRateThresholds(BaseModel):
    """Generic rate-based severity bands used by ``_severity_from_rate``."""

    model_config = ConfigDict(extra="forbid")

    severity_high: float = Field(0.20, ge=0.0, le=1.0)
    severity_medium: float = Field(0.05, ge=0.0, le=1.0)


class OutlierThresholds(BaseModel):
    """Tukey-fence outlier detection and remediation safeguards."""

    model_config = ConfigDict(extra="forbid")

    iqr_multiplier: float = Field(3.0, gt=0.0)
    min_observations: int = Field(10, ge=1)
    skewness_abs_max: float = Field(2.0, ge=0.0)
    cap_rate_max: float = Field(0.05, ge=0.0, le=1.0)
    min_unique_for_capping: int = Field(5, ge=2)


class DuplicateThresholds(BaseModel):
    """Duplicate-column detection thresholds."""

    model_config = ConfigDict(extra="forbid")

    jaccard_min_for_drop: float = Field(0.20, ge=0.0, le=1.0)
    name_similarity_min: float = Field(0.85, ge=0.0, le=1.0)
    min_substring_len: int = Field(5, ge=1)


class FormatPatternThresholds(BaseModel):
    """Format-pattern violation tolerances."""

    model_config = ConfigDict(extra="forbid")

    null_violation_max_pct: float = Field(0.30, ge=0.0, le=1.0)


class NumericThresholds(BaseModel):
    """Numeric coercion and float-precision tunables."""

    model_config = ConfigDict(extra="forbid")

    whole_number_threshold: float = Field(0.80, ge=0.0, le=1.0)
    float_precision_decimals: int = Field(2, ge=0)
    float_precision_min_pct: float = Field(0.10, ge=0.0, le=1.0)


class DateThresholds(BaseModel):
    """Date parsing acceptance bands."""

    model_config = ConfigDict(extra="forbid")

    parse_min_pct: float = Field(0.70, ge=0.0, le=1.0)
    format_significant_pct: float = Field(0.05, ge=0.0, le=1.0)


class ThresholdSettings(BaseModel):
    """Aggregate of every detector / remediation tunable."""

    model_config = ConfigDict(extra="forbid")

    completeness: CompletenessThresholds = Field(default_factory=CompletenessThresholds)
    generic_rate: GenericRateThresholds = Field(default_factory=GenericRateThresholds)
    outliers: OutlierThresholds = Field(default_factory=OutlierThresholds)
    duplicates: DuplicateThresholds = Field(default_factory=DuplicateThresholds)
    format_pattern: FormatPatternThresholds = Field(default_factory=FormatPatternThresholds)
    numeric: NumericThresholds = Field(default_factory=NumericThresholds)
    dates: DateThresholds = Field(default_factory=DateThresholds)


class CodeValidatorSettings(BaseModel):
    """Bounds for the LLM-generated-fix sandbox (Docker primary)."""

    model_config = ConfigDict(extra="forbid")

    max_retries: int = Field(3, ge=1)
    change_threshold: float = Field(0.20, ge=0.0, le=1.0)
    type_drift_threshold: float = Field(0.10, ge=0.0, le=1.0)
    sandbox_timeout_s: int = Field(10, ge=1)
    docker_image: str = "python:3.12-slim"
    docker_mem_limit: str = "512m"
    docker_cpu_quota: int = Field(50_000, ge=1_000)
    subsample_normal_rows: int = Field(50, ge=1)


class PipelineSettings(BaseModel):
    """Top-level pipeline toggles."""

    model_config = ConfigDict(extra="forbid")

    enable_code_validator: bool = True
    enable_deliberation: bool = True
    log_level: LogLevel = "INFO"
    langgraph_recursion_limit: int = Field(50, ge=10)
    langgraph_checkpoint: CheckpointBackend = "memory"


class Settings(BaseSettings):
    """Top-level Settings. Reads ``.env`` plus environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    model_tier_default: ModelTier = "smart"
    docker_host: str | None = None

    models: ModelSettings = Field(default_factory=ModelSettings)
    thresholds: ThresholdSettings = Field(default_factory=ThresholdSettings)
    code_validator: CodeValidatorSettings = Field(default_factory=CodeValidatorSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)

    def resolve_model(self, tier: ModelTier) -> str:
        """Return the configured identifier for the requested tier."""
        return self.models.smart_model if tier == "smart" else self.models.fast_model

    def resolve_fallback(self, tier: ModelTier) -> str:
        """Return the fallback identifier for the requested tier."""
        return (
            self.models.fallback_smart_model if tier == "smart" else self.models.fallback_fast_model
        )


settings = Settings()
