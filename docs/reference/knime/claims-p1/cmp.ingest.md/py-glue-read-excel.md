::: utils.glue_read_excel

# 💡 How It Works

This KNIME Python Script node serves as a **thin wrapper (glue layer)** that delegates all batch ingestion and file parsing logic to the version-controlled `utils.ingest` module.

The script operates in six sequential steps:

!!! info "Step 1: Flow Variable Resolution"
    * Reads `code_base_path` (path containing the `utils` Python package) and `data_folder_path` (directory containing source `.xlsx` files) from KNIME Flow Variables.
    * Checks for an optional `ingest_sheet_name` Flow Variable (defaults to `"DATA"` if not provided).

!!! abstract "Step 2: Dynamic Module Resolution & Fresh Import"
    1. **System Path Check:** Appends `code_base_path` to `sys.path` if not already present.
    2. **Cache Invalidation:** Runs `importlib.invalidate_caches()` to discover newly added module files.
    3. **Force Reload:** Force-reloads `utils.ingest` via `importlib.reload()` to bypass KNIME's persistent Python process and stale module caching.

!!! success "Step 3: Ingestion Execution & Data Consolidation"
    * Calls `ingest.ingest_folder(input_folder, sheet_name=sheet_name)`.
    * Reads and concatenates all matching Excel files into a consolidated DataFrame returned within the `result` object.

!!! note "Step 4: Audit Summary & Console Logging"
    * Prints execution metrics to the console: total files read, row count, and failed files.
    * Iterates through `result.files_failed` and logs specific failure errors.
    * Issues a warning if no files matched the criteria.

!!! tip "Step 5: Exporting Metrics to Flow Variables"
    Exposes execution metrics to downstream KNIME nodes via Flow Variables:
    * `ingest_files_read`: Number of successfully parsed Excel files.
    * `ingest_files_failed`: Number of files that encountered errors.
    * `ingest_row_count`: Total consolidated row count written to the pipeline.

!!! success "Step 6: Output Table Delivery & Memory Cleanup"
    * Converts `result.data` to a KNIME Table and assigns it to **Output Port 0**.
    * Deletes the `result` object and invokes garbage collection (`gc.collect()`) to prevent memory leaks.

---

## ⚙️ Flow Variables Reference

### Inputs (Read by Node)

| Variable Name | Type | Required | Description | Example Value |
| :--- | :--- | :--- | :--- | :--- |
| `code_base_path` | String | **Yes** | Root directory containing the `utils` package. | `\\SERVER\path\to\src` |
| `data_folder_path` | String | **Yes** | Target directory containing input Excel files. | `\\SERVER\path\to\data` |
| `ingest_sheet_name` | String | Optional | Excel sheet name to target during ingestion. | `"DATA"` (Default) |

### Outputs (Exported by Node)

| Variable Name | Type | Description |
| :--- | :--- | :--- |
| `ingest_files_read` | Integer | Count of Excel files successfully read and concatenated. |
| `ingest_files_failed` | Integer | Count of Excel files that failed during processing. |
| `ingest_row_count` | Integer | Total number of rows written to the output stream. |

---

## 🔌 Node Ports

| Port | Type | Direction | Description |
| :--- | :--- | :--- | :--- |
| **Output Port 0** | Data Table | Output | Consolidated Pandas DataFrame containing all ingested claim records. |

---

## ⚠️ Important Notes

!!! warning "Version Control Architecture"
    Do **not** place core parsing logic directly inside this KNIME node. Modifications to the ingestion rules should be committed directly to `utils/ingest.py` in your Git repository.

!!! tip "Stale Module Prevention"
    The inclusion of `importlib.invalidate_caches()` and `importlib.reload()` guarantees that edits made to `utils/ingest.py` take effect immediately upon execution without needing to restart the KNIME Analytics Platform.