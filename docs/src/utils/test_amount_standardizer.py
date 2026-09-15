# =============================================================================
# UNIT TESTS: amount_standardizer
# PURPOSE: Validate standardization logic in isolation (no KNIME required)
#
# Run with: python -m pytest test_amount_standardizer.py -v
# =============================================================================

import pytest
import pandas as pd
from amount_standardizer import standardize_amounts, log_standardization_report


class TestStandardizeAmounts:
    """Test suite for the standardize_amounts function."""
    
    def test_basic_conversion(self):
        """Test basic string-to-float conversion."""
        df = pd.DataFrame({
            'Gross Amount': ['100.50', '200.00', '50.25'],
            'LA_SOURCE_FILE': ['file1', 'file1', 'file1']
        })
        
        std, summary, diag = standardize_amounts(
            df,
            amount_columns=['Gross Amount'],
            tracking_columns=['LA_SOURCE_FILE'],
            null_to_zero=True
        )
        
        assert std['Gross Amount'].tolist() == [100.50, 200.00, 50.25]
        assert summary.empty
        assert diag.empty
    
    def test_null_to_zero_enabled(self):
        """Test that empty/null cells become 0.0 when null_to_zero=True."""
        df = pd.DataFrame({
            'Amount': ['100', '', 'nan', None],
        })
        
        std, _, _ = standardize_amounts(
            df,
            amount_columns=['Amount'],
            tracking_columns=[],
            null_to_zero=True
        )
        
        # Empty, "nan", and None should all become 0.0
        assert std['Amount'].tolist() == [100.0, 0.0, 0.0, 0.0]
    
    def test_null_to_zero_disabled(self):
        """Test that empty/null cells remain NaN when null_to_zero=False."""
        df = pd.DataFrame({
            'Amount': ['100', '', 'nan'],
        })
        
        std, _, _ = standardize_amounts(
            df,
            amount_columns=['Amount'],
            tracking_columns=[],
            null_to_zero=False
        )
        
        # Empty and "nan" should remain NaN
        assert std['Amount'].iloc[0] == 100.0
        assert pd.isna(std['Amount'].iloc[1])
        assert pd.isna(std['Amount'].iloc[2])
    
    def test_comma_removal(self):
        """Test that commas in amounts are removed and parsed."""
        df = pd.DataFrame({
            'Amount': ['1,234.56', '10,000', '50,000.99'],
        })
        
        std, summary, _ = standardize_amounts(
            df,
            amount_columns=['Amount'],
            tracking_columns=[],
            null_to_zero=True
        )
        
        assert std['Amount'].tolist() == [1234.56, 10000.0, 50000.99]
        assert summary.empty
    
    def test_parse_failure_capture(self):
        """Test that unparseable values are captured in diagnostics."""
        df = pd.DataFrame({
            'Gross Amount': ['100', '-', 'N/A', '200'],
            'LA_SOURCE_FILE': ['file1', 'file1', 'file1', 'file1'],
            'LA_SOURCE_ROW': [1, 2, 3, 4]
        })
        
        std, summary, diag = standardize_amounts(
            df,
            amount_columns=['Gross Amount'],
            tracking_columns=['LA_SOURCE_FILE', 'LA_SOURCE_ROW'],
            null_to_zero=True
        )
        
        # Successfully parsed: 100 and 200; failures: "-" and "N/A"
        assert std['Gross Amount'].iloc[0] == 100.0
        assert std['Gross Amount'].iloc[3] == 200.0
        
        # Unparseable should be in summary
        assert len(summary) == 2
        raw_values = summary['Raw_Value'].tolist()
        assert '-' in raw_values
        assert 'N/A' in raw_values
        
        # Diagnostics should have 2 rows (one for each failure)
        assert len(diag) == 2
        assert 'Failed_Column' in diag.columns
        assert 'Raw_Value' in diag.columns
    
    def test_missing_column_ignored(self):
        """Test that missing amount columns are skipped gracefully."""
        df = pd.DataFrame({
            'Existing Amount': ['100', '200'],
        })
        
        std, summary, diag = standardize_amounts(
            df,
            amount_columns=['Existing Amount', 'NonExistent Amount'],
            tracking_columns=[],
            null_to_zero=True
        )
        
        # Should process the existing column and skip the missing one
        assert std['Existing Amount'].tolist() == [100.0, 200.0]
        assert summary.empty
    
    def test_multiple_amount_columns(self):
        """Test processing multiple amount columns simultaneously."""
        df = pd.DataFrame({
            'Gross': ['100', '200'],
            'Ceded': ['10', '-'],
            'LA_SOURCE_FILE': ['f1', 'f1']
        })
        
        std, summary, diag = standardize_amounts(
            df,
            amount_columns=['Gross', 'Ceded'],
            tracking_columns=['LA_SOURCE_FILE'],
            null_to_zero=True
        )
        
        # Gross should be fully parsed
        assert std['Gross'].tolist() == [100.0, 200.0]
        
        # Ceded should have one failure (the "-")
        assert std['Ceded'].iloc[0] == 10.0
        assert std['Ceded'].iloc[1] == 0.0
        
        # Diagnostics should capture the failed "-"
        assert len(summary) == 1
        assert summary['Raw_Value'].iloc[0] == '-'
    
    def test_whitespace_stripping(self):
        """Test that leading/trailing whitespace is handled."""
        df = pd.DataFrame({
            'Amount': [' 100 ', '  200.50  ', '  -  '],
        })
        
        std, summary, _ = standardize_amounts(
            df,
            amount_columns=['Amount'],
            tracking_columns=[],
            null_to_zero=True
        )
        
        # Whitespace should be stripped; valid amounts parsed
        assert std['Amount'].iloc[0] == 100.0
        assert std['Amount'].iloc[1] == 200.50
        
        # "-" with spaces should still fail to parse
        assert len(summary) == 1
    
    def test_none_input_raises(self):
        """Test that None input raises ValueError."""
        with pytest.raises(ValueError, match="data_df cannot be None"):
            standardize_amounts(
                data_df=None,
                amount_columns=['Amount'],
                tracking_columns=[],
            )
    
    def test_non_dataframe_input_raises(self):
        """Test that non-DataFrame input raises ValueError."""
        with pytest.raises(ValueError, match="must be a DataFrame"):
            standardize_amounts(
                data_df=[1, 2, 3],
                amount_columns=['Amount'],
                tracking_columns=[],
            )
    
    def test_empty_dataframe(self):
        """Test that empty input DataFrame is handled gracefully."""
        df = pd.DataFrame()
        
        std, summary, diag = standardize_amounts(
            df,
            amount_columns=['Amount'],
            tracking_columns=[],
            null_to_zero=True
        )
        
        # Should return empty frames with correct structure
        assert std.empty
        assert summary.empty
        assert diag.empty
    
    def test_summary_grouping_and_count(self):
        """Test that summary correctly groups by column/value and counts."""
        df = pd.DataFrame({
            'Amount': ['100', '-', '-', 'N/A', '-'],
            'LA_SOURCE_FILE': ['f1', 'f1', 'f1', 'f1', 'f1']
        })
        
        _, summary, _ = standardize_amounts(
            df,
            amount_columns=['Amount'],
            tracking_columns=['LA_SOURCE_FILE'],
            null_to_zero=True
        )
        
        # Should have 2 unique failures: "-" (count=3) and "N/A" (count=1)
        assert len(summary) == 2
        
        dash_row = summary[summary['Raw_Value'] == '-']
        assert dash_row['Count'].iloc[0] == 3
        
        na_row = summary[summary['Raw_Value'] == 'N/A']
        assert na_row['Count'].iloc[0] == 1


class TestLoggingFunction:
    """Test suite for log_standardization_report."""
    
    def test_log_empty_summary(self, capsys):
        """Test that empty summary prints success message."""
        summary_df = pd.DataFrame(columns=['Failed_Column', 'Raw_Value', 'Count'])
        
        log_standardization_report(summary_df)
        
        captured = capsys.readouterr()
        assert "SUCCESS" in captured.out
        assert "without errors" in captured.out
    
    def test_log_with_failures(self, capsys):
        """Test that failures are printed with proper formatting."""
        summary_df = pd.DataFrame({
            'Failed_Column': ['Gross Amount', 'Gross Amount'],
            'Raw_Value': ['-', 'N/A'],
            'Count': [3, 1]
        })
        
        log_standardization_report(summary_df)
        
        captured = capsys.readouterr()
        assert "DIAGNOSTICS REPORT" in captured.out
        assert "Gross Amount" in captured.out
        assert "-" in captured.out
        assert "N/A" in captured.out
    
    def test_log_none_input_raises(self):
        """Test that None input raises ValueError."""
        with pytest.raises(ValueError, match="must be a DataFrame"):
            log_standardization_report(None)
    
    def test_log_non_dataframe_input_raises(self):
        """Test that non-DataFrame input raises ValueError."""
        with pytest.raises(ValueError, match="must be a DataFrame"):
            log_standardization_report([1, 2, 3])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
