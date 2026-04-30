"""Tests for CurrencySymbolStrategy (A3 closure): symbol strip + flag-on-no-op."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.currency_symbol import CurrencySymbolStrategy
from state.issues import CurrencySymbolInNumericIssue


def test_currency_symbol_strips_symbols(make_agent) -> None:
    df = pd.DataFrame({"prezzo": ["€ 100", "€ 200", "€ 300"]})
    agent, working = make_agent(df, {})
    issue = CurrencySymbolInNumericIssue(column="prezzo", detail="symbols", severity="medium")
    CurrencySymbolStrategy().apply(working, {"currency_symbol_in_numeric": [issue]}, {}, agent)
    fix_entries = [
        f for f in agent.state.fix_log if f["issue_type"] == "currency_symbol_in_numeric"
    ]
    assert fix_entries and fix_entries[0]["action"] == "auto_fixed"
    assert pd.to_numeric(working["prezzo"], errors="coerce").notna().all()


def test_currency_symbol_flags_when_no_safe_strip(make_agent) -> None:
    df = pd.DataFrame({"label": ["alpha", "beta", "gamma"]})
    agent, working = make_agent(df, {})
    issue = CurrencySymbolInNumericIssue(column="label", detail="false positive", severity="low")
    CurrencySymbolStrategy().apply(working, {"currency_symbol_in_numeric": [issue]}, {}, agent)
    fix_entries = [
        f for f in agent.state.fix_log if f["issue_type"] == "currency_symbol_in_numeric"
    ]
    assert fix_entries and fix_entries[0]["action"] == "flagged_for_review"
