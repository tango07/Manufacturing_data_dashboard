"""Ingest source files into raw tables.

Two input shapes are supported:
  1. A folder of flat exports, one table per file (the full dataset: 01_Production_Runs.xlsx and so on).
     The table is identified from its header row, by the key column it contains.
  2. A single stacked workbook with several tables on one sheet (the earlier sample).

Every raw row keeps source_file and source_row (the Excel row number), so any exception can be traced
back to the exact line of the source file.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from pipeline.config import TABLE_SPECS, TableSpec
from pipeline.load import _is_blank, _norm, extract_tables, read_grid

SUPPORTED_SUFFIXES = (".xlsx", ".xlsm")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_flat_file(path: Path) -> tuple[TableSpec | None, pd.DataFrame]:
    """Read one single-table workbook. Returns (spec, frame); spec is None if no known key column is found."""
    sheets = read_grid(str(path))
    _, rows = sheets[0]
    # Score every table by how many of its expected columns the header contains. A downtime file also
    # carries Run_ID, so matching on a single shared column would pick the wrong table.
    best = (0, None, None)  # (score, header index, spec)
    for i in range(min(10, len(rows))):
        labels = {_norm(v) for v in rows[i]}
        for spec in TABLE_SPECS:
            score = sum(_norm(c) in labels for c in spec.columns)
            if _norm(spec.key_column) in labels and score > best[0]:
                best = (score, i, spec)
    _, header_idx, spec_found = best
    if spec_found is None or best[0] < max(3, len(spec_found.columns) // 2):
        return None, pd.DataFrame()

    header_row = rows[header_idx]
    positions = [(k, str(v).strip()) for k, v in enumerate(header_row) if v is not None and str(v).strip()]
    headers = [name for _, name in positions]
    body, source_rows = [], []
    for i in range(header_idx + 1, len(rows)):
        row = rows[i]
        if _is_blank(row):
            continue
        body.append([row[p] if p < len(row) else None for p, _ in positions])
        source_rows.append(i + 1)  # Excel rows are 1-based
    df = pd.DataFrame(body, columns=headers)
    df["source_row"] = source_rows
    df["source_file"] = path.name
    return spec_found, df


def ingest_folder(folder: Path) -> tuple[dict[str, pd.DataFrame], list[dict], list[dict]]:
    """Read every workbook in a folder. Returns (raw tables, ingest log rows, issues)."""
    raw: dict[str, pd.DataFrame] = {}
    sources: list[dict] = []
    issues: list[dict] = []
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES and not p.name.startswith("~"))
    for path in files:
        spec, df = read_flat_file(path)
        if spec is None:
            issues.append({"file": path.name, "reason": "no known key column in the first 10 rows; file skipped"})
            continue
        if spec.name in raw:
            issues.append({"file": path.name, "reason": f"second file for {spec.name}; first file kept"})
            continue
        raw[spec.name] = df
        sources.append({"table_name": spec.name, "source_file": path.name,
                        "source_sha256": file_sha256(path), "row_count": int(len(df)), "mode": "flat_file"})
    missing = [s.name for s in TABLE_SPECS if s.name not in raw]
    for name in missing:
        issues.append({"table": name, "reason": "no source file found in folder"})
        raw[name] = pd.DataFrame()
    return raw, sources, issues


def ingest_stacked(path: Path) -> tuple[dict[str, pd.DataFrame], list[dict], list[dict]]:
    sheets = read_grid(str(path))
    tables, issues = extract_tables(sheets)
    sha = file_sha256(path)
    sources = [{"table_name": name, "source_file": path.name, "source_sha256": sha,
                "row_count": int(len(df)), "mode": "stacked_workbook"} for name, df in tables.items()]
    return tables, sources, issues


def ingest(input_path: Path) -> tuple[dict[str, pd.DataFrame], list[dict], list[dict], str]:
    """Dispatch on input shape. Returns (raw, sources, issues, input_fingerprint)."""
    if input_path.is_dir():
        raw, sources, issues = ingest_folder(input_path)
        fingerprint = hashlib.sha256("".join(s["source_sha256"] for s in sources).encode()).hexdigest()
        return raw, sources, issues, fingerprint
    raw, sources, issues = ingest_stacked(input_path)
    return raw, sources, issues, file_sha256(input_path)
