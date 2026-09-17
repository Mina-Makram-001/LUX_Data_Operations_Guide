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
