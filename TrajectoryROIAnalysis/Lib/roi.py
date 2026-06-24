# Lib/roi.py

"""ROI helpers for spherical ROI extraction and statistics."""

import re

from Lib.constants import ROI_NAME, ROI_RADIUS_MM
from Lib.geometry import sphere_inside_indices
from Lib.statistics import compute_roi_statistics


def get_roi_prefix(volume_name, roi_name=ROI_NAME):
    """Return a consistent CSV column prefix for one volume and ROI."""
    clean_name = re.sub(r"\s+", "_", str(volume_name or "").strip())
    return f"{clean_name}_{roi_name}_"


def compute_sphere_roi_indices(reference_volume_node, center_ras, radius_mm=ROI_RADIUS_MM):
    """Return voxel indices inside a spherical ROI."""
    return sphere_inside_indices(
        reference_volume_node,
        center_ras,
        radius_mm,
    )


def compute_sphere_roi_statistics(volume_node, center_ras, radius_mm=ROI_RADIUS_MM):
    """Return voxel indices and intensity statistics for a spherical ROI."""
    indices = compute_sphere_roi_indices(
        volume_node,
        center_ras,
        radius_mm,
    )

    stats = compute_roi_statistics(
        volume_node,
        indices,
    )

    return indices, stats