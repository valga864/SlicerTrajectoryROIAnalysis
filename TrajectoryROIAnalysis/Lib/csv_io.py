# Lib/csv_io.py

"""CSV input/output helpers for point-based measurements."""

import csv
import os

from Lib.utils import ffloat


def read_csv_rows(csv_path):
    """Read a CSV file and return its rows and column names."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file does not exist: {csv_path}")

    with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    return rows, fieldnames


def validate_required_columns(fieldnames, required_columns):
    """Raise an error if any required CSV columns are missing."""
    missing = [column for column in required_columns if column not in fieldnames]

    if missing:
        raise ValueError(
            "CSV is missing required columns: "
            + ", ".join(missing)
        )


def write_csv_rows(csv_path, rows, fieldnames):
    """Write dictionaries to a CSV file using the given column order."""
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(rows)


def ensure_columns(fieldnames, new_columns):
    """Return fieldnames with new columns appended if they are missing."""
    output_fieldnames = list(fieldnames)

    for column in new_columns:
        if column not in output_fieldnames:
            output_fieldnames.append(column)

    return output_fieldnames


def sort_rows_by_distance(rows):
    """Return rows sorted by DistanceToTarget_mm.

    Rows with missing or invalid distances are placed at the end.
    """
    return sorted(
        rows,
        key=lambda row: ffloat(
            row.get("DistanceToTarget_mm"),
            default=float("inf"),
        ),
    )


def _normalize_point_id(value):
    """Return a normalized integer-like PointID string."""
    point_id = str(value or "").strip()

    if point_id.endswith(".0"):
        point_id = point_id[:-2]

    if not point_id.isdigit():
        raise ValueError(f"Invalid PointID in CSV: {value}")

    return point_id


def match_rows_to_points_by_point_id(rows, fieldnames, point_metadata):
    """Match CSV rows to Slicer points using the PointID column.

    The CSV must contain exactly one row for every point index in
    point_metadata. Each matched row receives an internal
    _SlicerPointIndex value.
    """
    if "PointID" not in fieldnames:
        raise ValueError(
            "CSV must contain a PointID column with numeric values 0, 1, 2, ..."
        )

    row_by_point_id = {}

    for row in rows:
        point_id = _normalize_point_id(row.get("PointID"))

        if point_id in row_by_point_id:
            raise ValueError(f"CSV contains duplicate PointID: {point_id}")

        row_by_point_id[point_id] = row

    expected_ids = {str(meta["point_index"]) for meta in point_metadata}
    actual_ids = set(row_by_point_id)

    missing = sorted(expected_ids - actual_ids, key=int)
    extra = sorted(actual_ids - expected_ids, key=int)

    if missing:
        raise ValueError("CSV is missing PointID(s): " + ", ".join(missing))

    if extra:
        raise ValueError("CSV contains extra PointID(s): " + ", ".join(extra))

    matched_rows = []

    for meta in point_metadata:
        point_index = int(meta["point_index"])
        row = dict(row_by_point_id[str(point_index)])
        row["_SlicerPointIndex"] = point_index
        matched_rows.append(row)

    return matched_rows