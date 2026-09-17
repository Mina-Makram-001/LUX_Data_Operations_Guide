"""
date_standardizer.py
=====================

Pure, framework-free date standardization for the insurance claims pipeline.

PURPOSE
-------
Convert messy text date columns coming from many insurance companies into one
clean, unambiguous datetime format, and produce two diagnostic tables that
explain every value the parser could not handle.

This module contains NO KNIME imports. All logic is plain pandas/numpy so it can
be unit-tested locally and version-controlled. The KNIME node is only thin glue
that imports `standardize_dates` and wires it to the node ports.

WHY THIS MODULE EXISTS (the bug it removes)
-------------------------------------------
An earlier version parsed dates with `pd.to_datetime(..., dayfirst=True)` as a
first pass. For ISO strings like "2020-11-01" that flag makes pandas read the
middle number as the DAY, silently producing "2020-01-11". The swap only happens
when the day-of-month is <= 12 (when it is also a valid month), so a column ends
up with a mix of correct and silently-wrong dates that no error report catches.

This module fixes that by parsing ONLY with explicit, ordered format strings.
An explicit format is unambiguous: "2020-11-01" under "%Y-%m-%d" can only be
1 November. Values that match no format become NaT and are reported as failures,
instead of being turned into plausible-but-wrong dates.

PUBLIC API
----------
standardize_dates(df, date_columns, ...) -> StandardizeResult
parse_date_series(raw_series, date_formats) -> (original_missing, parsed_series)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from pandas.api.types import is_datetime64_any_dtype


# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

# Ordered list of accepted date formats. ORDER MATTERS: the most trusted and
# most specific formats come first. Each value is parsed with an explicit
# `format=`, so there is no day/month guessing.
#
# IMPORTANT BUSINESS DECISION — slash dates:
# Slash dates are read DAY-FIRST here ("%d/%m/%Y"). A value like "03/05/2020"
# is treated as 3 May, not 5 March. If any source file uses US month-first
# slash dates, you MUST supply a different `date_formats` list for that source.
# A single column cannot safely contain both conventions.
DEFAULT_DATE_FORMATS: tuple[str, ...] = (
    # ISO and ISO-like (no ambiguity)
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y%m%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    # ISO with 12-hour clock (needed after Arabic AM/PM is translated)
    "%Y-%m-%d %I:%M:%S %p",
    "%Y-%m-%d %I:%M %p",
    # Day-first European
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %I:%M:%S %p",
    "%d/%m/%Y %I:%M %p",
    "%d-%m-%y",
    "%d/%m/%y",
)

# Columns used to trace a failed value back to its exact source location.
DEFAULT_TRACKING_COLUMNS: tuple[str, ...] = (
    "LA_SOURCE_FILE",
    "LA_SOURCE_PAGE",
    "LA_R_FILE_NAME",
    "LA_SOURCE_ROW",
)

# Text tokens that mean "no value" and must be treated as missing.
_MISSING_TOKENS = ["", "nan", "None", "<NA>", "NaT", "NULL", "null"]

# Status codes written to each "<column>_status" column.
STATUS_OK = 0            # had a value and it parsed
STATUS_APPEARED = 1      # was missing but a date appeared (should never happen)
STATUS_FAILED = 2        # had a value but parsing failed
STATUS_BOTH_MISSING = 3  # was missing and stayed missing


@dataclass
class StandardizeResult:
    """
    Container for the three tables produced by `standardize_dates`.

    Attributes
    ----------
    data : pandas.DataFrame
        The main table. Each processed date column now holds real datetimes
        (or NaT). For every processed column a "<col>_old" backup column and a
        "<col>_status" code column are added.
    summary : pandas.DataFrame
        One row per unique failed value, with columns
        ['Failed_Column', 'Raw_Value', 'Count'].
    diagnostics : pandas.DataFrame
        One row per failed cell, with the available tracking columns plus
        ['Failed_Column', 'Raw_Value'].
    """

    data: pd.DataFrame
    summary: pd.DataFrame
    diagnostics: pd.DataFrame


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------

def clean_raw_values(values: pd.Series) -> pd.Series:
    """
    Clean a series of raw date values before parsing.

    Steps: cast to text, trim ends, collapse repeated spaces, translate the
    Arabic AM/PM markers ("ص"/"م") to "AM"/"PM", and turn empty or null-like
    tokens into NaN.

    Parameters
    ----------
    values : pandas.Series
        Raw values (any dtype). Usually the unique values of one column.

    Returns
    -------
    pandas.Series
        Cleaned text, NaN where the value means "missing". Same index as input.
    """
    cleaned = values.astype(str).str.strip()
    cleaned = cleaned.str.replace(r"\s+", " ", regex=True)
    cleaned = cleaned.str.replace(" ص", " AM", regex=False).str.replace(" م", " PM", regex=False)
    cleaned = cleaned.replace(_MISSING_TOKENS, np.nan)
    return cleaned


# ---------------------------------------------------------------------------
# Parsing core
# ---------------------------------------------------------------------------

def parse_cleaned_unique(cleaned_unique: pd.Series, date_formats: Sequence[str]) -> pd.Series:
    """
    Parse already-cleaned unique values using explicit formats only.

    Each format in `date_formats` is tried in order on the values still missing
    a result. No day/month inference is used, so no value is ever silently
    swapped: a value either matches a format exactly or stays NaT.

    Parameters
    ----------
    cleaned_unique : pandas.Series
        Cleaned text values (output of `clean_raw_values`). NaN means missing.
    date_formats : sequence of str
        Ordered strftime formats to try.

    Returns
    -------
    pandas.Series
        Parsed datetimes (datetime64[ns]), NaT where nothing matched. Same
        index as the input, normalized to midnight.
    """
    parsed = pd.Series(pd.NaT, index=cleaned_unique.index, dtype="datetime64[ns]")
    remaining = cleaned_unique.notna()

    for fmt in date_formats:
        if not remaining.any():
            break
        attempt = pd.to_datetime(cleaned_unique[remaining], format=fmt, errors="coerce")
        ok = attempt.notna()
        if ok.any():
            parsed.loc[ok.index[ok]] = attempt[ok]
        remaining = parsed.isna() & cleaned_unique.notna()

    return parsed.dt.normalize()


def parse_date_series(
    raw_series: pd.Series,
    date_formats: Sequence[str] = DEFAULT_DATE_FORMATS,
) -> tuple[pd.Series, pd.Series]:
    """
    Parse a full date column, using a unique-value cache for speed.

    The function parses only the distinct raw values, then maps the results
    back to every row. This is fast on large columns with few distinct dates.

    Parameters
    ----------
    raw_series : pandas.Series
        The raw column to parse (text or mixed). Index is preserved.
    date_formats : sequence of str, optional
        Ordered strftime formats to try. Defaults to `DEFAULT_DATE_FORMATS`.

    Returns
    -------
    original_missing : pandas.Series of bool
        True where the original value was missing or null-like.
    parsed_full_series : pandas.Series
        Parsed datetimes aligned to `raw_series.index`, NaT where parsing
        failed or the value was missing.
    """
    unique_raw_vals = raw_series.dropna().unique()

    if len(unique_raw_vals) == 0:
        empty = pd.Series(pd.NaT, index=raw_series.index, dtype="datetime64[ns]")
        return raw_series.isna(), empty

    unique_series = pd.Series(unique_raw_vals, index=unique_raw_vals)
    cleaned_unique = clean_raw_values(unique_series)

    parsed_unique = parse_cleaned_unique(cleaned_unique, date_formats)

    parsed_full_series = raw_series.map(parsed_unique)
    original_missing = raw_series.map(cleaned_unique).isna()
    return original_missing, parsed_full_series


def build_status(original_missing: pd.Series, result_missing: pd.Series) -> pd.Series:
    """
    Build the per-row status code for one column.

    Parameters
    ----------
    original_missing : pandas.Series of bool
        True where the original value was missing.
    result_missing : pandas.Series of bool
        True where the parsed result is NaT.

    Returns
    -------
    pandas.Series of int
        STATUS_OK (0), STATUS_APPEARED (1), STATUS_FAILED (2),
        STATUS_BOTH_MISSING (3).
    """
    conditions = [
        original_missing & ~result_missing,   # 1
        ~original_missing & result_missing,    # 2
        original_missing & result_missing,     # 3
    ]
    choices = [STATUS_APPEARED, STATUS_FAILED, STATUS_BOTH_MISSING]
    return pd.Series(np.select(conditions, choices, default=STATUS_OK), index=original_missing.index)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def standardize_dates(
    df: pd.DataFrame,
    date_columns: Iterable[str],
    tracking_columns: Sequence[str] = DEFAULT_TRACKING_COLUMNS,
    date_formats: Sequence[str] = DEFAULT_DATE_FORMATS,
    keep_backup: bool = True,
) -> StandardizeResult:
    """
    Standardize one or more date columns in a DataFrame and build diagnostics.

    For each named column the function: keeps a backup, parses the column with
    explicit formats, writes a status code, and records every value that had
    content but failed to parse.

    Columns named in `date_columns` but absent from `df` are skipped quietly.

    Parameters
    ----------
    df : pandas.DataFrame
        The input table. It is copied; the caller's frame is not modified.
    date_columns : iterable of str
        Names of the columns to treat as dates.
    tracking_columns : sequence of str, optional
        Source-tracing columns to include in the detailed diagnostics, if
        present. Defaults to `DEFAULT_TRACKING_COLUMNS`.
    date_formats : sequence of str, optional
        Ordered strftime formats to try. Defaults to `DEFAULT_DATE_FORMATS`.
    keep_backup : bool, optional
        If True, keep a "<col>_old" backup column for each processed column.

    Returns
    -------
    StandardizeResult
        `.data`, `.summary`, `.diagnostics`.

    Raises
    ------
    TypeError
        If `df` is not a pandas DataFrame.
    """
    if not isinstance(df, pd.DataFrame):
        raise TypeError("standardize_dates expects a pandas DataFrame as `df`.")

    df = df.copy()
    date_columns = list(date_columns)
    tracking_columns = list(tracking_columns)

    summary_records: list[pd.DataFrame] = []
    detailed_records: list[pd.DataFrame] = []

    for col in date_columns:
        if col not in df.columns:
            continue

        backup = df[col].copy()

        if is_datetime64_any_dtype(df[col]):
            parsed_series = df[col].dt.normalize()
            original_missing = df[col].isna()
        else:
            original_missing, parsed_series = parse_date_series(df[col], date_formats)

        df[col] = parsed_series
        if keep_backup:
            df[f"{col}_old"] = backup

        result_missing = parsed_series.isna()
        df[f"{col}_status"] = build_status(original_missing, result_missing).values

        failed_mask = (~original_missing) & result_missing
        if not failed_mask.any():
            continue

        failures = df[failed_mask].copy()
        failures["Failed_Column"] = col
        failures["Raw_Value"] = backup[failed_mask].values

        available_tracking = [tc for tc in tracking_columns if tc in failures.columns]
        detailed_records.append(failures[available_tracking + ["Failed_Column", "Raw_Value"]])

        counts = failures["Raw_Value"].astype(str).value_counts().reset_index()
        counts.columns = ["Raw_Value", "Count"]
        counts["Failed_Column"] = col
        summary_records.append(counts)

    summary_df = _build_summary(summary_records)
    diagnostics_df = _build_diagnostics(detailed_records, tracking_columns)
    return StandardizeResult(data=df, summary=summary_df, diagnostics=diagnostics_df)


def _build_summary(records: list[pd.DataFrame]) -> pd.DataFrame:
    """Concatenate and sort the per-value failure summary."""
    if not records:
        # Create an empty DataFrame with strict, explicit data types to prevent KNIME DataCell errors
        summary_df = pd.DataFrame({
            'Failed_Column': pd.Series(dtype='string'),
            'Raw_Value': pd.Series(dtype='string'),
            'Count': pd.Series(dtype='int32')
        })
    else:
        summary_df = pd.concat(records, ignore_index=True)
        summary_df = summary_df[["Failed_Column", "Raw_Value", "Count"]]
        summary_df = summary_df.sort_values(
            ["Failed_Column", "Count"], ascending=[True, False]
        ).reset_index(drop=True)
        
        # Enforce strict data types on populated summary data
        summary_df['Failed_Column'] = summary_df['Failed_Column'].astype("string")
        summary_df['Raw_Value'] = summary_df['Raw_Value'].astype("string")
        summary_df['Count'] = summary_df['Count'].astype("int32")
        
    return summary_df


def _build_diagnostics(records: list[pd.DataFrame], tracking_columns: Sequence[str]) -> pd.DataFrame:
    """Concatenate the per-cell failure detail, or return an empty shaped frame."""
    if records:
        diagnostics_df = pd.concat(records, ignore_index=True)
        # Enforce strict string types across all columns when data exists
        for col in diagnostics_df.columns:
            diagnostics_df[col] = diagnostics_df[col].astype("string")
    else:
        # Create an empty DataFrame with strict string types for all tracking and failure columns
        diag_dict = {col: pd.Series(dtype='string') for col in tracking_columns}
        diag_dict['Failed_Column'] = pd.Series(dtype='string')
        diag_dict['Raw_Value'] = pd.Series(dtype='string')
        diagnostics_df = pd.DataFrame(diag_dict)
        
    return diagnostics_df

def summarize_status(result: StandardizeResult, date_columns: Iterable[str]) -> str:
    """
    Build a short text summary of parse results, for printing to a console.

    Parameters
    ----------
    result : StandardizeResult
        Output of `standardize_dates`.
    date_columns : iterable of str
        Columns to report on.

    Returns
    -------
    str
        A multi-line, printable summary.
    """
    df = result.data
    lines = ["=" * 60, "DATE PARSING SUMMARY", "=" * 60]
    for col in date_columns:
        status_col = f"{col}_status"
        if status_col not in df.columns:
            continue
        status = df[status_col]
        total = len(status)
        lines.append(f"\n  [{col}]")
        lines.append(f"    OK parsed (0):            {(status == STATUS_OK).sum():>6} / {total}")
        lines.append(f"    Parse failed (2):         {(status == STATUS_FAILED).sum():>6}")
        lines.append(f"    Both missing (3):         {(status == STATUS_BOTH_MISSING).sum():>6}")
        lines.append(f"    Appeared from nothing (1):{(status == STATUS_APPEARED).sum():>6}")
    lines.append("=" * 60)
    return "\n".join(lines)
