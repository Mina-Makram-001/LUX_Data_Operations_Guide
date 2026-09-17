# =============================================================================
# KNIME Python Script node: "Ingest"
# -----------------------------------------------------------------------------
# Thin glue only. All real logic lives in version control at:
#     <code_base_path>/utils/ingest.py   (function: ingest_folder)
#
# This node:
#   1. reads code_base_path + input_folder from flow variables (nothing hardcoded)
#   2. puts code_base_path on sys.path so the package is importable
#   3. imports utils.ingest and force-reloads it (defeats KNIME's stale-module cache)
#   4. calls ingest_folder(...) and writes the table to output port 0
# =============================================================================

import sys
import gc
import importlib

import knime.scripting.io as knio

# --- 1. Read everything from flow variables (no hardcoded paths or config) ----
fv = knio.flow_variables
code_base_path = fv["code_base_path"]      # e.g. \\AHMED-PC\...\data\src
input_folder = fv["input_folder"]          # folder of source .xlsx files

# Optional override: only used if the flow variable exists, else module default.
# Add `ingest_engine` the same way if you ever need to override the engine too.
sheet_name = fv["ingest_sheet_name"] if "ingest_sheet_name" in fv else "DATA"

# --- 2. Make the version-controlled package importable -----------------------
# code_base_path is the folder that *contains* the `utils` package, so appending
# it lets `import utils.ingest` resolve to <code_base_path>/utils/ingest.py.
if code_base_path not in sys.path:
    sys.path.append(code_base_path)

# --- 3. Import the module and force a reload ----------------------------------
# KNIME keeps the Python process (and sys.modules) alive between runs, so an
# edited .py would otherwise serve stale code. invalidate_caches() also lets a
# brand-new file be discovered without restarting KNIME.
importlib.invalidate_caches()
if "utils.ingest" in sys.modules:
    ingest = importlib.reload(sys.modules["utils.ingest"])
else:
    import utils.ingest as ingest

# --- 4. Run the core logic ----------------------------------------------------
result = ingest.ingest_folder(input_folder, sheet_name=sheet_name)

# --- 5. Surface an audit summary to the console + downstream nodes ------------
print(f"Ingest: read {len(result.files_read)} file(s), "
      f"{len(result.data)} row(s); {len(result.files_failed)} failure(s).")
for name, err in result.files_failed:
    print(f"  FAILED {name}: {err}")
if not result.files_read:
    print("WARNING: no files matched in input_folder -- output table is empty.")

# Expose counts as flow variables for downstream validation / logging.
knio.flow_variables["ingest_files_read"] = len(result.files_read)
knio.flow_variables["ingest_files_failed"] = len(result.files_failed)
knio.flow_variables["ingest_row_count"] = int(len(result.data))

# --- 6. Write the consolidated table to output port 0 -------------------------
knio.output_tables[0] = knio.Table.from_pandas(result.data)

del result
gc.collect()
