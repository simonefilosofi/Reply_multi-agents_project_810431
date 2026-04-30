"""Common contract every remediation strategy must satisfy.

Each strategy declares the set of typed-issue ``type`` values it consumes
and exposes an ``apply(df, issues_by_type, fp, agent)`` method that mutates
``df`` in place, writes one or more entries to ``agent.state.fix_log`` via
``agent.log_fix``, and may consult / mutate the dataset fingerprint passed
through ``fp``. The :class:`RemediationStrategy` Protocol exists so the
``RemediationAgent`` can iterate ``STRATEGY_ORDER`` (defined in
``__init__.py``) without importing each strategy individually.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

import pandas as pd

from state.issues import Issue

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


@runtime_checkable
class RemediationStrategy(Protocol):
    """Structural contract every strategy in ``STRATEGY_ORDER`` honours."""

    name: ClassVar[str]
    applies_to: ClassVar[frozenset[str]]

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None: ...
