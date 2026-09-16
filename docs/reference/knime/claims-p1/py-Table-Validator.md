import knime.scripting.io as knio
import pandas as pd

# =============================================================================
# CONFIGURATION
# =============================================================================
# True: Drops columns from Input 1 that are NOT in the Reference Table.
# False: Keeps them, but appends them to the very end of the table.
# (Tip: You can replace 'True' with knio.flow_variables['your_boolean_var'] 
# if you turn this into a KNIME component!)
REMOVE_UNMATCHED_COLUMNS = True

# =============================================================================
# 1. READ INPUT TABLES
# =============================================================================
# Input Port 1: The data table to be restructured
df_main = knio.input_tables[0].to_pandas()



# Input Port 2: The reference table (Scenario A: Headers dictate the standard)
# df_ref = knio.input_tables[1].to_pandas()
config_file_path = knio.flow_variables['control_setting']
df_ref = pd.read_excel(config_file_path, sheet_name="Table_Structure")

# Extract column lists
main_cols = df_main.columns.tolist()
ref_cols = df_ref.columns.tolist()

# =============================================================================
# 2. COMPARE AND RESHAPE
# =============================================================================
final_cols_order = []
audit_log = []

# Phase A: Process strictly according to the Reference Table order
for col in ref_cols:
    if col in main_cols:
        final_cols_order.append(col)
        audit_log.append({
            "Column_Name": col, 
            "Status": "Found and retained"
        })
    else:
        # Create column filled with Missing values, explicitly cast as String
        df_main[col] = pd.NA
        df_main[col] = df_main[col].astype('string')
        
        final_cols_order.append(col)
        audit_log.append({
            "Column_Name": col, 
            "Status": "Not found, created with missing (String)"
        })

# Phase B: Handle columns that exist in the Main Table but NOT in the Reference Table
extra_cols = [col for col in main_cols if col not in ref_cols]

if REMOVE_UNMATCHED_COLUMNS:
    for col in extra_cols:
        audit_log.append({
            "Column_Name": col, 
            "Status": "Found and removed"
        })
else:
    for col in extra_cols:
        final_cols_order.append(col)  # Appends to the end
        audit_log.append({
            "Column_Name": col, 
            "Status": "Found, not in reference, appended to end"
        })

# Apply the final column selection and ordering
df_out = df_main[final_cols_order]

# Create the documentation/audit dataframe
df_audit = pd.DataFrame(audit_log)

# =============================================================================
# 3. WRITE TO OUTPUT PORTS
# =============================================================================
# Output Port 1: Restructured Data Table
knio.output_tables[0] = knio.Table.from_pandas(df_out)

# Output Port 2: Audit/Documentation Table
knio.output_tables[1] = knio.Table.from_pandas(df_audit)