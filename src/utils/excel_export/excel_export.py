"""Formatted Excel export engine.

Pure, version-controlled logic for writing a pandas DataFrame to an Excel sheet,
optionally styled (title, description, table grid, auto-sized columns, frozen
header). Contains NO KNIME imports so it can be unit-tested locally with pandas.
The KNIME node is a thin glue script that reads the configuration, imports this
module, and calls the functions below.

Why this module was rewritten (performance)
--------------------------------------------
The original version always wrote through ``openpyxl`` and, when the target
workbook already existed, opened it in append mode. Two things made that slow:

  1. APPEND RELOAD. ``ExcelWriter(mode="a")`` makes openpyxl read, re-build in
     memory, and re-serialise the WHOLE workbook on every call. The cost scales
     with the total size of the workbook, not the size of the sheet being added.
     Appending a 10-row sheet to a workbook that already holds a 300k-row sheet
     pays the full 300k-row reload every time -- this is the "2.5 minutes for a
     tiny sheet" symptom (worse over a UNC share).

  2. PER-CELL NUMBER FORMAT. Styling walked every data cell to set a number
     format. At 300k rows x N float columns that is millions of style writes.

Fixes applied here
------------------
  * ``apply_formatting`` flag (default True). When False, the data is dumped
    with no styling -- the fast path for big sheets.
  * NEW files are written with ``xlsxwriter``, which streams rows and lets us
    set number formats and widths once PER COLUMN (``set_column``) instead of
    per cell. This is the "export first, format with column-level calls"
    approach and removes the per-cell loop entirely.
  * EXISTING files still go through openpyxl (xlsxwriter cannot append). The
    append reload is intrinsic to that mode; the genuine cure is to not append a
    small sheet into a workbook that holds a huge sheet -- see the module guide
    / give large sheets their own ``file_name`` so they are written fresh.

Public API (unchanged names, so the glue keeps working):
    apply_config_defaults, build_output_path, handle_empty_dataset,
    clean_date_columns, generate_formatted_excel
plus the new helper ``parse_bool`` used to read the formatting flag.
"""

import os
import datetime

import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


# --------------------------------------------------------------------------- #
# Config helpers
# --------------------------------------------------------------------------- #
def parse_bool(value, default=True):
    """Interpret a config/flow value as a boolean.

    Accepts real booleans, numbers, and the usual spreadsheet spellings
    (``"true"/"false"``, ``"yes"/"no"``, ``"y"/"n"``, ``"1"/"0"``,
    ``"on"/"off"``). Anything missing, blank, or unrecognised falls back to
    ``default`` -- so a sheet with no ``apply_formatting`` setting is formatted.

    Parameters
    ----------
    value : Any
        Raw value from ``Output_Sheets_Config`` or a flow variable. ``None`` and
        pandas ``NaN`` both count as "missing".
    default : bool
        Value to return when ``value`` is missing or unrecognised.

    Returns
    -------
    bool
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    # pandas NaN (float) -> missing
    if isinstance(value, float) and pd.isna(value):
        return default
    if isinstance(value, (int,)):
        return value != 0
    text = str(value).strip().lower()
    if text == "":
        return default
    if text in ("true", "t", "yes", "y", "1", "on"):
        return True
    if text in ("false", "f", "no", "n", "0", "off"):
        return False
    return default


def apply_config_defaults(config):
    """Coerce types and fill in missing formatting settings on a config dict.

    The raw config comes from the ``Output_Sheets_Config`` sheet as strings.
    This makes a copy, converts the few non-string settings, normalises the
    ``apply_formatting`` flag to a real bool, and supplies fallback colours so
    downstream styling never hits a missing key.

    Parameters
    ----------
    config : dict
        Raw settings (``Setting`` -> ``Value``). Not mutated.

    Returns
    -------
    dict
        New dict with ``table_start_row`` (int), ``show_gridlines`` (bool),
        ``apply_formatting`` (bool, default True), the four font/border colours,
        and ``date_number_format`` guaranteed present.

    Raises
    ------
    KeyError
        If the required ``table_start_row`` setting is absent.
    ValueError
        If ``table_start_row`` cannot be parsed as an integer.
    """
    cfg = dict(config)

    cfg["table_start_row"] = int(cfg["table_start_row"])

    if isinstance(cfg.get("show_gridlines"), str):
        cfg["show_gridlines"] = cfg["show_gridlines"].strip().lower() == "true"

    # New: master formatting switch. Missing -> formatted (True).
    cfg["apply_formatting"] = parse_bool(cfg.get("apply_formatting"), default=True)

    cfg["header_font_color"] = cfg.get("header_font_color", "FFFFFF")
    cfg["table_border_color"] = cfg.get("table_border_color", "000000")
    cfg["desc_font_color"] = cfg.get("desc_font_color", "595959")
    cfg["title_font_color"] = cfg.get("title_font_color", "000000")
    cfg["float_number_format"] = cfg.get("float_number_format", "0.00")
    cfg["date_number_format"] = cfg.get("date_number_format", "yyyy-mm-dd")

    return cfg


def build_output_path(target_folder, company, file_name, run_timestamp):
    """Build the relative output path for the exported workbook.

    Mirrors the original convention: two levels up from the workflow working
    directory, into ``target_folder``, with a file name made from the company,
    base file name, and run timestamp.

    Returns
    -------
    str
        e.g. ``..\\..\\Output\\ACME Premium Report 20260624_1200.xlsx``.
    """
    return f"..\\..\\{target_folder}\\{company} {file_name} {run_timestamp}.xlsx"


def handle_empty_dataset(df):
    """Return a placeholder one-row frame when the input has no rows."""
    if df.empty:
        out = df.copy()
        out.loc[0] = ["No data available."] + [None] * (len(out.columns) - 1)
        return out
    return df


def clean_date_columns(df):
    """Convert timestamp-like columns to plain dates, on a copy.

    A column is treated as a date column if its first non-null value is a
    Timestamp/datetime, or a string containing ``"00:00:00"``. Uses
    ``first_valid_index`` so only one value is inspected per column.
    """
    out = df.copy()
    for col in out.columns:
        try:
            valid_idx = out[col].first_valid_index()
            if valid_idx is not None:
                first_valid = out[col].loc[valid_idx]
                if isinstance(first_valid, (pd.Timestamp, datetime.datetime)) or (
                    isinstance(first_valid, str) and "00:00:00" in first_valid
                ):
                    out[col] = pd.to_datetime(out[col]).dt.date
        except Exception:
            pass
    return out


# --------------------------------------------------------------------------- #
# Column metadata (shared by both engines)
# --------------------------------------------------------------------------- #
def _is_date_column(series):
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    idx = series.first_valid_index()
    return idx is not None and isinstance(series.loc[idx], datetime.date)


def _column_plan(df, config):
    """Compute per-column (width, kind) once, vectorised.

    kind is one of ``"float"``, ``"date"``, ``"other"``. Width mirrors the
    original auto-sizer (header length vs a 1000-row sample), so the visual
    result matches the previous node.
    """
    plan = []
    for col_name in df.columns:
        series = df[col_name]
        max_len = len(str(col_name)) * 1.3
        kind = "other"

        if pd.api.types.is_float_dtype(series):
            kind = "float"
        elif _is_date_column(series):
            kind = "date"

        sample = series.head(1000).dropna()
        if not sample.empty:
            if kind == "float":
                lens = sample.astype("int64", errors="ignore").astype(str).str.len()
                lens = lens + (lens // 3) + 3  # thousands separators + decimals
                max_len = max(max_len, int(lens.max()))
            elif kind == "date":
                max_len = max(max_len, 10)
            else:
                max_len = max(max_len, int(sample.astype(str).str.len().max()))

        plan.append((max_len + 4, kind))
    return plan


# --------------------------------------------------------------------------- #
# Engine entry point
# --------------------------------------------------------------------------- #
def generate_formatted_excel(df, config):
    """Write ``df`` to an Excel sheet and return the file path.

    Routing:
      * file does NOT exist  -> xlsxwriter (fast, streaming, column-level
        formatting). This is the common case for the first/own-file sheet.
      * file DOES exist       -> openpyxl append (required for multi-sheet
        workbooks).

    In both cases styling is skipped entirely when
    ``config["apply_formatting"]`` is False.

    Parameters
    ----------
    df : pandas.DataFrame
        Data to write (already cleaned/empty-handled by the caller).
    config : dict
        Resolved settings (see :func:`apply_config_defaults`) plus
        ``file_path``, ``sheet_name``, ``font_name``, ``header_bg``,
        ``title_text``/``desc_text`` and related keys.

    Returns
    -------
    str
        ``config["file_path"]`` -- the path of the workbook written.
    """
    apply_fmt = bool(config.get("apply_formatting", True))

    if os.path.exists(config["file_path"]):
        _export_openpyxl_append(df, config, apply_fmt)
    else:
        _export_xlsxwriter_new(df, config, apply_fmt)

    return config["file_path"]


# --------------------------------------------------------------------------- #
# Fast path: brand-new workbook via xlsxwriter
# --------------------------------------------------------------------------- #
def _export_xlsxwriter_new(df, config, apply_fmt):
    sheet = config["sheet_name"]
    start = config["table_start_row"]            # 1-based row of the header
    fp = config["file_path"]

    if not apply_fmt:
        # Plain dump: header on the configured row, no styling. Fastest path.
        with pd.ExcelWriter(fp, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name=sheet, startrow=start - 1)
        return

    with pd.ExcelWriter(
        fp,
        engine="xlsxwriter",
        engine_kwargs={"options": {"constant_memory": False}},
        datetime_format=config["date_number_format"],
        date_format=config["date_number_format"],
    ) as writer:
        # Data only (no header); first data row sits directly under the header.
        df.to_excel(
            writer, index=False, header=False, sheet_name=sheet, startrow=start
        )
        wb = writer.book
        ws = writer.sheets[sheet]
        _style_xlsxwriter(wb, ws, df, config)


def _style_xlsxwriter(wb, ws, df, config):
    fn = config["font_name"]
    start = config["table_start_row"]            # 1-based header row
    header_row0 = start - 1                       # 0-based

    title_fmt = wb.add_format({
        "font_name": fn, "bold": True, "font_size": 18,
        "font_color": "#" + config["title_font_color"],
        "align": "left", "valign": "vcenter", "bottom": 5,
        "bottom_color": "#" + config["title_font_color"],
    })
    if config.get("title_bg_color"):
        title_fmt.set_bg_color("#" + config["title_bg_color"])
    ws.set_row(0, 30)
    ws.write(0, 0, config.get("title_text", "Report Title"), title_fmt)

    if config.get("desc_text"):
        desc_fmt = wb.add_format({
            "font_name": fn, "italic": True, "font_size": 11,
            "font_color": "#" + config["desc_font_color"],
            "align": "left", "valign": "vcenter", "bottom": 6,
            "bottom_color": "#" + config["desc_font_color"],
        })
        if config.get("desc_bg_color"):
            desc_fmt.set_bg_color("#" + config["desc_bg_color"])
        ws.set_row(1, 20)
        ws.write(1, 0, config["desc_text"], desc_fmt)

    header_fmt = wb.add_format({
        "font_name": fn, "bold": True,
        "font_color": "#" + config["header_font_color"],
        "bg_color": "#" + config["header_bg"],
        "align": "center", "valign": "vcenter", "border": 1,
        "border_color": "#" + config["table_border_color"],
    })
    for col_idx, col_name in enumerate(df.columns):
        ws.write(header_row0, col_idx, str(col_name), header_fmt)

    # ONE format object per kind, applied per COLUMN (not per cell).
    float_fmt = wb.add_format({"font_name": fn, "num_format": config["float_number_format"]})
    date_fmt = wb.add_format({"font_name": fn, "num_format": config["date_number_format"]})
    plain_fmt = wb.add_format({"font_name": fn})

    for col_idx, (width, kind) in enumerate(_column_plan(df, config)):
        cell_fmt = float_fmt if kind == "float" else date_fmt if kind == "date" else plain_fmt
        ws.set_column(col_idx, col_idx, width, cell_fmt)

    ws.hide_gridlines(0 if config["show_gridlines"] else 2)
    ws.freeze_panes(start, 0)   # freeze title + description + header rows


# --------------------------------------------------------------------------- #
# Append path: existing workbook via openpyxl
# --------------------------------------------------------------------------- #
def _export_openpyxl_append(df, config, apply_fmt):
    with pd.ExcelWriter(
        config["file_path"], engine="openpyxl", mode="a", if_sheet_exists="replace"
    ) as writer:
        df.to_excel(
            writer,
            index=False,
            sheet_name=config["sheet_name"],
            startrow=config["table_start_row"] - 1,
        )
        if apply_fmt:
            _style_openpyxl(writer.sheets[config["sheet_name"]], df, config)


def _style_openpyxl(ws, df, config):
    fn = config["font_name"]
    start = config["table_start_row"]

    # --- Title ---
    ws["A1"] = config.get("title_text", "Report Title")
    ws["A1"].font = Font(name=fn, size=18, bold=True, color=config["title_font_color"])
    if config.get("title_bg_color"):
        ws["A1"].fill = PatternFill(start_color=config["title_bg_color"], end_color=config["title_bg_color"], fill_type="solid")
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws["A1"].border = Border(bottom=Side(style="thick", color=config["title_font_color"]))
    ws.row_dimensions[1].height = 30

    # --- Description (optional) ---
    if config.get("desc_text"):
        ws["A2"] = config["desc_text"]
        ws["A2"].font = Font(name=fn, size=11, italic=True, color=config["desc_font_color"])
        if config.get("desc_bg_color"):
            ws["A2"].fill = PatternFill(start_color=config["desc_bg_color"], end_color=config["desc_bg_color"], fill_type="solid")
        ws["A2"].alignment = Alignment(horizontal="left", vertical="center")
        ws["A2"].border = Border(bottom=Side(style="double", color=config["desc_font_color"]))
        ws.row_dimensions[2].height = 20

    # --- Header row only (cheap) ---
    header_font = Font(name=fn, bold=True, color=config["header_font_color"])
    header_fill = PatternFill(start_color=config["header_bg"], end_color=config["header_bg"], fill_type="solid")
    side = Side(style="thin", color=config["table_border_color"])
    border = Border(left=side, right=side, top=side, bottom=side)
    for cell in ws[start]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    # --- Number format on float columns (per cell; openpyxl has no column-level
    #     number format that reaches data cells). This is the slow part for big
    #     appended sheets -- give large sheets their own file_name (xlsxwriter
    #     path) or set apply_formatting = FALSE for them. ---
    float_cols = [i for i, c in enumerate(df.columns, 1) if pd.api.types.is_float_dtype(df[c])]
    if float_cols:
        fmt = config["float_number_format"]
        max_row = start + len(df)
        for row in ws.iter_rows(min_row=start + 1, max_row=max_row):
            for col_idx in float_cols:
                row[col_idx - 1].number_format = fmt

    # --- Column widths (vectorised) ---
    for col_idx, (width, _kind) in enumerate(_column_plan(df, config), 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    ws.sheet_view.showGridLines = config["show_gridlines"]
    ws.freeze_panes = f"A{start + 1}"
