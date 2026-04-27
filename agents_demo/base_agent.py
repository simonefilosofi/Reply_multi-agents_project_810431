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
from state_demo.constants import ISSUE_TYPES
from state_demo.helpers import non_empty_values
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
        issues: list[dict[str, Any]],
        df: Any,
        allowed_types: set[str],
    ) -> list[dict[str, Any]]:
        """Enrich deterministic issue findings with LLM analysis.

        Returns the original list on any failure or empty input. Always
        preserves every original issue regardless of what the LLM emits.
        """
        if not issues:
            return issues

        flagged_cols = {i.get("column", "") for i in issues if i.get("column")}
        unflagged = [c for c in df.columns if c not in flagged_cols][:5]
        sample_cols = list(flagged_cols) + unflagged

        col_samples: dict[str, dict[str, Any]] = {}
        for col in sample_cols:
            if col not in df.columns:
                continue
            nev = non_empty_values(df[col])
            sample = list(nev.sample(min(20, len(nev)), random_state=42).astype(str))
            col_samples[col] = {"dtype": str(df[col].dtype), "sample": sample}

        findings_text = "\n".join(
            f"- [{i['severity'].upper()}] type={i['type']} | "
            f"column='{i.get('column', '')}' | {i['detail']}"
            for i in issues
        )
        types_text = "\n".join(f"  {t}: {ISSUE_TYPES.get(t, '')}" for t in sorted(allowed_types))
        samples_text = "\n".join(
            f"  '{col}' (dtype={info['dtype']}): {info['sample']}"
            for col, info in col_samples.items()
        )

        user = (
            f"Dataset domain: {self.state.dataset_fingerprint.get('domain', 'unknown')}\n\n"
            f"Column samples:\n{samples_text}\n\n"
            f"Confirmed deterministic findings (you MUST include all of these):\n"
            f"{findings_text}\n\n"
            f"Allowed issue types for this agent:\n{types_text}\n\n"
            "Instructions:\n"
            "1. Return ALL confirmed findings above, enriching 'detail' with specific "
            "example values from the samples.\n"
            "2. Add NEW issues you clearly see in the samples.\n"
            "3. Use ONLY the allowed types listed above.\n"
            "4. 'severity' must be exactly 'high', 'medium', or 'low'.\n"
            "5. 'detail' must be specific.\n"
            'Return JSON: {"issues": [{"type": "...", "column": "...", '
            '"detail": "...", "severity": "..."}]}'
        )

        try:
            result = self.call_llm_json(user, max_tokens=2048, required_keys=["issues"])
            enriched = result.get("issues", [])
            valid_enriched = [
                i
                for i in enriched
                if i.get("type") in allowed_types
                and i.get("column", "") in df.columns
                and i.get("severity") in ("high", "medium", "low")
                and i.get("detail", "").strip()
            ]
            enriched_keys = {(i["type"], i.get("column", "")) for i in valid_enriched}
            merged = list(valid_enriched)
            for issue in issues:
                key = (issue["type"], issue.get("column", ""))
                if key not in enriched_keys:
                    merged.append(issue)
            new_count = len(merged) - len(issues)
            self.log(
                "act",
                f"LLM enrichment: {len(issues)} deterministic -> "
                f"{len(merged)} issues ({new_count:+d} new)",
            )
            return merged
        except Exception as exc:
            self.log(
                "error",
                f"LLM enrichment failed, keeping deterministic issues: {exc}",
            )
            return issues

    def summarize_issues(self, issues: list[dict[str, Any]], summary_attr: str, noun: str) -> None:
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
