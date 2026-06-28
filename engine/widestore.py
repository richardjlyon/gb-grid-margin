"""Generic append-only, idempotent wide CSV store.

Shared by the half-hourly history pipelines (settled FUELHH and embedded). One row per
(settlement_date, settlement_period); a blank cell is None (series absent that period),
kept distinct from a genuine 0. Re-appending an identical row is a no-op; a *different*
value for an existing key is a settlement revision, handled per the `on_revision` policy
of `append_rows` ("raise" by default for backfills; the daily append uses "update" to
absorb NESO/Elexon revisions, with git as the audit trail).
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path


def key(row: dict) -> tuple[str, int]:
    return (row["settlement_date"], int(row["settlement_period"]))


def to_csv(row: dict, columns: list[str]) -> dict:
    return {c: ("" if row.get(c) is None else row[c]) for c in columns}


def from_csv(raw: dict, columns: list[str], text_columns: set[str]) -> dict:
    out: dict = {}
    for c in columns:
        v = raw.get(c, "")
        out[c] = v if c in text_columns else (None if v == "" else int(v))
    return out


def read_file(path: Path, columns: list[str], text_columns: set[str]) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return [from_csv(r, columns, text_columns) for r in csv.DictReader(f)]


def append_rows(rows: list[dict], columns: list[str], text_columns: set[str],
                path_for: Callable[[str], Path], on_revision: str = "raise") -> int:
    """Append wide rows to their per-file buckets, append-only and idempotent.

    A key already present with a *different* value is a settlement revision (NESO/Elexon
    correct settled values retrospectively). ``on_revision`` decides what happens:
      - ``"raise"`` (default): refuse — append-only history is never silently overwritten.
        Right for backfills, where a revision means a real conflict to surface.
      - ``"update"``: rewrite the cell to the incoming value (the source's latest) and
        count it. The file is rewritten in place; git records the change. Right for the
        automated daily append, which re-fetches an overlap window of still-settling days.
      - ``"skip"``: keep the stored value, ignore the revision, don't count it.

    Returns the number of rows newly written or updated.
    """
    if on_revision not in ("raise", "update", "skip"):
        raise ValueError(f"unknown on_revision policy {on_revision!r}")
    written = 0
    by_file: dict[Path, list[dict]] = {}
    for row in rows:
        by_file.setdefault(path_for(row["settlement_date"]), []).append(row)
    for path, file_rows in by_file.items():
        existing = {key(r): r for r in read_file(path, columns, text_columns)}
        new_rows = []
        revised = 0
        for row in file_rows:
            k = key(row)
            if k in existing:
                if from_csv(to_csv(row, columns), columns, text_columns) == existing[k]:
                    continue  # identical re-append — idempotent no-op
                if on_revision == "raise":
                    raise ValueError(
                        f"settlement revision at {k}: stored {existing[k]} != incoming "
                        f"— refusing to overwrite append-only history")
                if on_revision == "skip":
                    continue
                existing[k] = from_csv(to_csv(row, columns), columns, text_columns)
                revised += 1
                continue
            new_rows.append(row)
        if not new_rows and not revised:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if revised:
            # A revision means the file must be rewritten, not appended to: merge the
            # updated existing rows with the new ones and re-emit, sorted by key.
            merged = sorted(list(existing.values()) + new_rows, key=key)
            with path.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=columns)
                w.writeheader()
                for row in merged:
                    w.writerow(to_csv(row, columns))
        else:
            is_new = not path.exists()
            with path.open("a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=columns)
                if is_new:
                    w.writeheader()
                for row in new_rows:
                    w.writerow(to_csv(row, columns))
        written += len(new_rows) + revised
    return written


def read_store(base_dir: Path, pattern: str, columns: list[str],
               text_columns: set[str]) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(Path(base_dir).glob(pattern)):
        rows.extend(read_file(path, columns, text_columns))
    return sorted(rows, key=key)
