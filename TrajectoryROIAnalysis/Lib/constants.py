# Lib/constants.py

"""Constants and small helper functions used throughout the extension."""

DEFAULT_ROI_RADIUS_MM: float = 2.0
DEFAULT_ROI_CENTER_OFFSET_MM: float = 0.0

ROI_RADIUS_MM: float = DEFAULT_ROI_RADIUS_MM
ROI_FOLDER_NAME: str = "Sphere ROIs"

REQUIRED_CSV_COLUMNS: list[str] = ["PointID", "DistanceToTarget_mm"]

DEFAULT_GREY_STAT: str = "Mean"
DEFAULT_PLOT_MODE: str = "Scaled (Min-Max)"

DEFAULT_ROI_CENTER_SOURCE: str = "CSV coordinates"
CSV_ROI_CENTER_COLUMNS: list[str] = ["Center_X", "Center_Y", "Center_Z"]
DEFAULT_CSV_COORDINATE_SYSTEM: str = "RAS"


def make_roi_name_from_radius(radius_mm: float) -> str:
    """Return a standardized ROI name for a spherical ROI radius.

    Examples:
        2.0  -> SphereR2
        1.5  -> SphereR1p5
        2.25 -> SphereR2p25
    """
    radius_mm = float(radius_mm)

    if abs(radius_mm - round(radius_mm)) < 1e-6:
        radius_text = str(int(round(radius_mm)))
    else:
        radius_text = f"{radius_mm:.2f}".rstrip("0").rstrip(".")
        radius_text = radius_text.replace(".", "p")

    return f"SphereR{radius_text}"


ROI_NAME: str = make_roi_name_from_radius(DEFAULT_ROI_RADIUS_MM)


PREFERRED_MODALITIES: list[str] = [
    "T1w_Gd",
    "T1w_trans",
    "T2w_Flair_trans",
    "T2w_trans",
    "postOp_trans",
]

EXCLUDED_VOLUME_NAME_PARTS: list[str] = [
    "slicerpoints",
    "insidelm",
    "labelmap",
    "mask",
    "segmentation",
    "selected_voxels",
    "voxelcubes",
    "tmp_",
]

COLOR_MAP: dict[str, tuple[float, float, float]] = {
    "Signal1": (0.0, 0.0, 0.0),
    "Signal2": (102 / 255, 51 / 255, 0 / 255),
    "T1w_Gd": (204 / 255, 121 / 255, 167 / 255),
    "T1w_trans": (0 / 255, 114 / 255, 178 / 255),
    "T2w_Flair_trans": (230 / 255, 159 / 255, 0 / 255),
    "T2w_trans": (0 / 255, 158 / 255, 115 / 255),
    "postOp_trans": (213 / 255, 94 / 255, 0 / 255),
}


def is_excluded_volume_name(name: str | None) -> bool:
    """Return True if a volume name indicates a derived or temporary node."""
    normalized_name = (name or "").lower()
    return any(part in normalized_name for part in EXCLUDED_VOLUME_NAME_PARTS)


def get_modality_key(volume_name: str | None) -> str:
    """Return the canonical modality key detected in a volume name.

    Returns an empty string if no preferred modality is recognized.
    """
    name = (volume_name or "").lower()

    if "postop" in name or "postop_trans" in name or "post_op" in name:
        return "postOp_trans"
    if "t1w_gd" in name:
        return "T1w_Gd"
    if "t1w_trans" in name:
        return "T1w_trans"
    if "t2w_flair_trans" in name:
        return "T2w_Flair_trans"
    if "t2w_trans" in name:
        return "T2w_trans"

    return ""


def is_preferred_modality(volume_name: str | None) -> bool:
    """Return True if the volume name matches one of the preferred modalities."""
    return bool(get_modality_key(volume_name))


def get_consistent_color(base_name: str | None) -> tuple[float, float, float]:
    """Return the predefined color for a modality, or gray as fallback."""
    modality_key = get_modality_key(base_name)
    return COLOR_MAP.get(modality_key, (0.5, 0.5, 0.5))