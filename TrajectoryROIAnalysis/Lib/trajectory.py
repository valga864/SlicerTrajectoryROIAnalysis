# Lib/trajectory.py

"""Trajectory helpers for Markups control points in RAS coordinates."""

import numpy as np


def get_point_position_ras(points_node, point_index):
    """Return one Markups control point position in RAS world coordinates."""
    if points_node is None:
        raise ValueError("Points node is invalid.")

    number_of_points = points_node.GetNumberOfControlPoints()

    if point_index < 0 or point_index >= number_of_points:
        raise IndexError(f"Point index out of range: {point_index}")

    position_ras = [0.0, 0.0, 0.0]
    points_node.GetNthControlPointPositionWorld(point_index, position_ras)

    return np.asarray(position_ras, dtype=float)


def get_all_point_positions_ras(points_node):
    """Return all Markups control point positions in RAS world coordinates."""
    if points_node is None:
        raise ValueError("Points node is invalid.")

    positions = []

    for point_index in range(points_node.GetNumberOfControlPoints()):
        positions.append(get_point_position_ras(points_node, point_index))

    return np.asarray(positions, dtype=float)


def validate_points_node(points_node, minimum_points=1):
    """Validate that the Markups node exists and contains enough points."""
    if points_node is None:
        raise ValueError("No Markups Fiducial node selected.")

    if points_node.GetNumberOfControlPoints() < minimum_points:
        raise ValueError(
            f"The selected Markups node must contain at least {minimum_points} point(s)."
        )


def compute_distances_to_target(positions_ras, target_index=-1):
    """Return distances from all points to one target point in millimeters."""
    positions = np.asarray(positions_ras, dtype=float)

    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError("positions_ras must have shape (N, 3).")

    if len(positions) == 0:
        return np.array([], dtype=float)

    if target_index < 0:
        target_index = len(positions) + target_index

    if target_index < 0 or target_index >= len(positions):
        raise IndexError(f"Target index out of range: {target_index}")

    target = positions[target_index]
    distances = np.linalg.norm(positions - target, axis=1)

    return distances.astype(float)


def offset_point_along_trajectory(point_ras, positions_ras, point_index, offset_mm=0.0):
    """Shift one point by offset_mm along the local trajectory direction."""
    positions = np.asarray(positions_ras, dtype=float)
    point = np.asarray(point_ras, dtype=float)

    number_of_points = len(positions)

    if number_of_points < 2:
        return point

    if point_index < 0 or point_index >= number_of_points:
        raise IndexError(f"Point index out of range: {point_index}")

    if point_index == 0:
        direction = positions[1] - positions[0]
    elif point_index == number_of_points - 1:
        direction = positions[-1] - positions[-2]
    else:
        direction = positions[point_index + 1] - positions[point_index - 1]

    norm = float(np.linalg.norm(direction))

    if norm < 1e-12:
        return point

    direction = direction / norm

    return point + float(offset_mm) * direction


def build_point_metadata(points_node, target_index=-1):
    """Return metadata for all Markups points."""
    validate_points_node(points_node)

    positions = get_all_point_positions_ras(points_node)
    distances = compute_distances_to_target(
        positions,
        target_index=target_index,
    )

    metadata = []

    for point_index, position in enumerate(positions):
        metadata.append(
            {
                "point_index": point_index,
                "point_id": f"P{point_index + 1}",
                "ras_x": float(position[0]),
                "ras_y": float(position[1]),
                "ras_z": float(position[2]),
                "distance_to_target_mm": float(distances[point_index]),
            }
        )

    return metadata