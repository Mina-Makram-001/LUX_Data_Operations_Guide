"""Single-pass multi-sheet Excel reporting engine (xlsxwriter).

Builds a complete workbook -- Audit Trail + TOC/Home + N data sheets -- in ONE
``pd.ExcelWriter`` pass. Nothing is ever re-opened or appended, so the workbook
is serialised to disk exactly once at the end of the ``with`` block. This is the
deliberate replacement for the old openpyxl ``mode="a"`` pattern that reloaded
the whole file on every sheet.

Design rules honoured here:
  * NO KNIME imports -- pure pandas / xlsxwriter, locally unit-testable.
  * Styling is applied per COLUMN via ``set_column`` (one call per column),
    never per cell.
  * Reconciliation flagging uses ``conditional_format`` across whole column
    ranges in one call per range -- no row loops.
  * All worksheets are created inside a single ``with pd.ExcelWriter(...)``.

Public API
----------
Pure assembly helpers (pandas only, easy to test):
    parse_bool, resolve_sheet_style, clean_date_columns, handle_empty_dataset,
    build_audit_rows, build_toc_rows, build_ordered_sheets
The writer:
    build_report_workbook
"""

import datetime

import pandas as pd
from xlsxwriter.utility import xl_col_to_name


# --------------------------------------------------------------------------- #
# Defaults / shared chrome for the TOC + Audit sheets
# --------------------------------------------------------------------------- #
AUDIT_SHEET_NAME = "Audit Trail"
TOC_SHEET_NAME = "TOC"
BACK_TO_HOME_TEXT = "Return to Home"
MISSING_SHEET_FLAG = "Sheet Not Generated"

DEFAULT_CHECK_PAIRS = [
    ("GROSS_PAID_DIFF", "GROSS_PAID_PCT"),
    ("GROSS_OS_DIFF", "GROSS_OS_PCT"),
    ("RI_PAID_DIFF", "RI_PAID_PCT"),
    ("RI_OS_DIFF", "RI_OS_PCT"),
]

# Colours (hex, no '#') for the navigation chrome -- mirror the original design.
TOC_STYLE = {
    "link_color": "0563C1",
    "missing_color": "7F7F7F",
    "back_font_color": "FFFFFF",
    "back_fill": "34495E",
    "header_font_color": "FFFFFF",
    "header_fill": "2C3E50",
    "audit_key_color": "2C3E50",
    "row_border_color": "E0E0E0",
    "missing_status_color": "FF0000",
    "audit_tab_color": "808080",
    "toc_tab_color": "000000",
    "font_name": "Calibri",
}


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def parse_bool(value, default=True):
    """Interpret a config value as bool. Missing/blank/unknown -> default."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and pd.isna(value):
        return default
    if isinstance(value, int):
        return value != 0
    text = str(value).strip().lower()
    if text == "":
        return default
    if text in ("true", "t", "yes", "y", "1", "on"):
        return True
    if text in ("false", "f", "no", "n", "0", "off"):
        return False
    return default


def _hex(value, default):
    """Normalise an Excel-sourced colour to a 6-char hex string (no '#').

    Excel reads all-digit hex codes (``000000``, ``595959``) as integers, and
    ``000000`` becomes a falsy ``0``. This restores them to padded strings.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    if isinstance(value, (int,)) and not isinstance(value, bool):
        return str(int(value)).zfill(6)
    s = str(value).strip().replace("#", "")
    if s == "":
        return default
    return s.zfill(6) if s.isdigit() else s


def _text(value, default=""):
    """Return a clean string, treating NaN/None/blank as missing."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return default
    s = str(value).strip()
    return s if s != "" else default


def resolve_sheet_style(config):
    """Fill defaults / coerce types on a raw per-sheet config dict.

    Raw config is the ``Setting`` -> ``Value`` mapping for one ``SheetNum`` from
    ``Output_Sheets_Config``. Returns a new dict; never mutates the input.
    """
    cfg = dict(config)
    cfg["table_start_row"] = int(cfg.get("table_start_row", 5))
    cfg["show_gridlines"] = parse_bool(cfg.get("show_gridlines"), default=False)
    cfg["font_name"] = _text(cfg.get("font_name"), "Calibri")

    cfg["header_bg"] = _hex(cfg.get("header_bg"), "1F4E78")
    cfg["header_font_color"] = _hex(cfg.get("header_font_color"), "FFFFFF")
    cfg["title_font_color"] = _hex(cfg.get("title_font_color"), "000000")
    cfg["desc_font_color"] = _hex(cfg.get("desc_font_color"), "595959")
    cfg["table_border_color"] = _hex(cfg.get("table_border_color"), "000000")

    # Optional backgrounds: keep only if actually present (else no fill).
    for key in ("title_bg_color", "desc_bg_color"):
        if _text(cfg.get(key)) == "":
            cfg.pop(key, None)
        else:
            cfg[key] = _hex(cfg.get(key), "FFFFFF")

    cfg["float_number_format"] = _text(cfg.get("float_number_format"), "#,##0")
    cfg["date_number_format"] = _text(cfg.get("date_number_format"), "yyyy-mm-dd")
    cfg["pct_number_format"] = _text(cfg.get("pct_number_format"), "0.0%")
    cfg["title_text"] = _text(cfg.get("title_text"), "Report")
    cfg["desc_text"] = _text(cfg.get("desc_text"), "")  # "" -> skipped downstream
    return cfg


def handle_empty_dataset(df):
    """Return a 1-row placeholder frame when the input has no rows."""
    if df.empty:
        out = df.copy()
        if len(out.columns) == 0:
            return pd.DataFrame({"Info": ["No data available."]})
        out.loc[0] = ["No data available."] + [None] * (len(out.columns) - 1)
        return out
    return df


def clean_date_columns(df):
    """Convert timestamp-like columns to plain dates (on a copy)."""
    out = df.copy()
    for col in out.columns:
        try:
            idx = out[col].first_valid_index()
            if idx is not None:
                first = out[col].loc[idx]
                if isinstance(first, (pd.Timestamp, datetime.datetime)) or (
                    isinstance(first, str) and "00:00:00" in first
                ):
                    out[col] = pd.to_datetime(out[col]).dt.date
        except Exception:
            pass
    return out


def build_audit_rows(meta):
    """Build the ordered (key, value) Audit Trail rows from a plain dict.

    ``meta`` holds already-resolved values (strings/numbers) pulled from flow
    variables by the glue. Section headers are emitted as ``(label, "")``.
    """
    g = lambda k, d="N/A": meta.get(k, d)
    try:
        tol_pct = float(g("tolerance_pct", 0.005)) * 100
    except (TypeError, ValueError):
        tol_pct = g("tolerance_pct")
    try:
        tol_abs = f"{float(g('tolerance_abs', 1000)):,.2f}"
    except (TypeError, ValueError):
        tol_abs = g("tolerance_abs")
    return [
        ("Execution Metadata", ""),
        ("Run ID", g("run_id")),
        ("Run Timestamp", g("run_timestamp")),
        ("Time End", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("User", g("operator")),
        ("Machine", g("machine")),
        ("Business Context", ""),
        ("Company", g("company")),
        ("Valuation Date", g("valuation_date")),
        ("Reporting Year/Quarter", f"{g('reporting_year', '')}-Q{g('reporting_quarter', '')}"),
        ("Data Scope & Source", ""),
        ("Data Type", g("data_type")),
        ("Data Scope", g("data_scope")),
        ("Data Name", g("database_filename")),
        ("Files Loaded", g("ingest_files_read", "1")),
        ("Files Failed", g("ingest_files_failed", "0")),
        ("Ingest Row Count", g("ingest_row_count")),
        ("Validation Parameters", ""),
        ("Reconciliation Based On", g("recon_date_variable")),
        ("Tolerance %", f"{tol_pct}%" if not isinstance(tol_pct, str) else tol_pct),
        ("Tolerance Abs", tol_abs),
        ("Workflow Timestamps", ""),
        ("Claims Part 1 Start", g("p1s")),
        ("Claims Part 1 End", g("p1e")),
        ("Claims Part 2 Start", g("p2s")),
        ("Claims Part 2 End", g("p2e"))
    ]


def build_toc_rows(details_df, existing_ids):
    """Build TOC row dicts from the ``Output_Sheets_Details`` frame.

    ``existing_ids`` is the set of Sheet IDs that actually have data (a parquet
    file was present). Sheets not in that set are rendered as "not generated".
    """
    rows = []
    d = details_df.sort_values(by="Order")
    for _, r in d.iterrows():
        sid = str(r["Sheet ID"]).strip()
        rows.append({
            "sheet_id": sid,
            "tab_name": str(r["Sheet Name"]).strip(),
            "sheet_title": str(r["Sheet Title"]).strip(),
            "category": str(r["Category"]).strip(),
            "action": str(r["Action"]).strip(),
            "fade_color": str(r["Fade Color"]).replace("#", "").strip() if pd.notna(r["Fade Color"]) else "FFFFFF",
            "exists": sid in existing_ids,
        })
    return rows


def build_ordered_sheets(details_df, raw_configs, frames):
    """Build the ordered list of data-sheet specs (only those with frames).

    Parameters
    ----------
    details_df : DataFrame
        ``Output_Sheets_Details`` (Sheet ID, Sheet Name, Color, Order, ...).
    raw_configs : dict[str, dict]
        Sheet ID -> raw ``Output_Sheets_Config`` ``Setting:Value`` mapping.
    frames : dict[str, DataFrame]
        Sheet ID -> DataFrame (already read from parquet).

    Returns
    -------
    list[dict]
        One spec per sheet, in ``Order``, with keys ``tab_name``, ``df``,
        ``config`` (raw), ``tab_color``.
    """
    specs = []
    d = details_df.sort_values(by="Order")
    for _, r in d.iterrows():
        sid = str(r["Sheet ID"]).strip()
        if sid not in frames:
            continue
        specs.append({
            "tab_name": str(r["Sheet Name"]).strip(),
            "df": frames[sid],
            "config": raw_configs.get(sid, {}),
            "tab_color": str(r["Color"]).replace("#", "").strip() if pd.notna(r["Color"]) else None,
        })
    return specs


# --------------------------------------------------------------------------- #
# Column metadata
# --------------------------------------------------------------------------- #
def _is_date_column(series):
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    idx = series.first_valid_index()
    return idx is not None and isinstance(series.loc[idx], datetime.date)


def _column_plan(df, pct_cols):
    """Return list of (width, kind) per column. kind in float/date/pct/other."""
    plan = []
    for name in df.columns:
        s = df[name]
        width = len(str(name)) * 1.3
        if name in pct_cols:
            kind = "pct"
        elif pd.api.types.is_float_dtype(s):
            kind = "float"
        elif _is_date_column(s):
            kind = "date"
        else:
            kind = "other"

        sample = s.head(1000).dropna()
        if not sample.empty:
            if kind in ("float", "pct"):
                lens = sample.astype("int64", errors="ignore").astype(str).str.len()
                lens = lens + (lens // 3) + 4
                width = max(width, int(lens.max()))
            elif kind == "date":
                width = max(width, 10)
            else:
                width = max(width, int(sample.astype(str).str.len().max()))
        plan.append((width + 4, kind))
    return plan


# --------------------------------------------------------------------------- #
# Sheet writers
# --------------------------------------------------------------------------- #
def _add_audit_sheet(wb, audit_rows, style):
    ws = wb.add_worksheet(AUDIT_SHEET_NAME)
    ws.set_tab_color("#" + style["audit_tab_color"])
    ws.hide_gridlines(2)

    fn = style["font_name"]
    header_fmt = wb.add_format({
        "font_name": fn, "bold": True, "font_color": "#" + style["header_font_color"],
        "bg_color": "#" + style["header_fill"], "valign": "vcenter",
    })
    key_fmt = wb.add_format({
        "font_name": fn, "bold": True, "font_color": "#" + style["audit_key_color"],
        "bottom": 1, "bottom_color": "#" + style["row_border_color"],
    })
    val_fmt = wb.add_format({
        "font_name": fn, "align": "left",
        "bottom": 1, "bottom_color": "#" + style["row_border_color"],
    })

    r = 1  # start on Excel row 2
    for key, value in audit_rows:
        if value == "":  # section header spanning B:C
            ws.write(r, 1, key, header_fmt)
            ws.write(r, 2, "", header_fmt)
        else:
            ws.write(r, 1, key, key_fmt)
            ws.write(r, 2, value, val_fmt)
        r += 1
    ws.set_column(1, 1, 30)
    ws.set_column(2, 2, 60)


def _add_toc_sheet(wb, toc_rows, style):
    ws = wb.add_worksheet(TOC_SHEET_NAME)
    ws.set_tab_color("#" + style["toc_tab_color"])
    ws.hide_gridlines(2)

    fn = style["font_name"]
    header_fmt = wb.add_format({
        "font_name": fn, "bold": True, "font_color": "#" + style["header_font_color"],
        "bg_color": "#" + style["header_fill"],
    })
    link_fmt = wb.add_format({
        "font_name": fn, "bold": True, "underline": 1, "font_color": "#" + style["link_color"],
        "bottom": 1, "bottom_color": "#" + style["row_border_color"],
    })
    border_fmt = wb.add_format({"font_name": fn, "bottom": 1, "bottom_color": "#" + style["row_border_color"]})
    missing_fmt = wb.add_format({
        "font_name": fn, "italic": True, "font_color": "#" + style["missing_color"],
        "bottom": 1, "bottom_color": "#" + style["row_border_color"],
    })
    missing_status_fmt = wb.add_format({
        "font_name": fn, "bold": True, "font_color": "#" + style["missing_status_color"],
        "bottom": 1, "bottom_color": "#" + style["row_border_color"],
    })

    headers = ["Sheet Name", "Sheet Title", "Category", "Action", "Status"]
    for c, h in enumerate(headers):
        ws.write(0, c, h, header_fmt)

    for i, row in enumerate(toc_rows, start=1):
        fade_fmt = wb.add_format({
            "font_name": fn, "bg_color": "#" + row["fade_color"],
            "bottom": 1, "bottom_color": "#" + style["row_border_color"],
        })
        if row["exists"]:
            ws.write_url(i, 0, f"internal:'{row['tab_name']}'!A1", link_fmt, row["tab_name"])
            ws.write(i, 1, row["sheet_title"], border_fmt)
            ws.write(i, 2, row["category"], border_fmt)
            ws.write(i, 3, row["action"], fade_fmt)
            ws.write(i, 4, "Available", border_fmt)
        else:
            ws.write(i, 0, row["tab_name"], missing_fmt)
            ws.write(i, 1, row["sheet_title"], missing_fmt)
            ws.write(i, 2, row["category"], border_fmt)
            ws.write(i, 3, row["action"], fade_fmt)
            ws.write(i, 4, MISSING_SHEET_FLAG, missing_status_fmt)

    for c, w in enumerate([30, 50, 20, 15, 25]):
        ws.set_column(c, c, w)


def _add_data_sheet(writer, wb, spec, recon_config, style):
    cfg = resolve_sheet_style(spec["config"])
    tab = spec["tab_name"]
    start = cfg["table_start_row"]            # 1-based header row
    df = handle_empty_dataset(clean_date_columns(spec["df"]))
    fn = cfg["font_name"]

    # which columns are reconciliation % columns present on THIS sheet
    pairs = [(d, p) for d, p in recon_config["check_pairs"] if d in df.columns and p in df.columns]
    pct_cols = {p for _, p in pairs}

    # --- data only; header written manually directly above first data row ---
    df.to_excel(writer, sheet_name=tab, index=False, header=False, startrow=start)
    ws = writer.sheets[tab]
    if spec.get("tab_color"):
        ws.set_tab_color("#" + spec["tab_color"])

    # --- title (A1) ---
    title_fmt = wb.add_format({
        "font_name": fn, "bold": True, "font_size": 18,
        "font_color": "#" + cfg["title_font_color"], "align": "left",
        "valign": "vcenter", "bottom": 5, "bottom_color": "#" + cfg["title_font_color"],
    })
    if cfg.get("title_bg_color"):
        title_fmt.set_bg_color("#" + cfg["title_bg_color"])
    ws.set_row(0, 30)
    ws.write(0, 0, cfg.get("title_text", "Report"), title_fmt)

    # --- description (A2) ---
    if cfg.get("desc_text"):
        desc_fmt = wb.add_format({
            "font_name": fn, "italic": True, "font_size": 11,
            "font_color": "#" + cfg["desc_font_color"], "align": "left",
            "valign": "vcenter", "bottom": 6, "bottom_color": "#" + cfg["desc_font_color"],
        })
        if cfg.get("desc_bg_color"):
            desc_fmt.set_bg_color("#" + cfg["desc_bg_color"])
        ws.set_row(1, 20)
        ws.write(1, 0, cfg["desc_text"], desc_fmt)

    # --- "Return to Home" button (A3) ---
    back_fmt = wb.add_format({
        "font_name": fn, "bold": True, "font_size": 11,
        "font_color": "#" + style["back_font_color"], "bg_color": "#" + style["back_fill"],
        "align": "center", "valign": "vcenter",
    })
    ws.write_url(2, 0, f"internal:'{TOC_SHEET_NAME}'!A1", back_fmt, BACK_TO_HOME_TEXT)

    # --- header row (one cell per column) ---
    header_fmt = wb.add_format({
        "font_name": fn, "bold": True, "font_color": "#" + cfg["header_font_color"],
        "bg_color": "#" + cfg["header_bg"], "align": "center", "valign": "vcenter",
        "border": 1, "border_color": "#" + cfg["table_border_color"],
    })
    for c, name in enumerate(df.columns):
        ws.write(start - 1, c, str(name), header_fmt)

    # --- column formats + widths (one set_column per column) ---
    float_fmt = wb.add_format({"font_name": fn, "num_format": cfg["float_number_format"]})
    date_fmt = wb.add_format({"font_name": fn, "num_format": cfg["date_number_format"]})
    pct_fmt = wb.add_format({"font_name": fn, "num_format": cfg["pct_number_format"]})
    plain_fmt = wb.add_format({"font_name": fn})
    fmt_by_kind = {"float": float_fmt, "date": date_fmt, "pct": pct_fmt, "other": plain_fmt}
    for c, (width, kind) in enumerate(_column_plan(df, pct_cols)):
        ws.set_column(c, c, width, fmt_by_kind[kind])

    ws.hide_gridlines(0 if cfg["show_gridlines"] else 2)
    ws.freeze_panes(start, 0)

    # --- reconciliation conditional formatting (whole-column ranges) ---
    if pairs and len(df) > 0:
        _apply_recon_formats(wb, ws, df, pairs, start, recon_config, fn)


def _apply_recon_formats(wb, ws, df, pairs, start, rc, fn):
    red_fmt = wb.add_format({
        "bg_color": "#" + rc["error_bg_color"], "font_color": "#" + rc["error_font_color"], "bold": True,
    })
    gray_fmt = wb.add_format({"bg_color": "#" + rc["null_bg_color"]})

    first_row0 = start                       # 0-based first data row
    last_row0 = start + len(df) - 1
    first_row1 = start + 1                    # 1-based first data row (for formulas)
    tol_abs = rc["tolerance_abs"]
    tol_pct = rc["tolerance_pct"]

    for diff_col, pct_col in pairs:
        di = df.columns.get_loc(diff_col)
        pi = df.columns.get_loc(pct_col)
        d_letter = xl_col_to_name(di)
        p_letter = xl_col_to_name(pi)
        # Coupling: highlight BOTH cells if EITHER breaches its tolerance.
        formula = (f"=OR(ABS(${d_letter}{first_row1})>{tol_abs},"
                   f"ABS(${p_letter}{first_row1})>{tol_pct})")

        for col0 in (di, pi):
            # red first (higher priority), then gray for blanks
            ws.conditional_format(first_row0, col0, last_row0, col0,
                                  {"type": "formula", "criteria": formula, "format": red_fmt})
            ws.conditional_format(first_row0, col0, last_row0, col0,
                                  {"type": "blanks", "format": gray_fmt})


# --------------------------------------------------------------------------- #
# Orchestrator -- the single pass
# --------------------------------------------------------------------------- #
def build_report_workbook(file_path, ordered_sheets, toc_rows, audit_rows,
                          recon_config=None, toc_style=None, date_number_format="yyyy-mm-dd"):
    """Write the entire workbook in one xlsxwriter pass and return the path.

    Order of tabs: Audit Trail, TOC, then each data sheet in ``ordered_sheets``.
    The file is created and serialised exactly once (on ``with`` exit).
    """
    style = dict(TOC_STYLE)
    if toc_style:
        style.update(toc_style)

    rc = {
        "check_pairs": DEFAULT_CHECK_PAIRS,
        "tolerance_abs": 1000.0,
        "tolerance_pct": 0.005,
        "error_bg_color": "FFC7CE",
        "error_font_color": "9C0006",
        "null_bg_color": "D9D9D9",
    }
    if recon_config:
        rc.update(recon_config)

    with pd.ExcelWriter(
        file_path,
        engine="xlsxwriter",
        datetime_format=date_number_format,
        date_format=date_number_format,
    ) as writer:
        wb = writer.book
        _add_audit_sheet(wb, audit_rows, style)
        _add_toc_sheet(wb, toc_rows, style)
        for spec in ordered_sheets:
            _add_data_sheet(writer, wb, spec, rc, style)

    return file_path
