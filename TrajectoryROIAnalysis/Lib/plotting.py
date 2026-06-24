# Lib/plotting.py

"""Plotting helpers for signal and MRI ROI statistics visualization."""

import re
from io import BytesIO

import numpy as np
import qt
import slicer
import vtk

from Lib.constants import (
    COLOR_MAP,
    ROI_NAME,
    get_consistent_color,
    is_excluded_volume_name,
    is_preferred_modality,
)
from Lib.csv_io import read_csv_rows, sort_rows_by_distance
from Lib.utils import ffloat, get_or_create_node


PLOT_NODE_PREFIX = "SignalPlot_"


class ResizableImageLabel(qt.QLabel):
    """QLabel that rescales its pixmap while preserving aspect ratio."""

    def __init__(self):
        qt.QLabel.__init__(self)
        self._original_pixmap = None

        self.setAlignment(qt.Qt.AlignCenter)
        self.setMinimumSize(1, 1)
        self.setSizePolicy(
            qt.QSizePolicy.Expanding,
            qt.QSizePolicy.Expanding,
        )

    def setOriginalPixmap(self, pixmap):
        """Store the original pixmap and display a scaled version."""
        self._original_pixmap = pixmap
        self._update_scaled_pixmap()

    def resizeEvent(self, event):
        """Update the displayed pixmap after resizing."""
        qt.QLabel.resizeEvent(self, event)
        self._update_scaled_pixmap()

    def _update_scaled_pixmap(self):
        """Update the scaled pixmap shown in the label."""
        if self._original_pixmap is None:
            return

        if self.width <= 1 or self.height <= 1:
            return

        scaled = self._original_pixmap.scaled(
            self.size,
            qt.Qt.KeepAspectRatio,
            qt.Qt.SmoothTransformation,
        )

        qt.QLabel.setPixmap(self, scaled)


def cleanup_old_plot_nodes():
    """Remove plot-related MRML nodes created by this module."""
    classes_to_clean = [
        "vtkMRMLPlotChartNode",
        "vtkMRMLPlotSeriesNode",
        "vtkMRMLTableNode",
    ]

    for class_name in classes_to_clean:
        nodes = slicer.util.getNodesByClass(class_name)

        if isinstance(nodes, dict):
            nodes = list(nodes.values())

        for node in list(nodes):
            if node.GetName().startswith(PLOT_NODE_PREFIX):
                slicer.mrmlScene.RemoveNode(node)


def cleanup_label_for_plot_column(label):
    """Convert a plot label into a safe MRML table column name."""
    text = str(label or "").strip()
    text = re.sub(r"[^A-Za-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip("_")

    if not text:
        text = "Signal"

    if text[0].isdigit():
        text = "Signal_" + text

    return text


def nice_volume_name(column_name, suffix):
    """Return a readable volume name from a CSV statistic column."""
    if column_name.endswith(suffix):
        name = column_name[: -len(suffix)]
    else:
        name = column_name

    name = re.sub(
        r"^sub[-_]p\d+(?:[-_]\d+)?[_-]?",
        "",
        name,
        flags=re.IGNORECASE,
    )

    return name


def pick_grey_value_columns(fieldnames, grey_stat="Mean", roi_name=ROI_NAME):
    """Return preferred MRI grey-value columns and their shared suffix."""
    suffix = f"_{roi_name}_{grey_stat}"

    grey_columns = [
        column
        for column in fieldnames
        if column.endswith(suffix)
        and is_preferred_modality(column)
        and not is_excluded_volume_name(column)
    ]

    unique_columns = []
    seen = set()

    for column in grey_columns:
        if column not in seen:
            unique_columns.append(column)
            seen.add(column)

    return unique_columns, suffix


def _read_sorted_csv(csv_path):
    """Read CSV rows and sort them by DistanceToTarget_mm."""
    rows, fieldnames = read_csv_rows(csv_path)
    rows = sort_rows_by_distance(rows)
    return rows, fieldnames


def _missing_columns(fieldnames, required_columns):
    """Return required columns that are missing from fieldnames."""
    return [column for column in required_columns if column not in fieldnames]


def _add_float_column(table, name):
    """Add a float column to a VTK table."""
    column = vtk.vtkFloatArray()
    column.SetName(name)
    table.AddColumn(column)


def _set_table_value(table, row_index, column_index, value):
    """Set a finite float value or NaN in a VTK table."""
    table.SetValue(
        row_index,
        column_index,
        float(value) if np.isfinite(value) else float("nan"),
    )


def _add_plot_series(
    table_node,
    y_col,
    node_name,
    legend_name,
    color,
    dashed=False,
):
    """Create or update a Slicer plot series node."""
    series = get_or_create_node(
        "vtkMRMLPlotSeriesNode",
        PLOT_NODE_PREFIX + "Series_" + node_name,
    )

    series.SetName(legend_name)
    series.SetAndObserveTableNodeID(table_node.GetID())
    series.SetXColumnName("DistanceToTarget_mm")
    series.SetYColumnName(y_col)
    series.SetPlotType(series.PlotTypeScatter)
    series.SetMarkerStyle(series.MarkerStyleCircle)

    if dashed:
        series.SetLineStyle(series.LineStyleDash)
    else:
        series.SetLineStyle(series.LineStyleSolid)

    series.SetColor(*color)

    return series


def _add_signal_series_to_chart(table_node, signal_specs, chart_node, legend_suffix):
    """Add center, +SD, and -SD plot series for each signal."""
    chart_node.RemoveAllPlotSeriesNodeIDs()

    for spec in signal_specs:
        center_series = _add_plot_series(
            table_node=table_node,
            y_col=spec["center_col"],
            node_name=spec["center_col"],
            legend_name=f"{spec['label']} {legend_suffix}",
            color=spec["color"],
            dashed=False,
        )

        plus_series = _add_plot_series(
            table_node=table_node,
            y_col=spec["plus_col"],
            node_name=spec["plus_col"],
            legend_name="",
            color=spec["color"],
            dashed=True,
        )

        minus_series = _add_plot_series(
            table_node=table_node,
            y_col=spec["minus_col"],
            node_name=spec["minus_col"],
            legend_name="",
            color=spec["color"],
            dashed=True,
        )

        chart_node.AddAndObservePlotSeriesNodeID(center_series.GetID())
        chart_node.AddAndObservePlotSeriesNodeID(plus_series.GetID())
        chart_node.AddAndObservePlotSeriesNodeID(minus_series.GetID())


def lighten_color(color, amount=0.65):
    """Return a lighter RGB color by blending toward white."""
    return tuple((1.0 - amount) * float(channel) + amount for channel in color)


def zscore(values):
    """Return z-scored values and the sample standard deviation."""
    values = np.asarray(values, dtype=float)
    output = np.full(values.shape, np.nan, dtype=float)

    mask = np.isfinite(values)

    if np.count_nonzero(mask) < 2:
        return output, float("nan")

    mean = float(np.mean(values[mask]))
    sd = float(np.std(values[mask], ddof=1))

    if sd < 1e-12:
        return output, sd

    output[mask] = (values[mask] - mean) / sd

    return output, sd


def show_single_plot_minmax(
    csv_path,
    grey_stat="Mean",
    show_signal1=False,
    show_signal2=False,
    roi_name=ROI_NAME,
):
    """Show a native Slicer min-max scaled plot with dashed SD lines."""
    cleanup_old_plot_nodes()

    rows, fieldnames = _read_sorted_csv(csv_path)

    if not rows:
        slicer.util.errorDisplay("CSV has no rows.")
        return None

    missing = _missing_columns(fieldnames, ["DistanceToTarget_mm"])

    if missing:
        slicer.util.errorDisplay("CSV must contain DistanceToTarget_mm.")
        return None

    x = np.array(
        [ffloat(row.get("DistanceToTarget_mm")) for row in rows],
        dtype=float,
    )

    grey_columns, suffix = pick_grey_value_columns(
        fieldnames,
        grey_stat,
        roi_name=roi_name,
    )

    if not grey_columns:
        slicer.util.errorDisplay(f"No grey value columns found for {suffix}.")
        return None

    signal_specs = []

    def scaled_mean_and_sd(mean_values, sd_values):
        mean_values = np.asarray(mean_values, dtype=float)
        sd_values = np.asarray(sd_values, dtype=float)

        mask = np.isfinite(mean_values)

        if not np.any(mask):
            empty = np.full(mean_values.shape, np.nan, dtype=float)
            return empty, empty, empty

        minimum = float(np.nanmin(mean_values))
        maximum = float(np.nanmax(mean_values))
        value_range = maximum - minimum

        if abs(value_range) < 1e-12:
            center = np.full(mean_values.shape, 0.5, dtype=float)
            center[~mask] = np.nan
            error = np.full(mean_values.shape, np.nan, dtype=float)
        else:
            center = (mean_values - minimum) / value_range
            center[~mask] = np.nan
            error = sd_values / value_range

        return center, center + error, center - error

    def add_signal(mean_col, sd_col, label, color):
        mean_values = np.array(
            [ffloat(row.get(mean_col)) for row in rows],
            dtype=float,
        )

        sd_values = np.array(
            [ffloat(row.get(sd_col)) for row in rows],
            dtype=float,
        )

        center, plus, minus = scaled_mean_and_sd(mean_values, sd_values)

        safe_label = cleanup_label_for_plot_column(label)

        signal_specs.append(
            {
                "label": label,
                "center_col": f"{safe_label}_scaled",
                "plus_col": f"{safe_label}_scaled_plus_SD",
                "minus_col": f"{safe_label}_scaled_minus_SD",
                "center": center,
                "plus": plus,
                "minus": minus,
                "color": color,
            }
        )

    if show_signal1:
        missing = _missing_columns(fieldnames, ["Signal1_mean", "Signal1_SD"])

        if missing:
            slicer.util.errorDisplay(
                "Min-Max plot with SD requires Signal1_mean and Signal1_SD."
            )
            return None

        add_signal(
            mean_col="Signal1_mean",
            sd_col="Signal1_SD",
            label="Signal 1",
            color=COLOR_MAP["Signal1"],
        )

    if show_signal2:
        missing = _missing_columns(fieldnames, ["Signal2_mean", "Signal2_SD"])

        if missing:
            slicer.util.errorDisplay(
                "Min-Max plot with SD requires Signal2_mean and Signal2_SD."
            )
            return None

        add_signal(
            mean_col="Signal2_mean",
            sd_col="Signal2_SD",
            label="Signal 2",
            color=COLOR_MAP["Signal2"],
        )

    missing_sd_columns = []

    for column in grey_columns:
        sd_col = column.replace(grey_stat, "SD")

        if sd_col not in fieldnames:
            missing_sd_columns.append(sd_col)
            continue

        label = nice_volume_name(column, suffix)

        add_signal(
            mean_col=column,
            sd_col=sd_col,
            label=label,
            color=get_consistent_color(label),
        )

    if missing_sd_columns:
        slicer.util.errorDisplay(
            "Min-Max plot with SD requires these missing SD columns:\n"
            + "\n".join(missing_sd_columns)
        )
        return None

    table_node = get_or_create_node(
        "vtkMRMLTableNode",
        f"{PLOT_NODE_PREFIX}Table_MinMax_{roi_name}",
    )

    table = table_node.GetTable()
    table.Initialize()

    _add_float_column(table, "DistanceToTarget_mm")

    for spec in signal_specs:
        _add_float_column(table, spec["center_col"])
        _add_float_column(table, spec["plus_col"])
        _add_float_column(table, spec["minus_col"])

    table.SetNumberOfRows(len(rows))

    for row_index in range(len(rows)):
        _set_table_value(table, row_index, 0, x[row_index])

        column_index = 1

        for spec in signal_specs:
            for values_key in ["center", "plus", "minus"]:
                _set_table_value(
                    table,
                    row_index,
                    column_index,
                    spec[values_key][row_index],
                )
                column_index += 1

    chart_node = get_or_create_node(
        "vtkMRMLPlotChartNode",
        f"{PLOT_NODE_PREFIX}Chart_MinMax_{roi_name}",
    )

    _add_signal_series_to_chart(
        table_node=table_node,
        signal_specs=signal_specs,
        chart_node=chart_node,
        legend_suffix="scaled ± SD",
    )

    chart_node.SetTitle(f"Min-Max scaled signals with SD lines ({roi_name}, {grey_stat})")
    chart_node.SetXAxisTitle("Distance to target [mm]")
    chart_node.SetYAxisTitle("Scaled intensity [0-1]")
    chart_node.SetLegendVisibility(True)

    slicer.modules.plots.logic().ShowChartInLayout(chart_node)

    return chart_node


def align_y_zero(ax_left, ax_right, pad_frac=0.05):
    """Align the zero level of two Matplotlib y-axes."""
    def expand_to_include_zero(axis):
        y0, y1 = axis.get_ylim()
        lower, upper = (y0, y1) if y0 < y1 else (y1, y0)

        if lower <= 0 <= upper:
            return

        value_range = upper - lower

        if value_range <= 0:
            value_range = 1.0

        pad = pad_frac * value_range

        if 0 < lower:
            lower = 0 - pad
        elif 0 > upper:
            upper = 0 + pad

        axis.set_ylim(lower, upper)

    expand_to_include_zero(ax_left)
    expand_to_include_zero(ax_right)

    y_left_0, y_left_1 = ax_left.get_ylim()
    y_right_0, y_right_1 = ax_right.get_ylim()

    if abs(y_left_1 - y_left_0) < 1e-12:
        return

    if abs(y_right_1 - y_right_0) < 1e-12:
        return

    zero_rel_left = (0 - y_left_0) / (y_left_1 - y_left_0)

    right_range = y_right_1 - y_right_0
    new_y_right_0 = 0 - zero_rel_left * right_range
    new_y_right_1 = new_y_right_0 + right_range

    ax_right.set_ylim(new_y_right_0, new_y_right_1)


def show_plot_two_y_axes(
    csv_path,
    grey_stat="Mean",
    show_signal1=False,
    show_signal2=False,
    parent=None,
    roi_name=ROI_NAME,
):
    """Show a Matplotlib dual-y-axis plot with one signal and MRI grey values."""
    try:
        import matplotlib

        matplotlib.use("Agg")

        from matplotlib.figure import Figure
        from qt import QDialog, QPixmap, QVBoxLayout

    except Exception:
        slicer.util.errorDisplay(
            "Matplotlib is not available. Please install matplotlib in Slicer's Python."
        )
        return None

    rows, fieldnames = _read_sorted_csv(csv_path)

    if not rows:
        slicer.util.errorDisplay("CSV has no rows.")
        return None

    if show_signal1 == show_signal2:
        slicer.util.errorDisplay(
            "Two Y axes (raw) requires exactly one left-axis signal.\n\n"
            "Select either Show Signal 1 or Show Signal 2, but not both."
        )
        return None

    required = ["DistanceToTarget_mm"]

    if show_signal1:
        required += ["Signal1_mean", "Signal1_SD"]

    if show_signal2:
        required += ["Signal2_mean", "Signal2_SD"]

    missing = _missing_columns(fieldnames, required)

    if missing:
        slicer.util.errorDisplay(
            "CSV is missing required column(s):\n" + ", ".join(missing)
        )
        return None

    x = np.array(
        [ffloat(row.get("DistanceToTarget_mm")) for row in rows],
        dtype=float,
    )

    if show_signal1:
        left_signal = np.array(
            [ffloat(row.get("Signal1_mean")) for row in rows],
            dtype=float,
        )
        left_signal_sd = np.array(
            [ffloat(row.get("Signal1_SD")) for row in rows],
            dtype=float,
        )
        left_signal_label = "Signal1_mean"
        left_signal_color = COLOR_MAP["Signal1"]

    else:
        left_signal = np.array(
            [ffloat(row.get("Signal2_mean")) for row in rows],
            dtype=float,
        )
        left_signal_sd = np.array(
            [ffloat(row.get("Signal2_SD")) for row in rows],
            dtype=float,
        )
        left_signal_label = "Signal2_mean"
        left_signal_color = COLOR_MAP["Signal2"]

    grey_columns, suffix = pick_grey_value_columns(
        fieldnames,
        grey_stat,
        roi_name=roi_name,
    )

    if not grey_columns:
        slicer.util.errorDisplay(f"No grey value columns found for {suffix}.")
        return None

    missing_sd = []

    for column in grey_columns:
        sd_col = column.replace(grey_stat, "SD")

        if sd_col not in fieldnames:
            missing_sd.append(sd_col)

    if missing_sd:
        slicer.util.errorDisplay(
            "Two Y axes plot with SD requires these missing MRI SD columns:\n"
            + "\n".join(missing_sd)
        )
        return None

    figure = Figure(figsize=(12, 6), dpi=110)
    ax_left = figure.add_subplot(111)
    ax_right = ax_left.twinx()

    ax_left.set_xticks(x)
    ax_left.set_xticklabels(
        [f"{xi:.1f}" for xi in x],
        rotation=45,
        ha="right",
    )

    point_ids = [row.get("PointID", "") for row in rows]
    tissue_class_column = next(
        (column for column in fieldnames if column.endswith("_Segmentation_TissueClass")),
        None,
    )

    tissue_classes = (
        [row.get(tissue_class_column, "") for row in rows]
        if tissue_class_column
        else None
    )

    x_transform = ax_left.get_xaxis_transform()

    for index, xi in enumerate(x):
        ax_left.axvline(
            x=xi,
            linestyle=":",
            linewidth=1.0,
            alpha=0.35,
            color="k",
        )

        ax_left.text(
            xi,
            1.02,
            str(point_ids[index]),
            transform=x_transform,
            ha="right",
            va="bottom",
            rotation=45,
            rotation_mode="anchor",
            fontsize=9,
        )

        if tissue_classes is not None:
            ax_left.text(
                xi,
                1.09,
                str(tissue_classes[index]),
                transform=x_transform,
                ha="right",
                va="bottom",
                rotation=45,
                rotation_mode="anchor",
                fontsize=9,
            )

    if np.isfinite(x).any():
        x_range = float(np.nanmax(x) - np.nanmin(x))

        if x_range <= 0:
            x_range = 1.0

        label_x = float(np.nanmin(x) - 0.08 * x_range)

        ax_left.text(
            label_x,
            1.02,
            "PointID",
            transform=x_transform,
            ha="right",
            va="bottom",
            fontsize=9,
        )

        if tissue_classes is not None:
            ax_left.text(
                label_x,
                1.09,
                "TissueClass",
                transform=x_transform,
                ha="right",
                va="bottom",
                fontsize=9,
            )

    ax_left.set_xlabel("Distance to target [mm]")
    ax_left.set_ylabel(left_signal_label)
    ax_right.set_ylabel(f"MRI grey value ({grey_stat})")

    ax_left.set_title(
        f"Dual Y-axes: {left_signal_label} ± SD and MRI grey values\n"
        f"ROI: {roi_name} | Statistic: {grey_stat}",
        y=1.18,
    )

    ax_left.grid(True, alpha=0.3)

    left_signal_minus_sd = left_signal - left_signal_sd
    left_signal_plus_sd = left_signal + left_signal_sd

    band_color = lighten_color(left_signal_color, amount=0.65)

    ax_left.fill_between(
        x,
        left_signal_minus_sd,
        left_signal_plus_sd,
        color=band_color,
        alpha=0.30,
        linewidth=0,
    )

    ax_left.plot(
        x,
        left_signal_plus_sd,
        linestyle="--",
        linewidth=0.8,
        color=left_signal_color,
        alpha=0.45,
    )

    ax_left.plot(
        x,
        left_signal_minus_sd,
        linestyle="--",
        linewidth=0.8,
        color=left_signal_color,
        alpha=0.45,
    )

    left_signal_line, = ax_left.plot(
        x,
        left_signal,
        marker="o",
        linewidth=2,
        color=left_signal_color,
        label=f"{left_signal_label} (mean ± SD)",
    )

    grey_lines = []

    for column in grey_columns:
        y = np.array([ffloat(row.get(column)) for row in rows], dtype=float)
        sd_col = column.replace(grey_stat, "SD")
        y_sd = np.array([ffloat(row.get(sd_col)) for row in rows], dtype=float)

        y_minus_sd = y - y_sd
        y_plus_sd = y + y_sd

        name = nice_volume_name(column, suffix)
        color = get_consistent_color(name)
        band_color = lighten_color(color, amount=0.65)

        ax_right.fill_between(
            x,
            y_minus_sd,
            y_plus_sd,
            color=band_color,
            alpha=0.22,
            linewidth=0,
        )

        ax_right.plot(
            x,
            y_plus_sd,
            linestyle="--",
            linewidth=0.8,
            color=color,
            alpha=0.45,
        )

        ax_right.plot(
            x,
            y_minus_sd,
            linestyle="--",
            linewidth=0.8,
            color=color,
            alpha=0.45,
        )

        line, = ax_right.plot(
            x,
            y,
            marker="o",
            linewidth=2,
            color=color,
            label=f"{name} ({grey_stat} ± SD)",
        )

        grey_lines.append(line)

    ax_left.axhline(0, linewidth=1, alpha=0.3, color="black")
    ax_right.axhline(0, linewidth=1, alpha=0.3, color="black")

    align_y_zero(ax_left, ax_right)

    lines = [left_signal_line] + grey_lines
    labels = [line.get_label() for line in lines]

    ax_left.legend(
        lines,
        labels,
        loc="upper left",
        bbox_to_anchor=(1.12, 1.0),
        borderaxespad=0.0,
    )

    figure.subplots_adjust(top=0.82, right=0.72)

    buffer = BytesIO()
    figure.savefig(buffer, format="png", bbox_inches="tight")
    buffer.seek(0)

    pixmap = QPixmap()
    pixmap.loadFromData(buffer.getvalue(), "PNG")

    dialog = QDialog(parent or slicer.util.mainWindow())
    dialog.setWindowTitle("Signal Dual Y-Axes Plot")

    layout = QVBoxLayout(dialog)

    label = ResizableImageLabel()
    label.setOriginalPixmap(pixmap)

    layout.addWidget(label)
    layout.setContentsMargins(0, 0, 0, 0)

    dialog.resize(900, 500)
    dialog.show()

    return dialog


def show_plot_zscore_native(
    csv_path,
    grey_stat="Mean",
    show_signal1=False,
    show_signal2=False,
    roi_name=ROI_NAME,
):
    """Show a native Slicer z-score plot with dashed SD lines."""
    cleanup_old_plot_nodes()

    rows, fieldnames = _read_sorted_csv(csv_path)

    if not rows:
        slicer.util.errorDisplay("CSV has no rows.")
        return None

    required = ["DistanceToTarget_mm", "PointID"]

    if show_signal1:
        required += ["Signal1_mean", "Signal1_SD"]

    if show_signal2:
        required += ["Signal2_mean", "Signal2_SD"]

    missing = _missing_columns(fieldnames, required)

    if missing:
        slicer.util.errorDisplay(
            "Native Z-score plot requires these missing CSV columns:\n"
            + ", ".join(missing)
        )
        return None

    x = np.array(
        [ffloat(row.get("DistanceToTarget_mm")) for row in rows],
        dtype=float,
    )

    grey_columns, suffix = pick_grey_value_columns(
        fieldnames,
        grey_stat,
        roi_name=roi_name,
    )

    if not grey_columns:
        slicer.util.errorDisplay(f"No grey value columns found for {suffix}.")
        return None

    missing_sd = []

    for column in grey_columns:
        sd_col = column.replace(grey_stat, "SD")

        if sd_col not in fieldnames:
            missing_sd.append(sd_col)

    if missing_sd:
        slicer.util.errorDisplay(
            "Native Z-score plot requires SD columns for all MRI signals:\n"
            + "\n".join(missing_sd)
        )
        return None

    table_node = get_or_create_node(
        "vtkMRMLTableNode",
        f"{PLOT_NODE_PREFIX}Table_ZScore_{roi_name}",
    )

    table = table_node.GetTable()
    table.Initialize()

    _add_float_column(table, "DistanceToTarget_mm")

    signal_specs = []

    def add_signal(mean_col, sd_col, label, color):
        raw = np.array([ffloat(row.get(mean_col)) for row in rows], dtype=float)
        raw_sd = np.array([ffloat(row.get(sd_col)) for row in rows], dtype=float)

        z_values, signal_sd = zscore(raw)

        if not np.isfinite(signal_sd) or signal_sd < 1e-12:
            z_error = np.full(z_values.shape, np.nan, dtype=float)
        else:
            z_error = raw_sd / signal_sd

        safe_label = cleanup_label_for_plot_column(label)

        center_col = f"{safe_label}_z"
        plus_col = f"{safe_label}_z_plus_SD"
        minus_col = f"{safe_label}_z_minus_SD"

        _add_float_column(table, center_col)
        _add_float_column(table, plus_col)
        _add_float_column(table, minus_col)

        signal_specs.append(
            {
                "label": label,
                "center_col": center_col,
                "plus_col": plus_col,
                "minus_col": minus_col,
                "z": z_values,
                "z_plus": z_values + z_error,
                "z_minus": z_values - z_error,
                "color": color,
            }
        )

    if show_signal1:
        add_signal(
            mean_col="Signal1_mean",
            sd_col="Signal1_SD",
            label="Signal 1",
            color=COLOR_MAP["Signal1"],
        )

    if show_signal2:
        add_signal(
            mean_col="Signal2_mean",
            sd_col="Signal2_SD",
            label="Signal 2",
            color=COLOR_MAP["Signal2"],
        )

    for column in grey_columns:
        sd_col = column.replace(grey_stat, "SD")
        label = nice_volume_name(column, suffix)

        add_signal(
            mean_col=column,
            sd_col=sd_col,
            label=label,
            color=get_consistent_color(label),
        )

    table.SetNumberOfRows(len(rows))

    for row_index in range(len(rows)):
        _set_table_value(table, row_index, 0, x[row_index])

        column_index = 1

        for spec in signal_specs:
            for values_key in ["z", "z_plus", "z_minus"]:
                _set_table_value(
                    table,
                    row_index,
                    column_index,
                    spec[values_key][row_index],
                )
                column_index += 1

    chart_node = get_or_create_node(
        "vtkMRMLPlotChartNode",
        f"{PLOT_NODE_PREFIX}Chart_ZScore_{roi_name}",
    )

    _add_signal_series_to_chart(
        table_node=table_node,
        signal_specs=signal_specs,
        chart_node=chart_node,
        legend_suffix="z-score ± SD",
    )

    chart_node.SetTitle(f"Z-score with SD lines ({roi_name}, {grey_stat})")
    chart_node.SetXAxisTitle("Distance to target [mm]")
    chart_node.SetYAxisTitle("Z-score")
    chart_node.SetLegendVisibility(True)

    slicer.modules.plots.logic().ShowChartInLayout(chart_node)

    return chart_node