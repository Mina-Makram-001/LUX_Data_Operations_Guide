"""
test_date_standardizer.py
=========================

Unit tests for date_standardizer.py.

Run locally with no special tools:
    python -m unittest test_date_standardizer -v

The most important test is `test_iso_dates_are_not_swapped`. It locks in the fix
for the day/month swap bug, where "2020-11-01" was being turned into
"2020-01-11" whenever the day was 12 or less.
"""

import unittest

import numpy as np
import pandas as pd

import date_standardizer as ds


class TestNoDaySwap(unittest.TestCase):
    """The core regression: ISO dates must never have day and month swapped."""

    def test_iso_dates_are_not_swapped(self):
        # Every value below has a day <= 12, the danger zone for swapping.
        raw = pd.Series(["2020-11-01", "2020-06-07", "2020-01-05", "2020-03-02"])
        _, parsed = ds.parse_date_series(raw)
        self.assertEqual(parsed.iloc[0], pd.Timestamp("2020-11-01"))
        self.assertEqual(parsed.iloc[1], pd.Timestamp("2020-06-07"))
        self.assertEqual(parsed.iloc[2], pd.Timestamp("2020-01-05"))
        self.assertEqual(parsed.iloc[3], pd.Timestamp("2020-03-02"))

    def test_iso_quarters_are_correct(self):
        raw = pd.Series(["2020-11-01", "2020-06-07", "2020-01-05"])
        _, parsed = ds.parse_date_series(raw)
        quarters = parsed.dt.to_period("Q").astype(str).tolist()
        self.assertEqual(quarters, ["2020Q4", "2020Q2", "2020Q1"])

    def test_compact_yyyymmdd_not_swapped(self):
        raw = pd.Series(["20201101", "20200607"])
        _, parsed = ds.parse_date_series(raw)
        self.assertEqual(parsed.iloc[0], pd.Timestamp("2020-11-01"))
        self.assertEqual(parsed.iloc[1], pd.Timestamp("2020-06-07"))


class TestFormats(unittest.TestCase):

    def test_european_slash_day_first(self):
        raw = pd.Series(["01/11/2020", "07/06/2020"])
        _, parsed = ds.parse_date_series(raw)
        self.assertEqual(parsed.iloc[0], pd.Timestamp("2020-11-01"))
        self.assertEqual(parsed.iloc[1], pd.Timestamp("2020-06-07"))

    def test_iso_with_time_is_normalized_to_midnight(self):
        raw = pd.Series(["2020-11-01 14:30:00"])
        _, parsed = ds.parse_date_series(raw)
        self.assertEqual(parsed.iloc[0], pd.Timestamp("2020-11-01 00:00:00"))

    def test_iso_t_separator(self):
        raw = pd.Series(["2020-11-01T09:15:00"])
        _, parsed = ds.parse_date_series(raw)
        self.assertEqual(parsed.iloc[0], pd.Timestamp("2020-11-01"))


class TestMissingAndJunk(unittest.TestCase):

    def test_missing_tokens_become_nat_and_are_flagged_missing(self):
        raw = pd.Series(["", "nan", "None", "<NA>", None])
        original_missing, parsed = ds.parse_date_series(raw)
        self.assertTrue(parsed.isna().all())
        self.assertTrue(original_missing.all())

    def test_invalid_month_fails_instead_of_swapping(self):
        # 13 is not a valid month. The honest result is NaT, not a swap.
        raw = pd.Series(["2020-13-01"])
        original_missing, parsed = ds.parse_date_series(raw)
        self.assertTrue(parsed.isna().all())
        self.assertFalse(original_missing.iloc[0])  # it was present, just unparseable

    def test_pure_text_fails(self):
        raw = pd.Series(["hello", "world"])
        _, parsed = ds.parse_date_series(raw)
        self.assertTrue(parsed.isna().all())

    def test_excel_serial_numbers_fail_loudly(self):
        # Numeric serials are NOT silently converted. They fail and get reported.
        raw = pd.Series([44136, 44137])
        _, parsed = ds.parse_date_series(raw)
        self.assertTrue(parsed.isna().all())


class TestCleaning(unittest.TestCase):

    def test_whitespace_is_trimmed_and_collapsed(self):
        raw = pd.Series(["  2020-11-01  ", "2020-06-07"])
        _, parsed = ds.parse_date_series(raw)
        self.assertEqual(parsed.iloc[0], pd.Timestamp("2020-11-01"))

    def test_arabic_pm_marker_is_translated(self):
        # The Arabic PM marker should not break parsing of the date part.
        raw = pd.Series(["2020-11-01 02:30:00 م"])
        _, parsed = ds.parse_date_series(raw)
        # Date part must still be recovered and normalized to midnight.
        self.assertEqual(parsed.iloc[0], pd.Timestamp("2020-11-01"))


class TestUniqueOptimization(unittest.TestCase):

    def test_duplicates_map_back_to_correct_rows(self):
        raw = pd.Series(["2020-11-01", "2020-11-01", "2020-06-07", "2020-11-01"])
        _, parsed = ds.parse_date_series(raw)
        self.assertEqual(parsed.iloc[0], pd.Timestamp("2020-11-01"))
        self.assertEqual(parsed.iloc[1], pd.Timestamp("2020-11-01"))
        self.assertEqual(parsed.iloc[2], pd.Timestamp("2020-06-07"))
        self.assertEqual(parsed.iloc[3], pd.Timestamp("2020-11-01"))

    def test_index_is_preserved(self):
        raw = pd.Series(["2020-11-01", "2020-06-07"], index=[10, 20])
        _, parsed = ds.parse_date_series(raw)
        self.assertListEqual(list(parsed.index), [10, 20])


class TestStandardizeDates(unittest.TestCase):

    def _frame(self):
        return pd.DataFrame({
            "LA_LOSS_DATE": ["2020-11-01", "2020-06-07", "bad-date", None],
            "LA_SOURCE_FILE": ["a.xlsx", "a.xlsx", "b.xlsx", "b.xlsx"],
            "LA_SOURCE_ROW": [1, 2, 3, 4],
            "amount": [100, 200, 300, 400],
        })

    def test_backup_and_status_columns_created(self):
        res = ds.standardize_dates(self._frame(), ["LA_LOSS_DATE"])
        self.assertIn("LA_LOSS_DATE_old", res.data.columns)
        self.assertIn("LA_LOSS_DATE_status", res.data.columns)

    def test_status_codes(self):
        res = ds.standardize_dates(self._frame(), ["LA_LOSS_DATE"])
        status = res.data["LA_LOSS_DATE_status"].tolist()
        # rows: ok, ok, failed(2), both-missing(3)
        self.assertEqual(status, [ds.STATUS_OK, ds.STATUS_OK,
                                  ds.STATUS_FAILED, ds.STATUS_BOTH_MISSING])

    def test_failed_value_appears_in_summary_and_diagnostics(self):
        res = ds.standardize_dates(self._frame(), ["LA_LOSS_DATE"])
        self.assertIn("bad-date", res.summary["Raw_Value"].astype(str).tolist())
        self.assertIn("bad-date", res.diagnostics["Raw_Value"].astype(str).tolist())
        # tracking columns carried through
        self.assertIn("LA_SOURCE_FILE", res.diagnostics.columns)
        self.assertEqual(res.diagnostics["LA_SOURCE_FILE"].iloc[0], "b.xlsx")

    def test_clean_column_produces_empty_reports(self):
        df = pd.DataFrame({"LA_LOSS_DATE": ["2020-11-01", "2020-06-07"]})
        res = ds.standardize_dates(df, ["LA_LOSS_DATE"])
        self.assertTrue(res.summary.empty)
        self.assertTrue(res.diagnostics.empty)

    def test_missing_column_is_skipped(self):
        res = ds.standardize_dates(self._frame(), ["NOT_A_COLUMN"])
        self.assertNotIn("NOT_A_COLUMN_status", res.data.columns)

    def test_input_frame_not_mutated(self):
        df = self._frame()
        before = df["LA_LOSS_DATE"].tolist()
        ds.standardize_dates(df, ["LA_LOSS_DATE"])
        self.assertEqual(df["LA_LOSS_DATE"].tolist(), before)

    def test_already_datetime_column_passthrough(self):
        df = pd.DataFrame({"LA_LOSS_DATE": pd.to_datetime(
            ["2020-11-01 10:00", "2020-06-07 23:00"])})
        res = ds.standardize_dates(df, ["LA_LOSS_DATE"])
        self.assertEqual(res.data["LA_LOSS_DATE"].iloc[0], pd.Timestamp("2020-11-01"))
        self.assertEqual(res.data["LA_LOSS_DATE"].iloc[1], pd.Timestamp("2020-06-07"))

    def test_non_dataframe_raises(self):
        with self.assertRaises(TypeError):
            ds.standardize_dates(["not", "a", "frame"], ["x"])


class TestUSConventionOverride(unittest.TestCase):
    """A source that uses US month-first slash dates needs its own format list."""

    def test_custom_format_list_for_us_dates(self):
        us_formats = ["%m/%d/%Y"]
        raw = pd.Series(["03/05/2020"])  # US: 5 March
        _, parsed = ds.parse_date_series(raw, date_formats=us_formats)
        self.assertEqual(parsed.iloc[0], pd.Timestamp("2020-03-05"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
