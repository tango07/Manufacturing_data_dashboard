"""Workbook loader.

The source workbook stacks several tables on one or more sheets. Each table starts with a
title row (text in column A), then an optional blank row and a header row, then data rows
until a blank row or the next title. Tables are located by title keyword and by the header
row containing the table's key column. No fixed row numbers are used.
"""

from __future__ import annotations

import re

import openpyxl
import pandas as pd

from pipeline.config import TABLE_SPECS, TableSpec


def _norm(value) -> str:
    """Lower-case, trim and collapse internal whitespace for label matching."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _is_blank(row: list) -> bool:
    return all(v is None or (isinstance(v, str) and not v.strip()) for v in row)


def _matching_spec(row: list) -> TableSpec | None:
    """Return the table spec whose title keyword appears in the row's first cell, if any."""
    if not row or not isinstance(row[0], str):
        return None
    text = _norm(row[0])
    for spec in TABLE_SPECS:
        if spec.title_keyword in text:
            return spec
    return None


def _title_like(row: list) -> bool:
    """A row with text only in column A and a non-empty title-style label starts a new block.
    Used to stop a body at an unknown table title so its rows are not read as data."""
    non_empty = [v for v in row if v is not None and not (isinstance(v, str) and not v.strip())]
    return (len(non_empty) == 1 and isinstance(row[0], str) and bool(row[0].strip())
            and "excel" in _norm(row[0]))


def read_grid(path: str) -> list[tuple[str, list[list]]]:
    """Return [(sheet_name, rows)] where rows is a list of lists of cell values."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        sheets = [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
    finally:
        wb.close()
    return sheets


def extract_tables(sheets: list[tuple[str, list[list]]]) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    """Extract every known table from every sheet.

    Returns (tables, issues). tables maps table name to a raw DataFrame with values as read
    (no type coercion). issues lists any table that was missing or had no header row.
    """
    found: dict[str, list[pd.DataFrame]] = {spec.name: [] for spec in TABLE_SPECS}
    issues: list[dict] = []

    for sheet_name, rows in sheets:
        i = 0
        while i < len(rows):
            spec = _matching_spec(rows[i])
            if spec is None:
                i += 1
                continue

            # Header: the first row within 5 rows below the title whose labels include the key column.
            header_idx = None
            for j in range(i + 1, min(i + 6, len(rows))):
                labels = [_norm(v) for v in rows[j]]
                if _norm(spec.key_column) in labels:
                    header_idx = j
                    break
            if header_idx is None:
                issues.append({"table": spec.name, "sheet": sheet_name, "row": i + 1,
                               "reason": f"header row with key column {spec.key_column!r} not found"})
                i += 1
                continue

            header_row = rows[header_idx]
            positions = [(k, str(v).strip()) for k, v in enumerate(header_row)
                         if v is not None and str(v).strip()]
            headers = [name for _, name in positions]

            # The body runs until the next title row (or sheet end). Blank rows are skipped, not treated
            # as the end of the table, so a stray gap never silently truncates data.
            body = []
            k = header_idx + 1
            while k < len(rows):
                row = rows[k]
                if _matching_spec(row) is not None or _title_like(row):
                    break
                if not _is_blank(row):
                    body.append([row[p] if p < len(row) else None for p, _ in positions])
                k += 1

            found[spec.name].append(pd.DataFrame(body, columns=headers))
            i = k

    result: dict[str, pd.DataFrame] = {}
    for spec in TABLE_SPECS:
        frames = found[spec.name]
        if not frames:
            issues.append({"table": spec.name, "sheet": None, "row": None,
                           "reason": "table not found in workbook"})
            result[spec.name] = pd.DataFrame(columns=list(spec.columns))
        else:
            result[spec.name] = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    return result, issues
