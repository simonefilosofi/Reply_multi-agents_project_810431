"""Cached PydanticAI Agent factories shared across the agent layer.

Centralises construction of typed PydanticAI Agents bound to the project's
provider failover policy (Anthropic primary -> OpenAI fallback) and the model
identifiers exposed by :class:`state_demo.config.Settings`. Subclasses of
:class:`agents_demo.base_agent.BaseAgent` use these factories to avoid
re-instantiating model adapters on every node invocation.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models.fallback import FallbackModel

from state import settings as default_settings
from state.config import ModelTier, Settings


@lru_cache(maxsize=64)
def _model_for_tier(tier: ModelTier, primary: str, fallback: str) -> FallbackModel:
    return FallbackModel(primary, fallback)


def get_model(tier: ModelTier, settings: Settings | None = None) -> FallbackModel:
    """Return the (cached) FallbackModel adapter for ``tier``."""
    cfg = settings or default_settings
    return _model_for_tier(tier, cfg.resolve_model(tier), cfg.resolve_fallback(tier))


def build_agent(
    tier: ModelTier,
    output_type: type | Any = str,
    instructions: str = "",
    settings: Settings | None = None,
) -> Agent:
    """Construct a PydanticAI Agent for the requested tier and output type."""
    return Agent(
        model=get_model(tier, settings),
        instructions=instructions,
        output_type=output_type,
    )


def reset_model_cache() -> None:
    """Drop cached model adapters. Useful in tests that swap settings."""
    _model_for_tier.cache_clear()
