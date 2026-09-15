"""Folder-level Excel ingestion for the claims reserving pipeline.

This module is the *pure core* behind the KNIME "Ingest" node. It contains no
KNIME imports, so it can be imported, run, and unit-tested on any machine with
pandas installed. The KNIME Python Script node is a thin glue layer that reads
flow variables, imports th  is module, and calls :func:`ingest_folder`.

Read strategy (business rule)
-----------------------------
Every cell is read as text (``dtype=str``) and the consolidated frame is cast to
the pandas nullable ``string`` dtype. Claims workbooks coming from different
companies are inconsistent: the same column can be numeric in one file and text
in another. Reading as string defers all type decisions to the downstream
Standardize / Mapping nodes and prevents schema-merge crashes during concat.

Audit trail (business rule)
---------------------------
Each row is stamped with its source file name and 1-based position inside that
file, so a bad value found downstream can be traced back to an exact file/row.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import pandas as pd

# --- Defaults (override via the node's flow variables, not by editing here) ---
DEFAULT_SHEET_NAME: str = "DATA"
DEFAULT_GLOB_PATTERN: str = "*.xlsx"
DEFAULT_ENGINE: str = "calamine"
FALLBACK_ENGINE: str = "openpyxl"

# Audit column names (kept stable; downstream nodes depend on them).
AUDIT_FILE_COL: str = "R_FILE_NAME"
AUDIT_ROW_COL: str = "Source_Row_ID"


class IngestResult(NamedTuple):
    """Outcome of an ingest run.

    Attributes:
        data: Consolidated all-string DataFrame (empty if no rows were read).
        files_read: Names of files read successfully, in read order.
        files_failed: ``(file_name, error_message)`` for each file that raised.
    """

    data: pd.DataFrame
    files_read: list[str]
    files_failed: list[tuple[str, str]]


def _engine_is_available(engine: str) -> bool:
    """Return True if the named pandas Excel engine can be imported.

    Args:
        engine: pandas engine name, e.g. ``"calamine"`` or ``"openpyxl"``.

    Returns:
        True if the backing package is importable, else False. Unknown engine
        names return True so pandas can raise its own descriptive error later.
    """
    backing = {"calamine": "python_calamine", "openpyxl": "openpyxl"}.get(engine)
    if backing is None:
        return True
    try:
        __import__(backing)
        return True
    except ImportError:
        return False


def resolve_engine(preferred: str = DEFAULT_ENGINE,
                   fallback: str = FALLBACK_ENGINE) -> str:
    """Pick an installed Excel engine, falling back if the preferred is missing.

    Args:
        preferred: Engine to use when available (default ``"calamine"``, a fast
            Rust-based reader).
        fallback: Engine to use if ``preferred`` is not installed.

    Returns:
        The name of an available engine.

    Raises:
        ImportError: If neither the preferred nor the fallback engine is
            installed in the active Python environment.
    """
    if _engine_is_available(preferred):
        return preferred
    if _engine_is_available(fallback):
        return fallback
    raise ImportError(
        f"Neither Excel engine '{preferred}' nor fallback '{fallback}' is "
        f"installed in this Python environment."
    )


def add_audit_columns(df: pd.DataFrame, file_name: str) -> pd.DataFrame:
    """Stamp a frame with source-file and source-row audit columns.

    Args:
        df: Rows read from a single workbook (any index).
        file_name: Physical file name to record in :data:`AUDIT_FILE_COL`.

    Returns:
        A copy of ``df`` with two added columns: the source file name and a
        1-based ``row_<n>`` identifier reflecting the row's position in the
        sheet (header excluded). The counter is positional and does not depend
        on the incoming index.
    """
    stamped = df.copy()
    stamped[AUDIT_FILE_COL] = file_name
    stamped[AUDIT_ROW_COL] = [f"row_{i}" for i in range(2, len(stamped) + 2)]
    return stamped


def read_excel_file(file_path, sheet_name: str = DEFAULT_SHEET_NAME,
                     engine: str = DEFAULT_ENGINE) -> pd.DataFrame:
    """Read one Excel workbook's data sheet as all-string, with audit columns.

    Args:
        file_path: Path to a single ``.xlsx`` workbook.
        sheet_name: Worksheet to read (default ``"DATA"``).
        engine: pandas Excel engine to use.

    Returns:
        A DataFrame with every value as text plus the two audit columns.

    Raises:
        FileNotFoundError: If ``file_path`` does not exist.
        ValueError: If the requested sheet is missing (raised by pandas).
    """
    file_path = Path(file_path)
    df = pd.read_excel(file_path, sheet_name=sheet_name, dtype=str, engine=engine)
    return add_audit_columns(df, file_path.name)


def ingest_folder(folder_path, sheet_name: str = DEFAULT_SHEET_NAME,
                  engine: str = DEFAULT_ENGINE,
                  pattern: str = DEFAULT_GLOB_PATTERN) -> IngestResult:
    """Read and consolidate every matching workbook in a folder.

    Files are processed in sorted (deterministic) name order. A file that fails
    to read is recorded and skipped, so one bad workbook never aborts the run.

    Args:
        folder_path: Directory containing the source workbooks.
        sheet_name: Worksheet to read from each file (default ``"DATA"``).
        engine: Preferred Excel engine; an installed fallback is used if needed.
        pattern: Glob pattern selecting input files (default ``"*.xlsx"``).

    Returns:
        An :class:`IngestResult`. ``data`` is the concatenated all-string frame
        (empty DataFrame if nothing was read); ``files_read`` and
        ``files_failed`` describe what happened.

    Raises:
        NotADirectoryError: If ``folder_path`` is not an existing directory.
            This deliberately fails loud, because a mistyped UNC path in
            Control_Settings.xlsx would otherwise silently yield zero rows.
        ImportError: If no usable Excel engine is installed.
    """
    folder = Path(folder_path)
    if not folder.is_dir():
        raise NotADirectoryError(
            f"Ingest input folder does not exist or is not a directory: {folder!s}"
        )

    engine = resolve_engine(engine)

    frames: list[pd.DataFrame] = []
    files_read: list[str] = []
    files_failed: list[tuple[str, str]] = []

    for file in sorted(folder.glob(pattern)):
        try:
            frames.append(
                read_excel_file(file, sheet_name=sheet_name, engine=engine)
            )
            files_read.append(file.name)
        except Exception as exc:  # noqa: BLE001 - log & continue, never abort
            files_failed.append((file.name, str(exc)))

    if frames:
        data = pd.concat(frames, ignore_index=True).astype("string")
    else:
        data = pd.DataFrame()

    return IngestResult(data=data, files_read=files_read, files_failed=files_failed)
