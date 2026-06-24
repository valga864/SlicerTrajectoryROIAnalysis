# Lib/segmentation.py

"""Segmentation helpers for ROI/segment overlap and segment statistics."""

import numpy as np
import slicer
import vtk


def get_segment_ids(segmentation_node):
    """Return all segment IDs from a segmentation node."""
    if segmentation_node is None or segmentation_node.GetSegmentation() is None:
        return []

    segmentation = segmentation_node.GetSegmentation()

    return [
        segmentation.GetNthSegmentID(index)
        for index in range(segmentation.GetNumberOfSegments())
    ]


def get_segment_name(segmentation_node, segment_id):
    """Return the display name of one segment."""
    if segmentation_node is None or segmentation_node.GetSegmentation() is None:
        return ""

    segment = segmentation_node.GetSegmentation().GetSegment(segment_id)

    if segment is None:
        return ""

    return segment.GetName() or ""


def export_segment_to_labelmap(segmentation_node, segment_id, reference_volume_node):
    """Export one segment into the geometry of a reference volume.

    Returns a temporary vtkMRMLLabelMapVolumeNode containing the selected segment.
    """
    if segmentation_node is None or segmentation_node.GetSegmentation() is None:
        raise ValueError("Segmentation node is invalid.")

    if reference_volume_node is None:
        raise ValueError("Reference volume node is invalid.")

    if not segment_id:
        raise ValueError("Segment ID is invalid.")

    segment = segmentation_node.GetSegmentation().GetSegment(segment_id)

    if segment is None:
        raise ValueError(f"Segment ID does not exist: {segment_id}")

    labelmap_node = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLLabelMapVolumeNode",
        f"tmp_{segmentation_node.GetName()}_{segment_id}",
    )

    segment_ids = vtk.vtkStringArray()
    segment_ids.InsertNextValue(segment_id)

    slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
        segmentation_node,
        segment_ids,
        labelmap_node,
        reference_volume_node,
    )

    return labelmap_node


def segment_to_mask(
    segmentation_node,
    segment_id,
    reference_volume_node,
    remove_temporary_node=True,
):
    """Return a boolean mask for one segment in reference volume geometry.

    The returned mask has the same shape and indexing order as
    slicer.util.arrayFromVolume(reference_volume_node), i.e. mask[k, j, i].
    """
    labelmap_node = export_segment_to_labelmap(
        segmentation_node,
        segment_id,
        reference_volume_node,
    )

    try:
        mask_array = slicer.util.arrayFromVolume(labelmap_node) > 0
        return mask_array.astype(bool)

    finally:
        if remove_temporary_node and labelmap_node is not None:
            slicer.mrmlScene.RemoveNode(labelmap_node)


def build_segment_masks_for_reference(segmentation_node, reference_volume_node):
    """Return boolean masks for all segments in reference volume geometry.

    The returned dictionary is keyed by segment ID.
    """
    masks = {}

    for segment_id in get_segment_ids(segmentation_node):
        segment_name = get_segment_name(segmentation_node, segment_id)

        try:
            mask = segment_to_mask(
                segmentation_node,
                segment_id,
                reference_volume_node,
                remove_temporary_node=True,
            )

            masks[segment_id] = {
                "name": segment_name,
                "mask": mask,
            }

        except Exception as exc:
            print(
                f"[WARN] Could not export segment "
                f"'{segment_name}' ({segment_id}): {exc}"
            )

    return masks


def roi_indices_to_mask(indices, reference_volume_node):
    """Convert ROI voxel indices into a boolean mask.

    indices must have shape (N, 3), with rows stored as (k, j, i).
    """
    volume_array = slicer.util.arrayFromVolume(reference_volume_node)
    roi_mask = np.zeros(volume_array.shape, dtype=bool)

    if indices is None or len(indices) == 0:
        return roi_mask

    indices = np.asarray(indices, dtype=int)

    k = indices[:, 0]
    j = indices[:, 1]
    i = indices[:, 2]

    roi_mask[k, j, i] = True

    return roi_mask


def compute_overlap_counts(roi_mask, segment_mask):
    """Compute voxel overlap between an ROI mask and one segment mask."""
    if roi_mask.shape != segment_mask.shape:
        raise ValueError("ROI mask and segment mask do not have the same shape.")

    roi_count = int(np.count_nonzero(roi_mask))
    segment_count = int(np.count_nonzero(segment_mask))
    overlap_count = int(np.count_nonzero(roi_mask & segment_mask))

    if roi_count > 0:
        overlap_fraction_of_roi = overlap_count / roi_count
    else:
        overlap_fraction_of_roi = float("nan")

    return {
        "roi_count": roi_count,
        "segment_count": segment_count,
        "overlap_count": overlap_count,
        "overlap_fraction_of_roi": overlap_fraction_of_roi,
    }


def classify_roi_by_segment_overlap(roi_mask, segment_masks, min_fraction=0.0):
    """Classify an ROI by the segment with the largest overlap."""
    best = {
        "segment_id": "",
        "segment_name": "",
        "overlap_count": 0,
        "overlap_fraction_of_roi": 0.0,
    }

    for segment_id, info in segment_masks.items():
        result = compute_overlap_counts(roi_mask, info["mask"])

        if result["overlap_count"] > best["overlap_count"]:
            best = {
                "segment_id": segment_id,
                "segment_name": info["name"],
                "overlap_count": result["overlap_count"],
                "overlap_fraction_of_roi": result["overlap_fraction_of_roi"],
            }

    if best["overlap_fraction_of_roi"] < min_fraction:
        best["segment_id"] = ""
        best["segment_name"] = "Unclassified"

    return best


def compute_selected_segment_reference_statistics(
    segmentation_node,
    segment_id,
    reference_volume_node,
    compute_roi_statistics,
):
    """Compute reference-volume statistics within one selected segment."""
    if segmentation_node is None or segmentation_node.GetSegmentation() is None:
        raise ValueError("Segmentation node is invalid.")

    if not segment_id:
        raise ValueError("Segment ID is invalid.")

    segment_mask = segment_to_mask(
        segmentation_node,
        segment_id,
        reference_volume_node,
        remove_temporary_node=True,
    )

    indices = np.argwhere(segment_mask)

    return compute_roi_statistics(reference_volume_node, indices)