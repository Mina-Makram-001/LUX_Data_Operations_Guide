"""
MODULE: amount_standardizer
PURPOSE: Standardize amount columns from string to float, capturing failures
DOMAIN: utils

This module provides core logic for financial amount parsing with diagnostic
tracking. It is pure Python (no KNIME dependencies in core functions) and
fully testable in isolation.
"""

import pandas as pd
import gc
from typing import Tuple, List, Optional


def standardize_amounts(
    data_df: pd.DataFrame,
    amount_columns: List[str],
    tracking_columns: List[str],
    null_to_zero: bool = True
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Convert amount columns from string to float, tracking parse failures.
    
    Takes a DataFrame with string-formatted amount columns, strips whitespace,
    removes common financial formatting (commas), and attempts numeric conversion.
    Successfully parsed values become floats; parse failures are isolated into a
    diagnostic table with source tracking. Null/empty cells are handled per the
    null_to_zero flag (default: convert to 0.0).
    
    Parameters
    ----------
    data_df : pd.DataFrame
        Input DataFrame with consolidated raw string data.
    amount_columns : List[str]
        Column names to standardize (e.g., ["Gross Amount", "Ceded Amount"]).
    tracking_columns : List[str]
        Columns needed to identify the source of failed parses
        (e.g., ["LA_SOURCE_FILE", "LA_SOURCE_ROW"]).
    null_to_zero : bool, optional
        If True (default), convert genuinely empty/null cells to 0.0.
        If False, leave them as NaN.
    
    Returns
    -------
    Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]
        - standardized_df: Main DataFrame with amount columns as floats
        - summary_df: Grouped summary of unique failures (Failed_Column, Raw_Value, Count)
        - diagnostics_df: Row-by-row detail of all failures (tracking + error info)
    
    Raises
    ------
    ValueError
        If data_df is None or not a DataFrame.
    
    Examples
    --------
    >>> df = pd.DataFrame({
    ...     'Gross Amount': ['100.50', '200', '-', ''],
    ...     'LA_SOURCE_FILE': ['file1', 'file1', 'file1', 'file1']
    ... })
    >>> std, summary, diag = standardize_amounts(
    ...     df,
    ...     amount_columns=['Gross Amount'],
    ...     tracking_columns=['LA_SOURCE_FILE'],
    ...     null_to_zero=True
    ... )
    >>> std['Gross Amount'].tolist()
    [100.5, 200.0, 0.0, 0.0]
    """
    
    # =========================================================================
    # VALIDATION
    # =========================================================================
    if data_df is None:
        raise ValueError("data_df cannot be None.")
    if not isinstance(data_df, pd.DataFrame):
        raise ValueError(f"data_df must be a DataFrame, got {type(data_df)}")
    
    # =========================================================================
    # INITIALIZATION & SETUP
    # =========================================================================
    unparsed_records = []
    final_df = data_df.copy()
    
    # Ensure tracking columns list exists and filter to only available columns
    if tracking_columns is None:
        tracking_columns = []
    available_tracking = [tc for tc in tracking_columns if tc in final_df.columns]
    
    # =========================================================================
    # STRIP WHITESPACE FROM ALL STRING COLUMNS (preparation)
    # =========================================================================
    final_df = final_df.apply(
        lambda x: x.str.strip() if x.dtype in ("object", "string") else x
    )
    
    # =========================================================================
    # AMOUNT COLUMN PROCESSING
    # =========================================================================
    for col in amount_columns:
        if col not in final_df.columns:
            # Skip missing columns gracefully; log a message for auditing
            print(f"WARNING: Column '{col}' not found in input DataFrame. Skipping.")
            continue
        
        # --- Step 1: Preserve the raw (original) value for diagnostics ---
        raw_series = final_df[col].copy()
        
        # --- Step 2: Clean common financial formatting ---
        # Remove commas (1,234.56 → 1234.56), trim whitespace
        clean_series = raw_series.astype(str).str.replace(',', '', regex=False).str.strip()
        
        # --- Step 3: Attempt numeric conversion ---
        # 'coerce' converts unparseable text (like "-", "N/A") to NaN
        parsed_series = pd.to_numeric(clean_series, errors='coerce')
        
        # --- Step 4: Identify failures ---
        # A failure is: raw value was non-empty AND parseable raw was not blank
        # AND the parse result is NaN
        is_populated = (
            raw_series.notna() & 
            (raw_series != "") & 
            (~raw_series.astype(str).str.lower().isin(["nan", "nat", "none", "<na>"]))
        )
        is_failed = parsed_series.isna()
        
        # --- Step 5: Extract and log failures ---
        failures_df = final_df[is_populated & is_failed].copy()
        
        if not failures_df.empty:
            failures_df['Failed_Column'] = col
            failures_df['Raw_Value'] = failures_df[col]
            
            # Keep only the tracking columns + error details
            tracking_df = failures_df[available_tracking + ['Failed_Column', 'Raw_Value']]
            unparsed_records.append(tracking_df)
        
        # --- Step 6: Apply the parsed floats (or 0.0 if null_to_zero) ---
        if null_to_zero:
            # Replace NaN (from empty or unparseable cells) with 0.0
            parsed_series = parsed_series.fillna(0.0)
        
        final_df[col] = parsed_series
    
    # =========================================================================
    # CONSOLIDATE DIAGNOSTICS
    # =========================================================================
    if unparsed_records:
        diagnostics_df = pd.concat(unparsed_records, ignore_index=True)
        
        # Group and summarize failures
        summary_df = (
            diagnostics_df
            .groupby(['Failed_Column', 'Raw_Value'])
            .size()
            .reset_index(name='Count')
            .sort_values(['Failed_Column', 'Count'], ascending=[True, False])
        )
    else:
        # No failures: create empty templates with correct structure
        diagnostics_columns = available_tracking + ['Failed_Column', 'Raw_Value']
        diagnostics_df = pd.DataFrame(columns=diagnostics_columns)
        summary_df = pd.DataFrame(columns=['Failed_Column', 'Raw_Value', 'Count'])
    
    # -------------------------------------------------------------------------
    # coerce data types for consistency and downstream processing
    # -------------------------------------------------------------------------
    # 1. define table columns (Summary)
    summary_df = pd.DataFrame({
            'Failed_Column': pd.Series(dtype='string'),
            'Raw_Value': pd.Series(dtype='string'),
            'Count': pd.Series(dtype='int32')
        })

    # 2. define details columns (Diagnostics)
    
    # diagnostics_df['Failed_Column'] = diagnostics_df['Failed_Column'].astype(str)
    # diagnostics_df['Raw_Value'] = diagnostics_df['Raw_Value'].astype(str)
    
    diag_dict = {col: pd.Series(dtype='string') for col in available_tracking}
    diag_dict['Failed_Column'] = pd.Series(dtype='string')
    diag_dict['Raw_Value'] = pd.Series(dtype='string')
    diagnostics_df = pd.DataFrame(diag_dict)

    # =========================================================================
    # CLEANUP & RETURN
    # =========================================================================
    try:
        del unparsed_records
    except NameError:
        pass
    gc.collect()
    
    return final_df, summary_df, diagnostics_df
    

def log_standardization_report(summary_df: pd.DataFrame) -> None:
    """
    Print a formatted console report of standardization failures.
    
    Useful for KNIME console output or local debugging.
    
    Parameters
    ----------
    summary_df : pd.DataFrame
        Output from standardize_amounts (summary output).
    
    Returns
    -------
    None
    
    Raises
    ------
    ValueError
        If summary_df is None or not a DataFrame.
    """
    
    if summary_df is None or not isinstance(summary_df, pd.DataFrame):
        raise ValueError("summary_df must be a DataFrame.")
    
    print("=" * 70)
    print("AMOUNT STANDARDIZATION DIAGNOSTICS REPORT")
    print("=" * 70)
    
    if summary_df.empty:
        print("SUCCESS: All amount columns parsed to float without errors.")
    else:
        print(f"\nFound {len(summary_df)} unique parse failure(s):\n")
        print(summary_df.to_string(index=False))
    
    print("=" * 70)
