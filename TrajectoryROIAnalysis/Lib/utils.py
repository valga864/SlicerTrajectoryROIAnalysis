import re
import slicer


def cleanup_string_for_csv(value):
    """Return a filesystem/CSV-safe text fragment."""
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip("_")
    return text or "NA"


def ffloat(value, default=float("nan")):
    try:
        return float(value)
    except Exception:
        return default


def get_or_create_node(class_name, node_name):
    node = slicer.util.getFirstNodeByName(node_name)

    if node is not None:
        if node.IsA(class_name):
            return node
        raise TypeError(f"Node '{node_name}' exists but is not a {class_name}.")

    return slicer.mrmlScene.AddNewNodeByClass(class_name, node_name)


def make_offset_name(offset_mm):
    """Return a filename-safe ROI offset label.

    Examples:
        0.0  -> Offset0
        0.5  -> OffsetP0p5
        -0.5 -> OffsetM0p5
        2.0  -> OffsetP2
    """
    offset_mm = float(offset_mm)

    if abs(offset_mm) < 1e-6:
        return "Offset0"

    sign = "P" if offset_mm > 0 else "M"
    value = abs(offset_mm)

    if abs(value - round(value)) < 1e-6:
        value_text = str(int(round(value)))
    else:
        value_text = f"{value:.2f}".rstrip("0").rstrip(".")
        value_text = value_text.replace(".", "p")

    return f"Offset{sign}{value_text}"