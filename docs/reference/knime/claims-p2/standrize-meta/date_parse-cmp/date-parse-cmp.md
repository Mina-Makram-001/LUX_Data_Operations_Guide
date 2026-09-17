# Date Parsing Standardization (`date_parse-cmp`)

**Workflow Node:** KNIME Component (Date Parse)  
**Module Reference:** `claims p2v1/Standardize/Date Parse`  
**Reference Diagram:** `image_52ea8d.jpg`

---

## Overview

This component node standardizes date and time fields across incoming data streams. As depicted in the `image_52ea8d.jpg` workflow, it orchestrates metadata extraction via an external Excel mapping file, filters target date variables, and applies Python-based string-to-datetime parsing. Finally, it splits the cleaned data into discrete date/time and date-only streams while purging legacy tracking columns.

---

## Key Responsibilities

1. **Metadata Extraction & Filtering**: Reads external variable mapping data (via `Excel Reader (Data_Var_Names)`) and uses `Nominal Value Row Filter` and `Value Lookup` nodes to isolate the specific columns requiring date conversion.
2. **Dynamic Date Parsing**: Executes the `04 String to Date&Time` Python Script, mapping the identified target columns from the metadata stream against the primary data stream to standardize string-based date entries.
3. **Time Modification**: Routes the parsed datetime data through a `Time Modifier` (`Date&Time to Date`) to generate a truncated, date-only version of the parsed fields.
4. **Schema Cleanup**: Employs parallel `Column Filter` nodes configured to drop legacy fields (specifically targeting `_old_match` columns) to prevent schema bloat downstream.
5. **Multi-Port Output Generation**: Emits four distinct outputs including the modified date fields, the full datetime fields, parse diagnostics, and the isolated date variable specifications.

---

## Configuration & Flow Variables

| Variable Name | Required | Description |
| :--- | :---: | :--- |
| `Data_Var_Names` | **Yes** | File path/configuration pointing to the Excel dictionary that defines which variables are classified as date fields. |

---

## Node Inputs & Outputs

### Input Ports

| Port Index | Input Source | Description | Expected Format |
| :---: | :--- | :--- | :--- |
| `0` | Upstream Data Stream | Raw/semi-processed dataset containing unparsed string date fields. | KNIME Data Table |
| `Internal` | Excel Reader | External metadata dictionary defining date column mappings. | `.xlsx` / `.xls` |

### Output Ports

| Port Index | Dataset Name | Description |
| :---: | :--- | :--- |
| `0` | `date_only_df` | Claims dataset with standardized dates (time components stripped), with `_old_match` columns filtered out. |
| `1` | `datetime_df` | Claims dataset with full Date&Time standardization, with `_old_match` columns filtered out. |
| `2` | `diagnostics_df` | Secondary output from the Python Script containing parse logs or unparsed record exclusions. |
| `3` | `date_specs_df` | The filtered dictionary table containing only the date variable specifications used during this run. |

---

## Script Execution Logic

??? note "Python Execution Logic — [date_standardizer.py](.\date_standardizer.md)
    ```python
        import knime.scripting.io as knio
        import pandas as pd
        import traceback

        try:
    # =============================================================================
    # KNIME Python Script node: Standardize Dates  (glue only — no business logic)
    # =============================================================================
    # This node is thin glue. All real work lives in the version-controlled file
    # utils/date_standardizer.py. The node only: finds that file, imports it, calls
    # it, and writes the results to the node output ports.
    #
    # Node ports
    #   Input  table 0 : the main data table (claims), with date columns to clean
    #   Input  table 1 : the date-variable table, with a column "NEW" listing the
    #                    names of the columns to treat as dates
    #   Output table 0 : the main table with standardized dates + backup + status
    #   Output table 1 : summary of failed values and their counts
    #   Output table 2 : detailed row-by-row diagnostics with source tracking
    #   Flow variable  : code_base_path  (set from Control_Settings.xlsx)
    # =============================================================================

    import sys
    import importlib
    import knime.scripting.io as knio

    # 1) Read the shared-code folder location from the flow variable.
    #    This path is NOT hardcoded; it comes from Control_Settings.xlsx so it can
    #    change machine to machine without editing this node.
    code_base_path = knio.flow_variables["code_base_path"]

    # 2) Make the shared-code folder importable.
    if code_base_path not in sys.path:
        sys.path.append(code_base_path)

    # 3) Import the module, then force a reload.
    #    KNIME keeps the Python process alive between runs, so an edited .py can
    #    serve stale code. reload() guarantees we always run the live file.
    from utils import date_standardizer
    importlib.reload(date_standardizer)

    # 4) Read node inputs.
    df = knio.input_tables[0].to_pandas()
    date_vars = knio.input_tables[1].to_pandas()

    # The list of date columns comes from the input, not from inside this node.
    date_columns = date_vars["NEW"].dropna().astype(str).tolist()

    # 5) Call the pure function. Tracking columns and accepted formats use the
    #    module defaults; pass overrides here only if a source needs them.
    result = date_standardizer.standardize_dates(df, date_columns=date_columns)

    # 6) Print a short summary to the console for the person running the workflow.
    print(date_standardizer.summarize_status(result, date_columns))

    # 7) Write the three tables back to the node output ports.
    knio.output_tables[0] = knio.Table.from_pandas(result.data)
    knio.output_tables[1] = knio.Table.from_pandas(result.summary)
    knio.output_tables[2] = knio.Table.from_pandas(result.diagnostics)
        ```