"""BaseAgent rewritten on PydanticAI for typed LLM I/O.

Preserves the Think-Act-Observe-Reply contract that every subclass relies on
while routing every LLM call through PydanticAI's typed Agent. Provider
failover (Anthropic primary -> OpenAI secondary) is delegated to PydanticAI's
FallbackModel; per-tier model identifiers come from state_demo.config.Settings.

Each subclass also exposes a classmethod as_node() that the LangGraph
compiler in agents_demo._graph turns into a node function with parallel-safe
delta semantics for the agent_log / cross_agent_insights list fields.
"""

from __future__ import annotations

import json
import logging
import warnings
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError

from agents_demo._llm_clients import build_agent
from state_demo import settings
from state_demo.config import ModelTier
from state_demo.issues import Issue
from state_demo.pipeline_state import PipelineState

logger = logging.getLogger(__name__)

_T = TypeVar("_T", bound=BaseModel)

SMART: ModelTier = "smart"
FAST: ModelTier = "fast"


class BaseAgent:
    name: str = "base"
    MODEL_TIER: ModelTier = "smart"
    INSTRUCTION: str = ""
    NODE_PROMPT: str = ""

    def __init__(self, state: PipelineState) -> None:
        self.state = state
        self.prompt: str = ""
        self.model: str = settings.resolve_model(self.MODEL_TIER)

    def run(self, prompt: str = "") -> None:
        self.prompt = prompt
        self.think()
        self.act()
        self.observe()
        self.reply()

    def think(self) -> None:
        return None

    def act(self) -> None:
        raise NotImplementedError

    def observe(self) -> None:
        return None

    def reply(self) -> None:
        return None

    def log(self, phase: str, message: str) -> None:
        self.state.agent_log.append(
            {
                "agent": self.name,
                "phase": phase,
                "message": message,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def _build_agent(self, output_type: Any) -> Agent:
        return build_agent(
            tier=self.MODEL_TIER,
            output_type=output_type,
            instructions=self.INSTRUCTION,
            settings=settings,
        )

    def call_llm(self, user: str, max_tokens: int = 4096) -> str:
        agent = self._build_agent(str)
        try:
            result = agent.run_sync(user, model_settings={"max_tokens": max_tokens})
        except ModelHTTPError as exc:
            logger.warning("LLM call failed for agent=%s: %s", self.name, exc)
            raise
        return result.output

    def call_llm_json(
        self,
        user: str,
        max_tokens: int = 4096,
        required_keys: list[str] | None = None,
        schema: type[_T] | None = None,
    ) -> Any:
        if schema is not None:
            agent = self._build_agent(schema)
            try:
                result = agent.run_sync(user, model_settings={"max_tokens": max_tokens})
            except ModelHTTPError as exc:
                logger.warning("Typed LLM call failed for agent=%s: %s", self.name, exc)
                raise
            return result.output
        if required_keys is not None:
            warnings.warn(
                "call_llm_json(required_keys=...) is deprecated; pass schema=... "
                "(a Pydantic BaseModel subclass) instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        raw = self.call_llm(user, max_tokens).strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()
        start_candidates = [i for i in (raw.find(c) for c in "{[") if i != -1]
        start = min(start_candidates) if start_candidates else 0
        end = max(raw.rfind("}"), raw.rfind("]")) + 1
        result = json.loads(raw[start:end])
        if required_keys:
            if not isinstance(result, dict):
                raise ValueError(
                    f"Expected JSON object with keys {required_keys}, got {type(result).__name__}"
                )
            missing = [k for k in required_keys if k not in result]
            if missing:
                raise ValueError(
                    f"LLM JSON response missing required keys: {missing}. "
                    f"Got keys: {list(result.keys())}"
                )
        return result

    def llm_enrich_issues(
        self,
        issues: list[Issue],
        df: Any,
        allowed_types: set[str],
    ) -> list[Issue]:
        """Thin alias to :func:`agents_demo._enrichment.enrich_with_llm`.

        Detector agents call this to run the typed enrichment pass. The base
        method is preserved so subclasses keep a single entry point; the heavy
        lifting now lives in ``_enrichment.py`` so the schema (``EnrichmentResponse``)
        and helpers can be reused outside this class. This shim is removed in
        Step 11 once every caller is fully migrated.
        """
        from agents_demo._enrichment import enrich_with_llm

        return enrich_with_llm(self, issues, df, allowed_types)

    def summarize_issues(
        self,
        issues: list[Issue] | list[dict[str, Any]],
        summary_attr: str,
        noun: str,
    ) -> None:
        issues_text = (
            "\n".join(f"- [{i['severity'].upper()}] {i['column']}: {i['detail']}" for i in issues)
            or f"No {noun} issues found."
        )
        try:
            summary = self.call_llm(
                f"Task: {self.prompt}\n\n"
                f"Summarize these {noun} issues in 2-3 sentences:\n\n{issues_text}"
            ).strip()
        except Exception as exc:
            self.log("error", str(exc))
            summary = f"{len(issues)} {noun} issues found."
        setattr(self.state, summary_attr, summary)
        self.log("reply", summary)

    @classmethod
    def as_node(cls) -> Callable[..., dict[str, Any]]:
        from agents_demo._graph import build_node_runner

        return build_node_runner(cls)
