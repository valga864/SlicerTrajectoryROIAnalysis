# Lib/geometry.py

"""Geometry helpers for converting between RAS and voxel coordinates."""

import numpy as np
import vtk
import slicer


def _vtk_multiply_point(matrix: vtk.vtkMatrix4x4, point4):
    """Multiply a 4x4 VTK matrix by a homogeneous 4D point."""
    out = [0.0, 0.0, 0.0, 0.0]

    for row in range(4):
        out[row] = (
            matrix.GetElement(row, 0) * point4[0]
            + matrix.GetElement(row, 1) * point4[1]
            + matrix.GetElement(row, 2) * point4[2]
            + matrix.GetElement(row, 3) * point4[3]
        )

    return out


def _clamp_int(value, lower, upper):
    """Clamp an integer value to the inclusive range [lower, upper]."""
    return int(max(lower, min(upper, int(value))))


def sphere_ijk_bounds_from_ras_aabb(volumeNode, center_ras, radius_mm):
    """Return voxel index bounds enclosing a spherical RAS region.

    The returned bounds are inclusive and ordered as:
    i0, i1, j0, j1, k0, k1.
    """
    volume_array = slicer.util.arrayFromVolume(volumeNode)
    k_size, j_size, i_size = volume_array.shape

    center = np.asarray(center_ras, dtype=float)
    radius_mm = float(radius_mm)

    ras_min = center - radius_mm
    ras_max = center + radius_mm

    ijk_to_ras = vtk.vtkMatrix4x4()
    volumeNode.GetIJKToRASMatrix(ijk_to_ras)

    ras_to_ijk = vtk.vtkMatrix4x4()
    vtk.vtkMatrix4x4.Invert(ijk_to_ras, ras_to_ijk)

    corners_ijk = []

    for x in (ras_min[0], ras_max[0]):
        for y in (ras_min[1], ras_max[1]):
            for z in (ras_min[2], ras_max[2]):
                ijk4 = _vtk_multiply_point(
                    ras_to_ijk,
                    [float(x), float(y), float(z), 1.0],
                )
                corners_ijk.append(ijk4[:3])

    corners_ijk = np.asarray(corners_ijk, dtype=float)

    ijk_min = np.floor(np.min(corners_ijk, axis=0) - 1.0).astype(int)
    ijk_max = np.ceil(np.max(corners_ijk, axis=0) + 1.0).astype(int)

    i0 = _clamp_int(ijk_min[0], 0, i_size - 1)
    i1 = _clamp_int(ijk_max[0], 0, i_size - 1)
    j0 = _clamp_int(ijk_min[1], 0, j_size - 1)
    j1 = _clamp_int(ijk_max[1], 0, j_size - 1)
    k0 = _clamp_int(ijk_min[2], 0, k_size - 1)
    k1 = _clamp_int(ijk_max[2], 0, k_size - 1)

    return i0, i1, j0, j1, k0, k1


def sphere_inside_indices(referenceVolumeNode, center_ras, radius_mm):
    """Return voxel indices inside a sphere centered in RAS coordinates.

    The returned array has shape (N, 3), with rows ordered as (k, j, i),
    matching the indexing order of arrays returned by slicer.util.arrayFromVolume.
    """
    ijk_to_ras = vtk.vtkMatrix4x4()
    referenceVolumeNode.GetIJKToRASMatrix(ijk_to_ras)

    center = np.asarray(center_ras, dtype=float)
    radius_mm = float(radius_mm)
    radius_squared = radius_mm * radius_mm

    i0, i1, j0, j1, k0, k1 = sphere_ijk_bounds_from_ras_aabb(
        referenceVolumeNode,
        center,
        radius_mm,
    )

    indices = []

    for k in range(k0, k1 + 1):
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                ras4 = _vtk_multiply_point(
                    ijk_to_ras,
                    [float(i), float(j), float(k), 1.0],
                )
                point_ras = np.asarray(ras4[:3], dtype=float)

                distance_squared = float(np.dot(point_ras - center, point_ras - center))

                if distance_squared <= radius_squared:
                    indices.append((k, j, i))

    if not indices:
        return np.zeros((0, 3), dtype=np.int32)

    return np.asarray(indices, dtype=np.int32)