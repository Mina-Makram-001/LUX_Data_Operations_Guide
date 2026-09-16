"""
KNIME Python Script: Table Structure Normalizer & Audit Generator
==================================================================
This script enforces a standard column structure on an input dataset based on 
a reference template defined in an external Excel file. 

Inputs:
    - Input Port 0: Main DataFrame to be reordered/restructured.
    - Flow Variable ('control_setting'): File path to the reference Excel sheet.

Outputs:
    - Output Port 0: Standardized DataFrame aligned with the reference schema.
    - Output Port 1: Audit DataFrame detailing column changes (Added/Retained/Removed).
"""

import knime.scripting.io as knio
import pandas as pd

# =============================================================================
# CONFIGURATION
# =============================================================================
# Controls the behavior for columns present in Input 1 but NOT in the Reference Table.
#   True  : Drops unmatched columns from the output.
#   False : Keeps unmatched columns and appends them to the end of the table.
REMOVE_UNMATCHED_COLUMNS = True

# =============================================================================
# 1. READ INPUT TABLES & REFERENCE SCHEMA
# =============================================================================
# Read input dataset from KNIME Port 0
df_main = knio.input_tables[0].to_pandas()

# Retrieve Excel configuration path from KNIME Flow Variable
config_file_path = knio.flow_variables['control_setting']

# Load reference template schema from Excel file
df_ref = pd.read_excel(config_file_path, sheet_name="Table_Structure")

# Extract column lists for processing
main_cols = df_main.columns.tolist()
ref_cols = df_ref.columns.tolist()

# =============================================================================
# 2. COMPARE, RESHAPE, AND AUDIT
# =============================================================================
final_cols_order = []
audit_log = []

# -----------------------------------------------------------------------------
# Phase A: Process strictly according to the Reference Table order
# -----------------------------------------------------------------------------
for col in ref_cols:
    if col in main_cols:
        # Column exists: Retain position and mark status
        final_cols_order.append(col)
        audit_log.append({
            "Column_Name": col, 
            "Status": "Found and retained"
        })
    else:
        # Column missing: Create new column filled with NA values cast as String
        df_main[col] = pd.NA
        df_main[col] = df_main[col].astype('string')
        
        final_cols_order.append(col)
        audit_log.append({
            "Column_Name": col, 
            "Status": "Not found, created with missing (String)"
        })

# -----------------------------------------------------------------------------
# Phase B: Handle columns existing in Main Table but NOT in Reference Table
# -----------------------------------------------------------------------------
extra_cols = [col for col in main_cols if col not in ref_cols]

if REMOVE_UNMATCHED_COLUMNS:
    # Drop extra columns and document removal
    for col in extra_cols:
        audit_log.append({
            "Column_Name": col, 
            "Status": "Found and removed"
        })
else:
    # Keep extra columns and append them to the end
    for col in extra_cols:
        final_cols_order.append(col)
        audit_log.append({
            "Column_Name": col, 
            "Status": "Found, not in reference, appended to end"
        })

# Apply final column hierarchy and create audit log dataframe
df_out = df_main[final_cols_order]
df_audit = pd.DataFrame(audit_log)

# =============================================================================
# 3. WRITE TO OUTPUT PORTS
# =============================================================================
# Output Port 0: Restructured Data Table
knio.output_tables[0] = knio.Table.from_pandas(df_out)

# Output Port 1: Audit & Documentation Table
knio.output_tables[1] = knio.Table.from_pandas(df_audit)