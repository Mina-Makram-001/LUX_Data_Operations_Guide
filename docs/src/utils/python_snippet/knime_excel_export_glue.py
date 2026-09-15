import knime.scripting.io as knio
import pandas as pd
import sys
import importlib

# --- Block 1: Configuration Setup ---
# Loads settings from Control Settings, filters to this SheetNum, builds a dict.
target_sheet_num = knio.flow_variables["target_sheet_number"]
config_file_path = knio.flow_variables['control_setting']
config_df = pd.read_excel(config_file_path, sheet_name="Output_Sheets_Config")
filtered_config = config_df[config_df['SheetNum'] == target_sheet_num]
CONFIG = filtered_config.set_index("Setting")["Value"].to_dict()

# Optional override: a flow variable wins over the per-sheet config row.
# Accepts TRUE/FALSE, yes/no, 1/0. If neither is set, the engine defaults to
# formatting ON. Set it to FALSE to dump big sheets fast with no styling.
if 'apply_formatting' in knio.flow_variables:
    CONFIG['apply_formatting'] = knio.flow_variables['apply_formatting']


# --- Block 2: Load the engine from the repo (always the live file) ---
code_base_path = knio.flow_variables['code_base_path']
if code_base_path not in sys.path:
    sys.path.append(code_base_path)
import utils.excel_export as excel_export
importlib.reload(excel_export)


# --- Block 3: Resolve the configuration ---
# Coerces types/defaults (incl. apply_formatting -> bool) and builds the path.
CONFIG = excel_export.apply_config_defaults(CONFIG)
CONFIG["file_path"] = excel_export.build_output_path(
    target_folder=CONFIG["target_folder"],
    company=knio.flow_variables["company"],
    file_name=CONFIG["file_name"],
    run_timestamp=knio.flow_variables["run_timestamp"],
)


# --- Block 4: Get and prepare the data ---
df = knio.input_tables[0].to_pandas()
df = excel_export.handle_empty_dataset(df)
df = excel_export.clean_date_columns(df)


# --- Block 5: Write the Excel file ---
# New file  -> xlsxwriter (fast, column-level formatting).
# Existing  -> openpyxl append. Styling is skipped when apply_formatting is off.
file_path = excel_export.generate_formatted_excel(df, CONFIG)


# --- Block 6: Outputs back to KNIME ---
# knio.output_tables[0] = knio.input_tables[0]
knio.flow_variables['my_exported_file_path'] = file_path
knio.flow_variables['my_exported_sheet_name'] = CONFIG["sheet_name"]
