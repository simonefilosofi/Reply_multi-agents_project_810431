"""Pydantic discriminated union of every issue type the pipeline can produce.

The ``Issue`` alias is an Annotated Union over thirty Pydantic subclasses, one
per entry in ``state_demo.constants.ISSUE_TYPES``. The discriminator field is
``type``. ``parse_issue(d)`` round-trips a legacy dict through
``TypeAdapter(Issue).validate_python`` and returns the strongly typed instance.

The discriminated-union shape is what closes B1 structurally: the
``FormatPatternViolationIssue.pattern`` field is required at the type level, so
the ``pattern`` key cannot silently disappear between detection and
remediation. ``DuplicateColumnsIssue``, ``DateOrderIssue`` and
``DuplicateKeyIssue`` likewise model multi-column issues with explicit fields
instead of the legacy ``"col_a / col_b"`` joined string.

``IssueBase`` exposes ``__getitem__``, ``__contains__`` and ``get`` so existing
consumers that read fields with bracket / ``.get`` syntax continue to work after
the migration in Step 9; downstream agents (synthesis, remediation, report) are
moved off the dict idiom incrementally in Steps 10-13.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from state.agent_names import AgentName

logger = logging.getLogger(__name__)

Severity = Literal["high", "medium", "low"]


class IssueBase(BaseModel):
    """Shared fields for every issue subclass."""

    model_config = ConfigDict(frozen=False, extra="forbid", populate_by_name=True)

    column: str
    detail: str
    severity: Severity
    source: AgentName | None = None
    rows_affected: int | None = None

    def __getitem__(self, key: str) -> Any:
        if key in type(self).model_fields:
            return getattr(self, key)
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in type(self).model_fields

    def get(self, key: str, default: Any = None) -> Any:
        if key in type(self).model_fields:
            return getattr(self, key)
        return default

    def keys(self) -> list[str]:
        return list(type(self).model_fields)


class MixedTypeIssue(IssueBase):
    """Column contains both numeric and non-numeric values."""

    type: Literal["mixed_type"] = "mixed_type"
    numeric_count: int | None = None
    non_numeric_count: int | None = None


class InvalidDatesIssue(IssueBase):
    """Date values that cannot be parsed."""

    type: Literal["invalid_dates"] = "invalid_dates"
    parse_rate: float | None = None
    unparseable_count: int | None = None


class NamingConventionIssue(IssueBase):
    """Column name violates snake_case convention."""

    type: Literal["naming_convention"] = "naming_convention"
    suggested_name: str | None = None


class MissingValuesIssue(IssueBase):
    """Null or empty values in the column."""

    type: Literal["missing_values"] = "missing_values"
    missing_count: int | None = None
    total: int | None = None


class PlaceholderValuesIssue(IssueBase):
    """Sentinel strings (N/A, N.D., unknown...) used instead of NULL."""

    type: Literal["placeholder_values"] = "placeholder_values"
    placeholder_examples: list[str] | None = None
    count: int | None = None


class SparseColumnIssue(IssueBase):
    """Column is mostly empty (>90% missing)."""

    type: Literal["sparse_column"] = "sparse_column"
    missing_pct: float | None = None


class DuplicateRowsIssue(IssueBase):
    """Exact duplicate rows."""

    type: Literal["duplicate_rows"] = "duplicate_rows"
    duplicate_count: int | None = None
    total: int | None = None


class DuplicateColumnsIssue(IssueBase):
    """Two columns with identical or near-identical values."""

    type: Literal["duplicate_columns"] = "duplicate_columns"
    column_a: str
    column_b: str

    @model_validator(mode="before")
    @classmethod
    def _populate_column(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        result = {**data}
        column_value = result.get("column")
        if (
            "column_a" not in result
            and "column_b" not in result
            and isinstance(column_value, str)
            and "/" in column_value
        ):
            parts = [p.strip() for p in column_value.split("/")]
            if len(parts) == 2 and all(parts):
                result["column_a"] = parts[0]
                result["column_b"] = parts[1]
        if "column" not in result and "column_a" in result:
            result["column"] = result["column_a"]
        return result


class DuplicateKeyIssue(IssueBase):
    """Rows sharing a key value but differing elsewhere."""

    type: Literal["duplicate_key"] = "duplicate_key"
    key_columns: tuple[str, ...]

    @model_validator(mode="before")
    @classmethod
    def _populate_column(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        result = {**data}
        column_value = result.get("column")
        if "key_columns" not in result and isinstance(column_value, str) and column_value:
            keys = tuple(c.strip() for c in column_value.split(",") if c.strip())
            if keys:
                result["key_columns"] = keys
        if "column" not in result and "key_columns" in result:
            keys = result["key_columns"]
            if isinstance(keys, list | tuple) and keys:
                result["column"] = str(keys[0])
        return result


class OutliersIssue(IssueBase):
    """Statistical outliers (3 x IQR Tukey outer fence)."""

    type: Literal["outliers"] = "outliers"
    outlier_count: int | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None


class RareCategoriesIssue(IssueBase):
    """Categorical values appearing in <1% of rows."""

    type: Literal["rare_categories"] = "rare_categories"
    rare_examples: list[str] | None = None
    rare_pct: float | None = None


class FormatInconsistencyIssue(IssueBase):
    """Mixed date or string formats within one column."""

    type: Literal["format_inconsistency"] = "format_inconsistency"
    format_examples: list[str] | None = None
    dominant_format: str | None = None


class CaseInconsistencyIssue(IssueBase):
    """Same values in different cases (e.g. RM vs rm)."""

    type: Literal["case_inconsistency"] = "case_inconsistency"
    case_examples: list[str] | None = None


class DateOrderIssue(IssueBase):
    """End date earlier than start date in the same row."""

    type: Literal["date_order"] = "date_order"
    column_a: str
    column_b: str
    violations: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _populate_column(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        result = {**data}
        column_value = result.get("column")
        if (
            "column_a" not in result
            and "column_b" not in result
            and isinstance(column_value, str)
            and "/" in column_value
        ):
            parts = [p.strip() for p in column_value.split("/")]
            if len(parts) == 2 and all(parts):
                result["column_a"] = parts[0]
                result["column_b"] = parts[1]
        if "column" not in result and "column_a" in result:
            result["column"] = result["column_a"]
        return result


class ConditionalCompletenessIssue(IssueBase):
    """Column B missing when column A has a value."""

    type: Literal["conditional_completeness"] = "conditional_completeness"
    dependency_column: str | None = None
    missing_when_present: int | None = None


class LookupImputabilityIssue(IssueBase):
    """Missing values can be inferred from a related column via a learned mapping."""

    type: Literal["lookup_imputability"] = "lookup_imputability"
    mapping_source: str
    coverage: float | None = None
    n_imputable: int | None = None


class FloatPrecisionNoiseIssue(IssueBase):
    """Floating-point noise (1.000000001 instead of 1.0)."""

    type: Literal["float_precision_noise"] = "float_precision_noise"
    noisy_count: int | None = None
    decimals: int | None = None


class FormatPatternViolationIssue(IssueBase):
    """Values not matching the expected regex pattern."""

    type: Literal["format_pattern_violation"] = "format_pattern_violation"
    pattern: str
    description: str


class CrossColumnMismatchIssue(IssueBase):
    """Two columns that should agree but don't."""

    type: Literal["cross_column_mismatch"] = "cross_column_mismatch"
    other_column: str | None = None
    mismatch_count: int | None = None


class DomainNegativeValuesIssue(IssueBase):
    """Negative values in a non-negative column."""

    type: Literal["domain_negative_values"] = "domain_negative_values"
    negative_count: int | None = None


class CurrencySymbolInNumericIssue(IssueBase):
    """Currency symbols present in a numeric column."""

    type: Literal["currency_symbol_in_numeric"] = "currency_symbol_in_numeric"
    currency_examples: list[str] | None = None
    count: int | None = None


class CommaDecimalFormatIssue(IssueBase):
    """Comma used as decimal separator instead of dot."""

    type: Literal["comma_decimal_format"] = "comma_decimal_format"
    count: int | None = None


class NdPlaceholderInNumericIssue(IssueBase):
    """N.D. / N.A. placeholders in a numeric column."""

    type: Literal["nd_placeholder_in_numeric"] = "nd_placeholder_in_numeric"
    placeholder_examples: list[str] | None = None
    count: int | None = None


class FractionalIntegersIssue(IssueBase):
    """Non-trivial fractional parts in an integer column."""

    type: Literal["fractional_integers"] = "fractional_integers"
    fractional_count: int | None = None


class PeriodFormatInconsistencyIssue(IssueBase):
    """Period (YYYYMM) values stored in mixed formats."""

    type: Literal["period_format_inconsistency"] = "period_format_inconsistency"
    format_examples: list[str] | None = None


class MonthFormatInconsistencyIssue(IssueBase):
    """Month values as text names or out-of-range integers."""

    type: Literal["month_format_inconsistency"] = "month_format_inconsistency"
    month_examples: list[str] | None = None


class SpecialMonthCodeIssue(IssueBase):
    """Special codes (0, 13, 99...) used as month values."""

    type: Literal["special_month_code"] = "special_month_code"
    special_codes: list[str] | None = None


class YearFormatInconsistencyIssue(IssueBase):
    """Year values with trailing noise or non-digit chars."""

    type: Literal["year_format_inconsistency"] = "year_format_inconsistency"
    year_examples: list[str] | None = None


class AmbiguousYearFormatIssue(IssueBase):
    """2-digit year values requiring century expansion."""

    type: Literal["ambiguous_year_format"] = "ambiguous_year_format"
    examples: list[str] | None = None


class InvalidYearValueIssue(IssueBase):
    """Year values outside the plausible range [1900-2099]."""

    type: Literal["invalid_year_value"] = "invalid_year_value"
    invalid_examples: list[str] | None = None


_AnyIssue = (
    MixedTypeIssue
    | InvalidDatesIssue
    | NamingConventionIssue
    | MissingValuesIssue
    | PlaceholderValuesIssue
    | SparseColumnIssue
    | DuplicateRowsIssue
    | DuplicateColumnsIssue
    | DuplicateKeyIssue
    | OutliersIssue
    | RareCategoriesIssue
    | FormatInconsistencyIssue
    | CaseInconsistencyIssue
    | DateOrderIssue
    | ConditionalCompletenessIssue
    | LookupImputabilityIssue
    | FloatPrecisionNoiseIssue
    | FormatPatternViolationIssue
    | CrossColumnMismatchIssue
    | DomainNegativeValuesIssue
    | CurrencySymbolInNumericIssue
    | CommaDecimalFormatIssue
    | NdPlaceholderInNumericIssue
    | FractionalIntegersIssue
    | PeriodFormatInconsistencyIssue
    | MonthFormatInconsistencyIssue
    | SpecialMonthCodeIssue
    | YearFormatInconsistencyIssue
    | AmbiguousYearFormatIssue
    | InvalidYearValueIssue
)

Issue = Annotated[_AnyIssue, Field(discriminator="type")]

ISSUE_ADAPTER: TypeAdapter[Issue] = TypeAdapter(Issue)

ISSUE_SUBCLASSES: tuple[type[IssueBase], ...] = (
    MixedTypeIssue,
    InvalidDatesIssue,
    NamingConventionIssue,
    MissingValuesIssue,
    PlaceholderValuesIssue,
    SparseColumnIssue,
    DuplicateRowsIssue,
    DuplicateColumnsIssue,
    DuplicateKeyIssue,
    OutliersIssue,
    RareCategoriesIssue,
    FormatInconsistencyIssue,
    CaseInconsistencyIssue,
    DateOrderIssue,
    ConditionalCompletenessIssue,
    LookupImputabilityIssue,
    FloatPrecisionNoiseIssue,
    FormatPatternViolationIssue,
    CrossColumnMismatchIssue,
    DomainNegativeValuesIssue,
    CurrencySymbolInNumericIssue,
    CommaDecimalFormatIssue,
    NdPlaceholderInNumericIssue,
    FractionalIntegersIssue,
    PeriodFormatInconsistencyIssue,
    MonthFormatInconsistencyIssue,
    SpecialMonthCodeIssue,
    YearFormatInconsistencyIssue,
    AmbiguousYearFormatIssue,
    InvalidYearValueIssue,
)


def parse_issue(d: dict[str, Any]) -> Issue:
    """Validate a legacy dict against the discriminated union and return the typed instance."""
    return ISSUE_ADAPTER.validate_python(d)


def parse_issues(
    raw: Iterable[dict[str, Any]],
    *,
    source: AgentName | None = None,
    allowed_types: set[str] | None = None,
) -> list[Issue]:
    """Validate an iterable of legacy issue dicts, dropping any that fail.

    Each surviving dict is round-tripped through ``ISSUE_ADAPTER`` and tagged
    with ``source`` when supplied. Dicts whose ``type`` is not in
    ``allowed_types`` (when given) are skipped before validation. Validation
    failures are logged and the offending entry is dropped, never raised.
    """
    out: list[Issue] = []
    for raw_dict in raw:
        if not isinstance(raw_dict, dict):
            logger.warning("parse_issues: skipping non-dict entry %r", raw_dict)
            continue
        if allowed_types is not None and raw_dict.get("type") not in allowed_types:
            logger.warning(
                "parse_issues: dropping issue with disallowed type=%r (allowed=%s)",
                raw_dict.get("type"),
                sorted(allowed_types),
            )
            continue
        payload: dict[str, Any] = dict(raw_dict)
        if source is not None and payload.get("source") is None:
            payload["source"] = source
        try:
            out.append(ISSUE_ADAPTER.validate_python(payload))
        except ValidationError as exc:
            logger.warning(
                "parse_issues: dropping invalid issue type=%r column=%r: %s",
                payload.get("type"),
                payload.get("column"),
                exc,
            )
    return out


class AgentReport(TypedDict):
    """Shape every Layer-1 detector writes to ``state.<x>_report``.

    Storing typed ``Issue`` instances (not dicts) closes B1 structurally: the
    discriminated union enforces required fields like
    ``FormatPatternViolationIssue.pattern`` between detection and remediation.
    """

    issues: list[Issue]
    total_issues: int
