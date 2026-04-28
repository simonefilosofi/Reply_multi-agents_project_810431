"""Strategy registry for the remediation layer.

``STRATEGY_ORDER`` is the authoritative execution sequence the
:class:`RemediationAgent` walks; the order encodes:

* B2 invariant: ``PlaceholderStrategy`` -> ``LookupImputationStrategy``
  -> ``MissingValuesStrategy`` (placeholders become NULL, then learned
  src->tgt mappings impute, then median/mode fills the residual).
* A3 invariant: ``CurrencySymbolStrategy`` -> ``CommaDecimalStrategy``
  -> ``MixedTypeStrategy`` (Italian-locale strings parse before numeric
  coercion turns them to NaN).
* Outlier capping precedes ``DerivedRecomputationStrategy`` so additive
  derivatives (profit = revenue - cost) are recomputed against the capped
  base values rather than the raw ones.
* ``DuplicateColumnsStrategy`` precedes ``NamingConventionStrategy`` so the
  original column names recorded by ``DuplicateAgent`` still exist when the
  drop happens.

``DerivedRecomputationStrategy.applies_to`` is intentionally empty: it
consumes the fix log produced by ``OutlierStrategy`` rather than a
detector-emitted issue type, and is invoked unconditionally at the end of
the run.
"""

from __future__ import annotations

from agents_demo.remediation_strategies._base import RemediationStrategy
from agents_demo.remediation_strategies.case_inconsistency import CaseInconsistencyStrategy
from agents_demo.remediation_strategies.comma_decimal import CommaDecimalStrategy
from agents_demo.remediation_strategies.currency_symbol import CurrencySymbolStrategy
from agents_demo.remediation_strategies.derived_recomputation import DerivedRecomputationStrategy
from agents_demo.remediation_strategies.duplicate_columns import DuplicateColumnsStrategy
from agents_demo.remediation_strategies.duplicate_key import DuplicateKeyStrategy
from agents_demo.remediation_strategies.duplicate_rows import DuplicateRowsStrategy
from agents_demo.remediation_strategies.flag_only import FlagOnlyStrategy
from agents_demo.remediation_strategies.float_precision import FloatPrecisionStrategy
from agents_demo.remediation_strategies.format_inconsistency import FormatInconsistencyStrategy
from agents_demo.remediation_strategies.format_pattern import FormatPatternStrategy
from agents_demo.remediation_strategies.fractional_integers import FractionalIntegersStrategy
from agents_demo.remediation_strategies.invalid_dates import InvalidDatesStrategy
from agents_demo.remediation_strategies.lookup_imputation import LookupImputationStrategy
from agents_demo.remediation_strategies.missing_values import MissingValuesStrategy
from agents_demo.remediation_strategies.mixed_type import MixedTypeStrategy
from agents_demo.remediation_strategies.month_column import MonthColumnStrategy
from agents_demo.remediation_strategies.naming_convention import NamingConventionStrategy
from agents_demo.remediation_strategies.outliers import OutlierStrategy
from agents_demo.remediation_strategies.period_format import PeriodFormatStrategy
from agents_demo.remediation_strategies.placeholder import PlaceholderStrategy
from agents_demo.remediation_strategies.year_column import YearColumnStrategy

STRATEGY_ORDER: tuple[RemediationStrategy, ...] = (
    PeriodFormatStrategy(),
    MonthColumnStrategy(),
    YearColumnStrategy(),
    PlaceholderStrategy(),
    CurrencySymbolStrategy(),
    CommaDecimalStrategy(),
    FractionalIntegersStrategy(),
    MixedTypeStrategy(),
    InvalidDatesStrategy(),
    DuplicateRowsStrategy(),
    LookupImputationStrategy(),
    MissingValuesStrategy(),
    OutlierStrategy(),
    FloatPrecisionStrategy(),
    FormatPatternStrategy(),
    FormatInconsistencyStrategy(),
    CaseInconsistencyStrategy(),
    DuplicateColumnsStrategy(),
    NamingConventionStrategy(),
    DuplicateKeyStrategy(),
    FlagOnlyStrategy(),
    DerivedRecomputationStrategy(),
)


__all__ = [
    "STRATEGY_ORDER",
    "CaseInconsistencyStrategy",
    "CommaDecimalStrategy",
    "CurrencySymbolStrategy",
    "DerivedRecomputationStrategy",
    "DuplicateColumnsStrategy",
    "DuplicateKeyStrategy",
    "DuplicateRowsStrategy",
    "FlagOnlyStrategy",
    "FloatPrecisionStrategy",
    "FormatInconsistencyStrategy",
    "FormatPatternStrategy",
    "FractionalIntegersStrategy",
    "InvalidDatesStrategy",
    "LookupImputationStrategy",
    "MissingValuesStrategy",
    "MixedTypeStrategy",
    "MonthColumnStrategy",
    "NamingConventionStrategy",
    "OutlierStrategy",
    "PeriodFormatStrategy",
    "PlaceholderStrategy",
    "RemediationStrategy",
    "YearColumnStrategy",
]
