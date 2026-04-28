"""Pydantic models that carry deliberation outcomes through ``PipelineState``.

The synthesis supervisor, after detecting a contested finding (typically a
column flagged by both ``AnomalyAgent`` as ``outliers`` and ``ConstraintAgent``
as ``domain_negative_values``), invokes a small LangGraph subgraph that asks
the two specialist agents to vote on whether to keep the issue. Each vote is a
typed :class:`Vote`; the aggregate outcome (with the supervisor tie-break when
votes diverge) is recorded as a :class:`DeliberationOutcome` and appended to
``PipelineState.deliberation_log``. The :class:`SupervisorDecision` schema is
the typed I/O contract for the LLM tie-break call.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from state_demo.agent_names import AgentName
from state_demo.issues import Issue

FinalDecision = Literal["keep", "drop", "escalate"]


class Vote(BaseModel):
    """A specialist agent's vote on whether to keep a contested issue."""

    model_config = ConfigDict(extra="forbid")

    agent_name: AgentName
    keep_issue: bool
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)


class SupervisorDecision(BaseModel):
    """Tie-breaking decision returned by the supervisor LLM call."""

    model_config = ConfigDict(extra="forbid")

    final_decision: FinalDecision
    rationale: str


class DeliberationOutcome(BaseModel):
    """The full record of a single deliberation pass on one contested issue."""

    model_config = ConfigDict(extra="forbid")

    contested_issue: Issue
    votes: list[Vote]
    final_decision: FinalDecision
    rationale: str
