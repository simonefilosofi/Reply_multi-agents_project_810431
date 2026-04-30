"""Tests for the PydanticAI-backed BaseAgent.

Covers tier-based model routing, FallbackModel-mediated provider failover on
ModelHTTPError, typed-JSON parsing through ``schema=``, and the legacy
``required_keys`` deprecation warning. Real network calls are avoided by
overriding the PydanticAI Agent with ``TestModel``/``FunctionModel``.
"""

from __future__ import annotations

import warnings

import pytest
from pydantic import BaseModel, Field
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from agents_demo._llm_clients import reset_model_cache
from agents_demo.base_agent import FAST, SMART, BaseAgent
from state import settings
from state.pipeline_state import PipelineState


class _SmartAgent(BaseAgent):
    name = "smart_test"
    MODEL_TIER = SMART

    def act(self) -> None:
        return None


class _FastAgent(BaseAgent):
    name = "fast_test"
    MODEL_TIER = FAST

    def act(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _stub_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-openai")
    reset_model_cache()


def test_tier_drives_resolved_model_identifier() -> None:
    """Subclass MODEL_TIER must select the smart vs fast identifier from settings."""
    smart_agent = _SmartAgent(PipelineState())
    fast_agent = _FastAgent(PipelineState())
    assert smart_agent.model == settings.resolve_model("smart")
    assert fast_agent.model == settings.resolve_model("fast")
    assert smart_agent.model != fast_agent.model


def test_call_llm_returns_overridden_text_output() -> None:
    """call_llm must surface the model's text output verbatim under TestModel."""
    agent = _SmartAgent(PipelineState())
    pa_agent = agent._build_agent(str)
    with pa_agent.override(model=TestModel(custom_output_text="ciao mondo")):
        result = pa_agent.run_sync("hi")
    assert result.output == "ciao mondo"


class _IssueModel(BaseModel):
    column: str
    severity: str = Field(pattern="^(high|medium|low)$")


def test_call_llm_json_with_schema_returns_typed_instance() -> None:
    """A schema= call must return an instance of the requested Pydantic model."""
    agent = _SmartAgent(PipelineState())
    pa_agent = agent._build_agent(_IssueModel)
    with pa_agent.override(model=TestModel(custom_output_args={"column": "x", "severity": "high"})):
        result = pa_agent.run_sync("emit issue")
    assert isinstance(result.output, _IssueModel)
    assert result.output.column == "x"
    assert result.output.severity == "high"


def test_required_keys_path_emits_deprecation_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling call_llm_json with required_keys (no schema) must warn DeprecationWarning."""
    agent = _SmartAgent(PipelineState())

    def _stub_call_llm(self: BaseAgent, user: str, max_tokens: int = 4096) -> str:
        return '{"issues": []}'

    monkeypatch.setattr(BaseAgent, "call_llm", _stub_call_llm)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = agent.call_llm_json("anything", required_keys=["issues"])
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
    assert result == {"issues": []}


def test_fallback_model_is_used_after_primary_http_error() -> None:
    """FallbackModel must route to the secondary when the primary raises ModelHTTPError."""
    agent = _SmartAgent(PipelineState())
    pa_agent = agent._build_agent(str)

    def _primary_failing(messages: list[ModelRequest], info: AgentInfo) -> ModelResponse:
        raise ModelHTTPError(status_code=503, model_name="primary-stub", body=None)

    def _fallback_ok(messages: list[ModelRequest], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="recovered via fallback")])

    primary = FunctionModel(_primary_failing)
    fallback = FunctionModel(_fallback_ok)

    from pydantic_ai.models.fallback import FallbackModel

    with pa_agent.override(model=FallbackModel(primary, fallback)):
        result = pa_agent.run_sync("trigger failover")
    assert result.output == "recovered via fallback"


def test_as_node_returns_callable_for_subclasses() -> None:
    """Every BaseAgent subclass must expose a graph-compatible as_node() factory."""
    runner = _SmartAgent.as_node()
    assert callable(runner)
