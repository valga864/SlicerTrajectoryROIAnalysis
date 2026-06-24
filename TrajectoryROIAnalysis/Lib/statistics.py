# Lib/statistics.py

"""Statistical helpers for ROI intensity measurements."""

import math

import numpy as np


def safe_divide(value, reference):
    """Return value divided by reference, or NaN if invalid."""
    try:
        value = float(value)
        reference = float(reference)

    except Exception:
        return float("nan")

    if not math.isfinite(value):
        return float("nan")

    if not math.isfinite(reference) or abs(reference) < 1e-12:
        return float("nan")

    return value / reference


def compute_statistics(values):
    """Return descriptive statistics for finite voxel intensity values.

    Variance and standard deviation use the population definition
    with ddof=0, because the ROI contains the full voxel set being measured.
    """
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]

    if values.size == 0:
        return {
            "mean": float("nan"),
            "median": float("nan"),
            "q1": float("nan"),
            "q3": float("nan"),
            "iqr": float("nan"),
            "var": float("nan"),
            "sd": float("nan"),
            "count": 0,
        }

    q1 = float(np.percentile(values, 25))
    q3 = float(np.percentile(values, 75))

    return {
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "q1": q1,
        "q3": q3,
        "iqr": q3 - q1,
        "var": float(np.var(values, ddof=0)),
        "sd": float(np.std(values, ddof=0)),
        "count": int(values.size),
    }


def extract_voxel_values(volumeNode, indices):
    """Return voxel values from a Slicer volume at indices ordered as (k, j, i)."""
    import slicer

    volume_array = slicer.util.arrayFromVolume(volumeNode)

    if indices is None or len(indices) == 0:
        return np.array([], dtype=float)

    indices = np.asarray(indices, dtype=int)

    k = indices[:, 0]
    j = indices[:, 1]
    i = indices[:, 2]

    return volume_array[k, j, i].astype(float)


def compute_roi_statistics(volumeNode, indices):
    """Return intensity statistics for one volume inside one ROI."""
    values = extract_voxel_values(volumeNode, indices)
    return compute_statistics(values)


def write_statistics_to_row(row, prefix, stats, norm_ref_mean=None):
    """Write ROI statistics into a CSV row using a consistent column prefix."""
    row[f"{prefix}Mean"] = stats["mean"]
    row[f"{prefix}Median"] = stats["median"]
    row[f"{prefix}Q1"] = stats["q1"]
    row[f"{prefix}Q3"] = stats["q3"]
    row[f"{prefix}IQR"] = stats["iqr"]
    row[f"{prefix}Var"] = stats["var"]
    row[f"{prefix}SD"] = stats["sd"]
    row[f"{prefix}Count"] = stats["count"]

    if norm_ref_mean is not None:
        row[f"{prefix}Mean_NormBySelectedSegmentMean"] = safe_divide(
            stats["mean"],
            norm_ref_mean,
        )