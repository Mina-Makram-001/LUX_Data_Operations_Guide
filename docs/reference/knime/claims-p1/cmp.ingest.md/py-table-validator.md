
::: utils.hc_table_validator

## 💡 How It Works

The script operates in three main steps to process the incoming dataset:

!!! info "Step 1: Configuration &amp; File Loading"
    * Reads the main dataset from **Input Port 0**.
    * Fetches the reference schema path from the `control_setting` Flow Variable.
    * Loads the `Table_Structure` sheet from the external Excel file.

!!! abstract "Step 2: Column Matching &amp; Reshaping"
    1. **Reference Check (Phase A):** Loops through the reference schema columns.
        * **Found:** Keeps the column and records `"Found and retained"`.
        * **Missing:** Creates a new column filled with `pd.NA` (cast as string) and records `"Not found, created with missing (String)"`.
    2. **Extra Columns Check (Phase B):** Checks columns that exist in the main table but not in the reference schema.
        * If `REMOVE_UNMATCHED_COLUMNS = True`: Drops extra columns and records `"Found and removed"`.
        * If `REMOVE_UNMATCHED_COLUMNS = False`: Appends extra columns to the end and records `"Found, not in reference, appended to end"`.

!!! success "Step 3: Output Delivery"
    * Reorders the main dataset to match the final schema and sends it to **Output Port 0**.
    * Generates the audit log DataFrame and sends it to **Output Port 1**.

### 📊 Audit Log Output Example

The second output port generates a table structured like this:

| Column_Name | Status |
| :--- | :--- |
| `Customer_ID` | Found and retained |
| `Email_Address` | Not found, created with missing (String) |
| `Internal_Note` | Found and removed |

---

## ⚠️ Important Notes

!!! warning "Sheet Name Requirement"
    The reference Excel file must contain a sheet named `Table_Structure`. Otherwise, the script will raise a `ValueError`.

!!! tip "Data Type Handling"
    Newly created missing columns are cast as `string` by default. If your downstream pipeline expects specific data types (like `Integer` or `Date`), use standard KNIME nodes to convert them afterwards.

