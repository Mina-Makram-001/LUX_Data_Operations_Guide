import datetime

import knime.scripting.io as knio
import pandas as pd
import os
import re
import glob
import sys
import importlib

# --- Block 1: Flow variables -------------------------------------------------
# Config workbook + repo root + the folder holding the DQR##.parquet files.
config_file_path = knio.flow_variables["control_setting"]
code_base_path = knio.flow_variables["code_base_path"]
# parquet_folder = knio.flow_variables["parquet_input_folder"]
parquet_folder = knio.flow_variables.get("parquet_input_folder", r"..\..\03 Out of Knime\00 Process")
company = knio.flow_variables.get("company", "Company")
run_timestamp = knio.flow_variables.get("run_timestamp", "")

# Reconciliation tolerances + colours (engine defaults used if absent).
recon_config = {
    "tolerance_abs": float(knio.flow_variables.get("tolerance_abs", 1000.0)),
    "tolerance_pct": float(knio.flow_variables.get("tolerance_pct", 0.005)),
    "error_bg_color": knio.flow_variables.get("error_bg_color", "FFC7CE"),
    "error_font_color": knio.flow_variables.get("error_font_color", "9C0006"),
    "null_bg_color": knio.flow_variables.get("null_bg_color", "D9D9D9"),
}


# --- Block 2: Load the engine from the repo (always the live file) -----------
if code_base_path not in sys.path:
    sys.path.append(code_base_path)
import utils.reporting_engine as reporting_engine
importlib.reload(reporting_engine)


# --- Block 3: Read configuration sheets --------------------------------------
details_df = pd.read_excel(config_file_path, sheet_name="Output_Sheets_Details")
config_df = pd.read_excel(config_file_path, sheet_name="Output_Sheets_Config")

# Sheet ID -> {Setting: Value} mapping for per-sheet visual styling.
raw_configs = {
    sid: grp.set_index("Setting")["Value"].to_dict()
    for sid, grp in config_df.groupby("SheetNum")
}

# Build the output path from the (shared) file_name / target_folder in config.
first_cfg = next(iter(raw_configs.values()))
file_path = f"..\\..\\{first_cfg['target_folder']}\\{company} {first_cfg['file_name']} {run_timestamp}.xlsx"


# --- Block 4: Read DQR##.parquet files from the folder -----------------------
# Match only files named DQRnn.parquet (DQR01..DQR17). Map to Sheet IDs.
frames = {}
pattern = re.compile(r"^(DQR\d{2})\.parquet$", re.IGNORECASE)
for path in sorted(glob.glob(os.path.join(parquet_folder, "*.parquet"))):
    m = pattern.match(os.path.basename(path))
    if not m:
        continue
    sid = m.group(1).upper()
    if sid in raw_configs:          # ignore DQR00 / anything not in the config
        frames[sid] = pd.read_parquet(path)


# --- Block 5: Assemble metadata sheets (in memory) ---------------------------
existing_ids = set(frames.keys())

audit_rows = reporting_engine.build_audit_rows({
    "run_id": knio.flow_variables.get("run_id"),
    "run_timestamp": knio.flow_variables.get("p1_start",f"{run_timestamp}"),
    "operator": knio.flow_variables.get("user"),
    "machine": os.environ.get("COMPUTERNAME", knio.flow_variables.get("machine", "N/A")),
    "company": company,
    "valuation_date": knio.flow_variables.get("valuation_date"),
    "reporting_year": knio.flow_variables.get("reporting_year", ""),
    "reporting_quarter": knio.flow_variables.get("reporting_quarter", ""),
    "data_type": knio.flow_variables.get("data_type"),
    "data_scope": knio.flow_variables.get("data_scope"),
    "database_filename": knio.flow_variables.get("database_filename"),
    "ingest_files_read": knio.flow_variables.get("ingest_files_read", "N/A"),
    "ingest_files_failed": knio.flow_variables.get("ingest_files_failed", "N/A"),
    "ingest_row_count": knio.flow_variables.get("ingest_row_count", "N/A"),
    "recon_date_variable": knio.flow_variables.get("recon_date_variable"),
    "tolerance_pct": recon_config["tolerance_pct"],
    "tolerance_abs": recon_config["tolerance_abs"],
    "p1s": knio.flow_variables.get("p1_start", f"{run_timestamp}"),
    "p1e": knio.flow_variables.get("p1_end", ""),
    "p2s": knio.flow_variables.get("p2_start", ""),
    "p2e": knio.flow_variables.get("p2_end", f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
})

toc_rows = reporting_engine.build_toc_rows(details_df, existing_ids)
ordered_sheets = reporting_engine.build_ordered_sheets(details_df, raw_configs, frames)


# --- Block 6: Build the whole workbook in ONE pass ---------------------------
file_path = reporting_engine.build_report_workbook(
    file_path=file_path,
    ordered_sheets=ordered_sheets,
    toc_rows=toc_rows,
    audit_rows=audit_rows,
    recon_config=recon_config,
)


# --- Block 7: Outputs back to KNIME ------------------------------------------
knio.flow_variables["my_exported_file_path"] = file_path
# knio.output_tables[0] = knio.Table.from_pandas(
#     pd.DataFrame({"Status": ["Success"], "Sheets": [len(ordered_sheets)], "File": [file_path]})
# )
