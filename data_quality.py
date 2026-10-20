"""
data_quality.py
---------------
Standard data quality checks for any pandas DataFrame.

Two layers of checks:

    1. AUTOMATIC checks, run on every DataFrame without configuration.
       They describe the data and raise WARNINGS:
       duplicate rows, missing values, blank text, stray spaces,
       mixed types, constant columns, extreme outliers.

    2. RULES you declare for your data. A broken rule is an ERROR:
       required columns, data types, unique keys, mandatory values,
       numeric ranges, allowed values, text formats, date ranges.

Usage:
    from data_quality import run_checks, split_valid_invalid

    report = run_checks(df, rules)              # one row per check
    valid, invalid = split_valid_invalid(df, rules)

Run this file directly to see a demonstration:
    python data_quality.py
"""

import re
from dataclasses import dataclass

import pandas as pd

ERROR, WARNING = "ERROR", "WARNING"


# @dataclass is a decorator: it adds code to the class written below it.
# Here it turns Result into a simple container for data. From the list of
# fields below, Python generates the methods you would otherwise write by hand:
#   __init__  creates a Result:  Result("not_null", "borrower", "completeness", "ERROR", 1)
#   __repr__  displays it:       print(r) -> Result(check='not_null', column='borrower', ...)
#   __eq__    compares two Results field by field
# Each field is declared as  name: type  and may have a default value (= ...).
# Fields with a default must come after the fields without one.
# See the README, section "What is @dataclass?", for a full explanation.
@dataclass
class Result:
    """Outcome of one check."""
    check: str                  # e.g. "not_null"
    column: str                 # the column checked, or "(dataset)"
    dimension: str              # completeness, validity, uniqueness...
    severity: str               # ERROR or WARNING
    failed: int                 # number of failing rows (or columns)
    examples: str = ""          # a few offending values; default: empty
    mask: pd.Series | None = None   # True for each failing row; None for dataset-level checks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _examples(values, limit: int = 3) -> str:
    """Up to `limit` distinct offending values, for the report."""
    distinct = pd.Series(values).drop_duplicates().head(limit)
    return ", ".join(repr(v) for v in distinct)


def _row_result(check, column, dimension, severity, df, mask) -> Result:
    """Build a row-level result from a True/False mask."""
    mask = mask.fillna(False).astype(bool)
    values = df.loc[mask, column] if column in df.columns else []
    # For missing values, showing "nan" as an example would tell nothing.
    examples = "" if check in ("missing_values", "not_null") else _examples(values)
    return Result(check, column, dimension, severity, int(mask.sum()), examples, mask)


def _bad_type(series: pd.Series, expected: str) -> pd.Series:
    """True where a non-missing value cannot be read as the expected type."""
    present = series.notna()
    if expected == "numeric":
        converted = pd.to_numeric(series, errors="coerce")
        return present & converted.isna()
    if expected == "integer":
        converted = pd.to_numeric(series, errors="coerce")
        return present & (converted.isna() | (converted % 1 != 0))
    if expected == "date":
        converted = pd.to_datetime(series, errors="coerce", format="mixed")
        return present & converted.isna()
    if expected == "string":
        return present & ~series.map(lambda v: isinstance(v, str))
    if expected == "bool":
        return present & ~series.isin([True, False])
    raise ValueError(f"Unknown type '{expected}': use numeric, integer, date, string or bool")


# ---------------------------------------------------------------------------
# 1. Automatic checks (WARNINGS)
# ---------------------------------------------------------------------------
def profile_checks(df: pd.DataFrame) -> list[Result]:
    """Checks that apply to any DataFrame. They flag what deserves a look."""
    results = []

    # Fully duplicated rows: every column identical (the first copy is not counted).
    duplicates = df.duplicated(keep="first")
    results.append(Result("duplicate_rows", "(dataset)", "uniqueness", WARNING,
                          int(duplicates.sum()), mask=duplicates))

    for col in df.columns:
        s = df[col]

        # Missing values: None, NaN, NaT.
        results.append(_row_result("missing_values", col, "completeness", WARNING, df, s.isna()))

        if s.dtype == object or pd.api.types.is_string_dtype(s):
            text = s.map(lambda v: v if isinstance(v, str) else None)
            # Blank text: "" or only spaces. Looks filled in, but holds no value.
            results.append(_row_result("blank_text", col, "completeness", WARNING, df,
                                       text.notna() & (text.str.strip() == "")))
            # Leading or trailing spaces: "FRA " never equals "FRA" in a filter or a merge.
            results.append(_row_result("stray_spaces", col, "consistency", WARNING, df,
                                       text.notna() & (text != text.str.strip()) & (text.str.strip() != "")))
            # Mixed types: e.g. numbers and text in the same column.
            types = s.dropna().map(lambda v: type(v).__name__)
            if types.nunique() > 1:
                results.append(Result("mixed_types", col, "consistency", WARNING, types.nunique(),
                                      ", ".join(sorted(types.unique()))))

        # Constant column: one single value everywhere, so it carries no information.
        if len(df) > 1 and s.nunique(dropna=True) == 1 and s.notna().all():
            results.append(Result("constant_column", col, "validity", WARNING, 1, _examples(s)))

        # Extreme outliers: beyond 3 interquartile ranges from the quartiles.
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s) and s.notna().sum() >= 4:
            q1, q3 = s.quantile([0.25, 0.75])
            iqr = q3 - q1
            if iqr > 0:
                outside = (s < q1 - 3 * iqr) | (s > q3 + 3 * iqr)
                results.append(_row_result("extreme_outliers", col, "accuracy", WARNING, df, outside))

    return results


# ---------------------------------------------------------------------------
# 2. Declared rules (ERRORS)
# ---------------------------------------------------------------------------
def rule_checks(df: pd.DataFrame, rules: dict) -> list[Result]:
    """Checks that you declare for your data. Each broken rule is an ERROR.

    rules = {
        "required_columns": ["id", "amount"],
        "dtypes":     {"amount": "numeric", "id": "integer", "date": "date"},
        "unique":     [["id"], ["country", "year"]],   # one key per list
        "not_null":   ["id", "amount"],
        "ranges":     {"amount": (0, None)},            # (min, max); None = no limit
        "allowed":    {"status": ["open", "closed"]},
        "patterns":   {"currency": r"[A-Z]{3}"},        # the whole value must match
        "date_range": {"date": ("2000-01-01", "today")},
    }
    Every key is optional.
    """
    results = []

    # Required columns: a missing column makes every rule on it impossible to run.
    missing = [c for c in rules.get("required_columns", []) if c not in df.columns]
    results.append(Result("required_columns", "(dataset)", "completeness", ERROR,
                          len(missing), ", ".join(missing)))
    present = lambda col: col in df.columns   # noqa: E731  rules on absent columns are skipped

    for col, expected in rules.get("dtypes", {}).items():
        if present(col):
            results.append(_row_result(f"dtype_{expected}", col, "validity", ERROR, df,
                                       _bad_type(df[col], expected)))

    for key in rules.get("unique", []):
        key = [key] if isinstance(key, str) else list(key)
        if all(present(c) for c in key):
            dupes = df.duplicated(subset=key, keep=False)   # every copy is flagged
            label = " + ".join(key)
            values = df.loc[dupes, key].astype(str).agg(" | ".join, axis=1).drop_duplicates()
            results.append(Result("unique", label, "uniqueness", ERROR, int(dupes.sum()),
                                  ", ".join(values.head(3)), dupes))

    for col in rules.get("not_null", []):
        if present(col):
            results.append(_row_result("not_null", col, "completeness", ERROR, df, df[col].isna()))

    for col, (low, high) in rules.get("ranges", {}).items():
        if present(col):
            values = pd.to_numeric(df[col], errors="coerce")   # non-numbers are the dtype check's job
            outside = pd.Series(False, index=df.index)
            if low is not None:
                outside |= values < low
            if high is not None:
                outside |= values > high
            results.append(_row_result(f"range [{low}, {high}]", col, "validity", ERROR, df, outside))

    for col, allowed in rules.get("allowed", {}).items():
        if present(col):
            results.append(_row_result("allowed_values", col, "validity", ERROR, df,
                                       df[col].notna() & ~df[col].isin(allowed)))

    for col, pattern in rules.get("patterns", {}).items():
        if present(col):
            regex = re.compile(pattern)
            bad = df[col].notna() & ~df[col].map(lambda v: bool(regex.fullmatch(str(v))))
            results.append(_row_result(f"pattern {pattern}", col, "validity", ERROR, df, bad))

    for col, (start, end) in rules.get("date_range", {}).items():
        if present(col):
            dates = pd.to_datetime(df[col], errors="coerce", format="mixed")
            start = pd.Timestamp.today().normalize() if start == "today" else pd.Timestamp(start)
            end = pd.Timestamp.today().normalize() if end == "today" else pd.Timestamp(end)
            outside = dates.notna() & ((dates < start) | (dates > end))
            results.append(_row_result(f"date_range [{start.date()}, {end.date()}]", col,
                                       "validity", ERROR, df, outside))

    return results


# ---------------------------------------------------------------------------
# Running the checks
# ---------------------------------------------------------------------------
def _all_results(df: pd.DataFrame, rules: dict | None) -> list[Result]:
    if df.empty:
        return [Result("not_empty", "(dataset)", "completeness", ERROR, 1, "no rows")]
    return profile_checks(df) + rule_checks(df, rules or {})


def run_checks(df: pd.DataFrame, rules: dict | None = None) -> pd.DataFrame:
    """Run every check and return the report: one row per check."""
    results = _all_results(df, rules)
    report = pd.DataFrame([{
        "status": "PASS" if r.failed == 0 else ("FAIL" if r.severity == ERROR else "WARN"),
        "check": r.check,
        "column": r.column,
        "dimension": r.dimension,
        "failed": r.failed,
        "failed_pct": round(100 * r.failed / len(df), 1) if (len(df) and r.mask is not None) else None,
        "examples": r.examples,
    } for r in results])
    return report


def split_valid_invalid(df: pd.DataFrame, rules: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separate the rows breaking at least one rule (ERROR) from the others.

    The invalid rows get a `dq_reasons` column listing the rules each one broke.
    Warnings never make a row invalid.
    """
    reasons = pd.Series("", index=df.index)
    for r in _all_results(df, rules):
        if r.severity == ERROR and r.mask is not None and r.failed:
            label = f"{r.check}({r.column})"
            reasons[r.mask] = reasons[r.mask] + label + "; "
    reasons = reasons.str.rstrip("; ")
    invalid = df[reasons != ""].assign(dq_reasons=reasons[reasons != ""])
    return df[reasons == ""], invalid


def print_report(report: pd.DataFrame, show_passed: bool = False) -> None:
    """Print a summary line, then the failed checks (and the passed ones on request)."""
    counts = report["status"].value_counts()
    print(f"Data quality: {counts.get('PASS', 0)} passed, "
          f"{counts.get('WARN', 0)} warnings, {counts.get('FAIL', 0)} errors")
    shown = report if show_passed else report[report["status"] != "PASS"]
    if len(shown):
        with pd.option_context("display.width", 140, "display.max_colwidth", 40):
            print(shown.sort_values(["status", "column"]).to_string(index=False))


# ---------------------------------------------------------------------------
# Demonstration
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # A small loan book with deliberate problems.
    loans = pd.DataFrame({
        "loan_id":   [101, 102, 103, 103, 105, 106, 107, 108],
        "borrower":  ["Smith", "Jones ", "Brown", "Brown", "", "Taylor", None, "Evans"],
        "amount":    [250_000, 180_000, 320_000, 320_000, -5_000, 210_000, 195_000, 9_900_000],
        "rate":      [0.045, 0.051, "4.8%", 0.048, 0.052, 0.049, 0.047, 0.046],
        "currency":  ["GBP", "GBP", "gbp", "GBP", "EUR", "GBP", "GBP", "GBP"],
        "status":    ["open", "open", "closed", "closed", "open", "defaulted", "open", "pending"],
        "start_date": ["2021-03-01", "2022-07-15", "2020-11-30", "2020-11-30",
                       "2023-02-29", "2019-05-10", "2031-01-01", "2024-06-01"],
    })

    rules = {
        "required_columns": ["loan_id", "amount", "rate", "currency", "status", "start_date"],
        "dtypes":     {"loan_id": "integer", "amount": "numeric", "rate": "numeric",
                       "start_date": "date"},
        "unique":     [["loan_id"]],
        "not_null":   ["loan_id", "borrower", "amount"],
        "ranges":     {"amount": (0, None), "rate": (0, 0.25)},
        "allowed":    {"status": ["open", "closed", "defaulted"]},
        "patterns":   {"currency": r"[A-Z]{3}"},
        "date_range": {"start_date": ("2000-01-01", "today")},
    }

    report = run_checks(loans, rules)
    print_report(report)

    valid, invalid = split_valid_invalid(loans, rules)
    print(f"\n{len(valid)} valid rows, {len(invalid)} invalid rows:")
    print(invalid[["loan_id", "dq_reasons"]].to_string(index=False))
