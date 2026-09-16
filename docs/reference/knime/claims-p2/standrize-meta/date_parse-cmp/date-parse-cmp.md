# KNIME Date Standardization Workflow

## Workflow Architecture

### High-Level Flow

```
Component Input
    ↓
Excel Reader (DATA_Var_Values)
    ↓
┌─────────────────────────────────────────┐
│   Nominal Value Row Filter              │
│   (Filter Date Variables)               │
└─────────────────────────────────────────┘
    ↓
Value Lookup → Row Filter → Extract Table Spec → Row Filter
    ↓
┌─────────────────────────────────────────┐
│   Python Script (Standardize Dates)     │
│   - Imports utils/date_standardizer.py  │
│   - Applies transformations             │
│   - Tracks failed conversions           │
└─────────────────────────────────────────┘
    ↓
Time Modifier → Column Filter (x2)
    ↓
Composed Output
```

---

## Node Descriptions

### 1. **Component Input**
- Entry point for the workflow
- Receives raw claims data table

### 2. **Excel Reader**
- Reads `DATA_Var_Values` sheet
- Contains date variable metadata
- Provides column names to be standardized

### 3. **Nominal Value Row Filter**
- Filters to only date-related variables
- Creates the "NEW" column list for Python script

### 4. **Value Lookup + Row Filters**
- Enriches data with variable metadata
- Filters to include only active date columns
- Extracts table specifications for processing

### 5. **Python Script: Standardize Dates** (Core Logic)
- Orchestration node that:
  - Reads configuration from flow variables
  - Imports the external `utils.date_standardizer` module
  - Processes claims data
  - Returns three output tables

### 6. **Time Modifier**
- Post-processing adjustments
- Applied after standardization

### 7. **Column Filters**
- Removes intermediate/tracking columns
- Preserves only output columns needed downstream
- Two filters for different column sets

### 8. **Composed Output**
- Final result set
- Structured for downstream consumption

---

## Python Script Node: Standardize Dates

### Location in Workflow
The Python Script node is the heart of the data transformation. It is deliberately thin—acting as **glue only**, with all business logic delegated to external Python files.

### Script Code
📄 Link to full module: utils/date_standardizer.py

<details> <summary><strong>Click to expand KNIME Node Code</strong></summary>
python
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
</details>

---

## Key Design Principles

### 1. **Separation of Concerns**
- **KNIME node**: I/O orchestration and configuration reading only
- **External Python module**: All date parsing, validation, and transformation logic
- **Benefit**: Code is testable, version-controlled, and reusable outside KNIME

### 2. **Configuration as Flow Variable**
- `code_base_path` is injected from `Control_Settings.xlsx`, not hardcoded
- Enables portable workflows across machines without editing node code
- Single source of truth for shared code location

### 3. **Module Reload**
```python
importlib.reload(date_standardizer)
```
- KNIME keeps the Python process alive between runs
- Without reload, edited `.py` files would serve stale code
- Force reload ensures always running the live version

### 4. **Three Output Tables**

| Output | Purpose | Use Case |
|--------|---------|----------|
| **Table 0** | Main data + standardized dates + backup columns | Downstream analysis |
| **Table 1** | Failed conversions summary (value → count) | QA/alerting |
| **Table 2** | Row-by-row diagnostics with source tracking | Troubleshooting |

### 5. **Metadata-Driven Column Selection**
- Date columns are NOT hardcoded in the node
- Instead, read dynamically from input table (column "NEW")
- Allows adding/removing date columns without editing the script