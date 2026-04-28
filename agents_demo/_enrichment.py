"""Typed LLM enrichment helper shared by every Layer-1 detector agent.

``EnrichmentResponse`` wraps a ``list[Issue]`` so PydanticAI validates each LLM
suggestion against the discriminated union; malformed entries are dropped at the
type-system boundary instead of slipping into ``state.<x>_report``. The
``enrich_with_llm`` helper assembles the per-agent prompt that
``BaseAgent.llm_enrich_issues`` previously built inline, calls the agent's typed
LLM transport, and returns a deduplicated ``list[Issue]`` that always preserves
the deterministic findings even when the LLM is unavailable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, ValidationError

from state_demo.constants import ISSUE_TYPES
from state_demo.helpers import non_empty_values
from state_demo.issues import ISSUE_ADAPTER, Issue

if TYPE_CHECKING:
    from agents_demo.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class EnrichmentResponse(BaseModel):
    """Typed wrapper for LLM enrichment output.

    PydanticAI parses the LLM response against ``list[Issue]`` (the discriminated
    union), so any suggestion missing a required field for its declared type is
    rejected by Pydantic before reaching the agent's report.
    """

    model_config = ConfigDict(extra="forbid")

    issues: list[Issue]


def enrich_with_llm(
    agent: BaseAgent,
    issues: list[Issue],
    df: pd.DataFrame,
    allowed_types: set[str],
) -> list[Issue]:
    """Enrich deterministic findings with LLM-suggested issues, typed end-to-end.

    Behaviour mirrors the legacy ``BaseAgent.llm_enrich_issues`` but operates on
    ``Issue`` instances throughout:

    * deterministic ``issues`` are always preserved;
    * the LLM prompt advertises the allowed types and a sample of column values;
    * the response is validated against ``EnrichmentResponse`` so malformed
      issues are dropped at the schema boundary;
    * issues whose column is not in ``df.columns`` or whose ``type`` is outside
      ``allowed_types`` are filtered out as a defence-in-depth check;
    * de-duplication is by ``(type, column)`` with the LLM-enriched copy winning
      so its richer ``detail`` text replaces the deterministic one.

    Returns the merged list. On any failure, the deterministic ``issues`` are
    returned unchanged and the failure is logged on the agent.
    """
    if not issues:
        return list(issues)

    flagged_cols = {i.column for i in issues if i.column}
    unflagged = [c for c in df.columns if c not in flagged_cols][:5]
    sample_cols = list(flagged_cols) + unflagged

    col_samples: dict[str, dict[str, Any]] = {}
    for col in sample_cols:
        if col not in df.columns:
            continue
        nev = non_empty_values(df[col])
        if len(nev) == 0:
            sample = []
        else:
            sample = list(nev.sample(min(20, len(nev)), random_state=42).astype(str))
        col_samples[col] = {"dtype": str(df[col].dtype), "sample": sample}

    findings_text = "\n".join(
        f"- [{i.severity.upper()}] type={i.type} | column='{i.column}' | {i.detail}" for i in issues
    )
    types_text = "\n".join(f"  {t}: {ISSUE_TYPES.get(t, '')}" for t in sorted(allowed_types))
    samples_text = "\n".join(
        f"  '{col}' (dtype={info['dtype']}): {info['sample']}" for col, info in col_samples.items()
    )

    user = (
        f"Dataset domain: {agent.state.dataset_fingerprint.get('domain', 'unknown')}\n\n"
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
        '6. Return JSON of the form {"issues": [...]} where each issue has '
        '"type", "column", "detail", "severity" plus any type-specific fields.'
    )

    try:
        result = agent.call_llm_json(user, max_tokens=2048, schema=EnrichmentResponse)
    except Exception as exc:
        agent.log(
            "error",
            f"LLM enrichment failed, keeping deterministic issues: {exc}",
        )
        return list(issues)

    enriched_raw = _coerce_issue_list(result, agent_name=agent.name)
    valid_enriched: list[Issue] = []
    for candidate in enriched_raw:
        if candidate.type not in allowed_types:
            continue
        if candidate.column not in df.columns:
            continue
        if not candidate.detail.strip():
            continue
        if candidate.source is None:
            candidate = candidate.model_copy(update={"source": agent.name})
        valid_enriched.append(candidate)

    enriched_keys = {(i.type, i.column) for i in valid_enriched}
    merged: list[Issue] = list(valid_enriched)
    for issue in issues:
        key = (issue.type, issue.column)
        if key not in enriched_keys:
            merged.append(issue)

    new_count = len(merged) - len(issues)
    agent.log(
        "act",
        f"LLM enrichment: {len(issues)} deterministic -> {len(merged)} issues ({new_count:+d} new)",
    )
    return merged


def _coerce_issue_list(result: Any, *, agent_name: str) -> list[Issue]:
    """Best-effort coercion of an enrichment LLM response into a list[Issue]."""
    if isinstance(result, EnrichmentResponse):
        return list(result.issues)
    if isinstance(result, dict):
        try:
            return list(EnrichmentResponse.model_validate(result).issues)
        except ValidationError as exc:
            logger.warning(
                "enrich_with_llm[%s]: response failed EnrichmentResponse validation: %s",
                agent_name,
                exc,
            )
            return _validate_each(result.get("issues", []), agent_name=agent_name)
    if isinstance(result, list):
        return _validate_each(result, agent_name=agent_name)
    logger.warning(
        "enrich_with_llm[%s]: unexpected response type %s",
        agent_name,
        type(result).__name__,
    )
    return []


def _validate_each(items: Any, *, agent_name: str) -> list[Issue]:
    if not isinstance(items, list):
        return []
    out: list[Issue] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        try:
            out.append(ISSUE_ADAPTER.validate_python(entry))
        except ValidationError as exc:
            logger.warning(
                "enrich_with_llm[%s]: dropping invalid issue type=%r column=%r: %s",
                agent_name,
                entry.get("type"),
                entry.get("column"),
                exc,
            )
    return out
