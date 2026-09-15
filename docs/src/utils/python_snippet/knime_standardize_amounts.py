import sys
import importlib
import traceback
import knime.scripting.io as knio
import pandas as pd

# Get code path from flow variable
code_base_path = knio.flow_variables.get('code_base_path')
if not code_base_path:
    raise ValueError("Flow variable 'code_base_path' not set.")

# Import and reload the module
if code_base_path not in sys.path:
    sys.path.insert(0, code_base_path)

try:
    import utils.amount_standardizer as amount_standardizer
    importlib.reload(amount_standardizer)
except ImportError as e:
    raise ImportError(f"Cannot import amount_standardizer from {code_base_path}: {e}")

# Read inputs
data_df = knio.input_tables[0].to_pandas()
amount_columns = knio.input_tables[1].to_pandas()["NEW"].tolist()

tracking_columns = [
    "LA_SOURCE_FILE",
    "LA_SOURCE_PAGE", 
    "LA_R_FILE_NAME",
    "LA_SOURCE_ROW"
]

# Call the standardization function
try:
    standardized_df, summary_df, diagnostics_df = amount_standardizer.standardize_amounts(
        data_df=data_df,
        amount_columns=amount_columns,
        tracking_columns=tracking_columns,
        null_to_zero=True
    )
    
    # Log results
    amount_standardizer.log_standardization_report(summary_df)
    
    # Write outputs
    knio.output_tables[0] = knio.Table.from_pandas(standardized_df)
    knio.output_tables[1] = knio.Table.from_pandas(summary_df)
    knio.output_tables[2] = knio.Table.from_pandas(diagnostics_df)
    
except Exception as e:
    print("ERROR: Node failed.")
    print(traceback.format_exc())
    raise
