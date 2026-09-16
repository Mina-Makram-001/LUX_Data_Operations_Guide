# Amount Standardization (`float_parse-cmp`)

**Workflow Node:** Python Script (Float Parse Component)  
**Module Reference:** `standrize-meta/float_parse-cmp/float-parse-cmp.md`  
**External Logic Script:** [`amount_standardizer.py`](.\amount_standardizer.md)

---

## Overview

This component node performs numeric and financial amount standardization across target columns dynamically passed from upstream configuration nodes. It executes within the KNIME Python Script environment (`knio`), importing core transformation routines from the central `utils.amount_standardizer` Python library.

---

## Key Responsibilities

1. **Dynamic Workspace Resolution**: Dynamically imports and reloads `utils.amount_standardizer` from the path defined in `code_base_path`.
2. **Schema & Target Column Extraction**: Reads main claim data from Input Port 0 and target column specifications from Input Port 1 (`NEW` column list).
3. **Lineage Preservation**: Tracks record source details across four key source metadata fields (`LA_SOURCE_FILE`, `LA_SOURCE_PAGE`, `LA_R_FILE_NAME`, `LA_SOURCE_ROW`).
4. **Standardization Execution**: Calls `standardize_amounts` to clean numeric values, handle missing/null entries (`null_to_zero=True`), and compute audit metrics.
5. **Multi-Port Output Generation**: Emits standardized claims, summary transformation reports, and diagnostic log tables.

---

## Configuration & Flow Variables

| Variable Name | Required | Description |
| :--- | :---: | :--- |
| `code_base_path` | **Yes** | Root directory path containing the shared Python utility scripts repository. |

---

## Node Inputs & Outputs

### Input Ports

| Port Index | Input Source | Description | Expected Format |
| :---: | :--- | :--- | :--- |
| `0` | Upstream Data Stream | Raw/semi-processed claims dataset requiring float parsing. | pandas DataFrame |
| `1` | Variable Column Specs | List of amount column names to be processed (extracted from column `NEW`). | Single-column table (`NEW`) |

### Output Ports

| Port Index | Dataset Name | Description |
| :---: | :--- | :--- |
| `0` | `standardized_df` | Main claims dataset with cleaned float/currency fields. |
| `1` | `summary_df` | High-level summary of standardized rows, zero-filled nulls, and error counts. |
| `2` | `diagnostics_df` | Detailed row-level audit trail for records with parse exceptions or flags. |

---

## Lineage Tracking Fields

The following tracking fields are passed into the standardizer to preserve data provenance and record-level traceability:

- `LA_SOURCE_FILE` — Source file name or identifier.
- `LA_SOURCE_PAGE` — Source page/sheet reference.
- `LA_R_FILE_NAME` — Relative source file path.
- `LA_SOURCE_ROW` — Original row index in the raw file.

---

## Script Execution Logic

??? note "Python Execution Logic — [amount_standardizer.py](.\amount_standardizer.md)"
    ```python
    import sys
    import importlib
    import traceback
    import knime.scripting.io as knio
    import pandas as pd

    # Get code path from flow variable
    code_base_path = knio.flow_variables.get('code_base_path')
    if not code_base_path:
        raise ValueError("Flow variable 'code_base_path' not set.")

    # Import and reload the module
    if code_base_path not in sys.path:
        sys.path.insert(0, code_base_path)

    try:
        import utils.amount_standardizer as amount_standardizer
        importlib.reload(amount_standardizer)
    except ImportError as e:
        raise ImportError(f"Cannot import amount_standardizer from {code_base_path}: {e}")

    # Read inputs
    data_df = knio.input_tables[0].to_pandas()
    amount_columns = knio.input_tables[1].to_pandas()["NEW"].tolist()

    tracking_columns = [
        "LA_SOURCE_FILE",
        "LA_SOURCE_PAGE", 
        "LA_R_FILE_NAME",
        "LA_SOURCE_ROW"
    ]

    # Call the standardization function
    try:
        standardized_df, summary_df, diagnostics_df = amount_standardizer.standardize_amounts(
            data_df=data_df,
            amount_columns=amount_columns,
            tracking_columns=tracking_columns,
            null_to_zero=True
        )

        # Log results
        amount_standardizer.log_standardization_report(summary_df)

        # Write outputs
        knio.output_tables[0] = knio.Table.from_pandas(standardized_df)
        knio.output_tables[1] = knio.Table.from_pandas(summary_df)
        knio.output_tables[2] = knio.Table.from_pandas(diagnostics_df)

    except Exception as e:
        print("ERROR: Node failed.")
        print(traceback.format_exc())
        raise
    ```