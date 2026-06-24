# Lib/visualization.py

"""Visualization helpers for ROI models, voxel masks, and segmentations."""

import numpy as np
import slicer
import vtk

from Lib.constants import ROI_FOLDER_NAME, ROI_NAME, ROI_RADIUS_MM


def configure_segmentation_visibility(
    segmentation_node,
    show_3d=False,
    show_2d_fill=True,
    show_2d_outline=True,
    opacity_3d=0.0,
    opacity_2d_fill=0.45,
    opacity_2d_outline=1.0,
):
    """Configure reliable 2D/3D display settings for a Slicer segmentation."""
    if segmentation_node is None:
        return

    try:
        segmentation_node.CreateBinaryLabelmapRepresentation()
    except Exception as exc:
        print(f"[WARN] Could not create binary labelmap representation: {exc}")

    display_node = segmentation_node.GetDisplayNode()

    if display_node is None:
        segmentation_node.CreateDefaultDisplayNodes()
        display_node = segmentation_node.GetDisplayNode()

    if display_node is None:
        return

    display_node.SetVisibility(True)
    display_node.SetVisibility3D(bool(show_3d))
    display_node.SetOpacity3D(float(opacity_3d))
    display_node.SetVisibility2DFill(bool(show_2d_fill))
    display_node.SetVisibility2DOutline(bool(show_2d_outline))
    display_node.SetOpacity2DFill(float(opacity_2d_fill))
    display_node.SetOpacity2DOutline(float(opacity_2d_outline))


def _get_subject_hierarchy_node():
    """Return the scene subject hierarchy node, or None."""
    return slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(
        slicer.mrmlScene
    )


def _find_folder_item_id(subject_hierarchy_node, folder_name):
    """Return the item ID of a top-level Subject Hierarchy folder."""
    scene_item_id = subject_hierarchy_node.GetSceneItemID()

    child_ids = vtk.vtkIdList()
    subject_hierarchy_node.GetItemChildren(scene_item_id, child_ids, False)

    for index in range(child_ids.GetNumberOfIds()):
        item_id = child_ids.GetId(index)

        if subject_hierarchy_node.GetItemName(item_id) == folder_name:
            return item_id

    return None


def put_node_into_folder(node, folder_name):
    """Put a MRML node into a top-level Subject Hierarchy folder."""
    if node is None:
        return

    subject_hierarchy_node = _get_subject_hierarchy_node()

    if subject_hierarchy_node is None:
        return

    scene_item_id = subject_hierarchy_node.GetSceneItemID()
    folder_item_id = _find_folder_item_id(subject_hierarchy_node, folder_name)

    if folder_item_id is None:
        folder_item_id = subject_hierarchy_node.CreateFolderItem(
            scene_item_id,
            folder_name,
        )

    node_item_id = subject_hierarchy_node.GetItemByDataNode(node)

    if node_item_id:
        subject_hierarchy_node.SetItemParent(node_item_id, folder_item_id)


def create_sphere_roi_model(
    center_ras,
    radius_mm=ROI_RADIUS_MM,
    name=None,
    color=(1.0, 0.2, 0.2),
    opacity=0.25,
    folder_name=ROI_FOLDER_NAME,
):
    """Create a visible 3D sphere model at a given RAS position.

    This is used only for visualization. Quantitative voxel selection is
    performed separately in geometry.py.
    """
    center_ras = np.asarray(center_ras, dtype=float)

    if center_ras.shape != (3,):
        raise ValueError("center_ras must contain exactly three coordinates.")

    if name is None:
        name = f"{ROI_NAME}_ROI"

    sphere_source = vtk.vtkSphereSource()
    sphere_source.SetCenter(
        float(center_ras[0]),
        float(center_ras[1]),
        float(center_ras[2]),
    )
    sphere_source.SetRadius(float(radius_mm))
    sphere_source.SetThetaResolution(32)
    sphere_source.SetPhiResolution(32)
    sphere_source.Update()

    model_node = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLModelNode",
        name,
    )

    model_node.SetAndObservePolyData(sphere_source.GetOutput())
    model_node.CreateDefaultDisplayNodes()

    display_node = model_node.GetDisplayNode()

    if display_node:
        display_node.SetVisibility(True)
        display_node.SetColor(float(color[0]), float(color[1]), float(color[2]))
        display_node.SetOpacity(float(opacity))
        display_node.SetVisibility2D(True)
        display_node.SetSliceIntersectionThickness(2)

    put_node_into_folder(model_node, folder_name)

    return model_node


def create_roi_voxel_segmentation(
    indices_by_point,
    reference_volume_node,
    name=None,
    roi_name=None,
):
    """Create one segmentation node containing one segment per ROI point.

    Each segment marks exactly the selected ROI voxels. Input indices must
    be ordered as (k, j, i), matching slicer.util.arrayFromVolume().
    """
    if roi_name is None:
        roi_name = ROI_NAME

    if name is None:
        name = f"{roi_name} selected voxels"

    if reference_volume_node is None:
        raise ValueError("Reference volume node is invalid.")

    segmentation_node = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLSegmentationNode",
        name,
    )

    segmentation_node.SetReferenceImageGeometryParameterFromVolumeNode(
        reference_volume_node
    )
    segmentation_node.CreateDefaultDisplayNodes()

    reference_array = slicer.util.arrayFromVolume(reference_volume_node)

    for point_index, indices in enumerate(indices_by_point):
        mask = np.zeros(reference_array.shape, dtype=np.uint8)

        if indices is not None and len(indices) > 0:
            indices = np.asarray(indices, dtype=int)

            k = indices[:, 0]
            j = indices[:, 1]
            i = indices[:, 2]

            mask[k, j, i] = 1

        labelmap_node = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLLabelMapVolumeNode",
            f"tmp_{name}_P{point_index + 1}",
        )

        try:
            labelmap_node.CopyOrientation(reference_volume_node)
            slicer.util.updateVolumeFromArray(labelmap_node, mask)

            slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
                labelmap_node,
                segmentation_node,
            )

            segment_id = segmentation_node.GetSegmentation().GetNthSegmentID(point_index)
            segment = segmentation_node.GetSegmentation().GetSegment(segment_id)

            if segment is not None:
                segment.SetName(f"{roi_name}_P{point_index + 1}_voxels")
                segment.SetColor(1.0, 0.0, 1.0)

        finally:
            slicer.mrmlScene.RemoveNode(labelmap_node)

    configure_segmentation_visibility(
        segmentation_node,
        show_3d=False,
        show_2d_fill=True,
        show_2d_outline=True,
        opacity_3d=0.0,
        opacity_2d_fill=0.45,
        opacity_2d_outline=1.0,
    )

    put_node_into_folder(segmentation_node, ROI_FOLDER_NAME)

    return segmentation_node


def create_roi_voxel_cube_model(
    indices,
    reference_volume_node,
    name,
    color=(1.0, 0.0, 1.0),
    opacity=0.8,
):
    """Create a 3D cube model showing every selected voxel as a box."""
    if reference_volume_node is None:
        raise ValueError("Reference volume node is invalid.")

    if indices is None or len(indices) == 0:
        return None

    indices = np.asarray(indices, dtype=int)

    ijk_to_ras = vtk.vtkMatrix4x4()
    reference_volume_node.GetIJKToRASMatrix(ijk_to_ras)

    append = vtk.vtkAppendPolyData()

    for k, j, i in indices:
        cube = vtk.vtkCubeSource()
        cube.SetBounds(
            float(i),
            float(i + 1),
            float(j),
            float(j + 1),
            float(k),
            float(k + 1),
        )
        cube.Update()

        transform = vtk.vtkTransform()
        transform.SetMatrix(ijk_to_ras)

        transform_filter = vtk.vtkTransformPolyDataFilter()
        transform_filter.SetInputConnection(cube.GetOutputPort())
        transform_filter.SetTransform(transform)
        transform_filter.Update()

        append.AddInputData(transform_filter.GetOutput())

    append.Update()

    model_node = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLModelNode",
        name,
    )

    model_node.SetAndObservePolyData(append.GetOutput())
    model_node.CreateDefaultDisplayNodes()

    display_node = model_node.GetDisplayNode()

    if display_node:
        display_node.SetColor(*color)
        display_node.SetOpacity(float(opacity))
        display_node.SetVisibility(True)

    put_node_into_folder(model_node, ROI_FOLDER_NAME)

    return model_node


def remove_nodes_in_folder(folder_name):
    """Remove all data nodes inside a top-level Subject Hierarchy folder."""
    subject_hierarchy_node = _get_subject_hierarchy_node()

    if subject_hierarchy_node is None:
        return

    folder_item_id = _find_folder_item_id(subject_hierarchy_node, folder_name)

    if folder_item_id is None:
        return

    item_ids_to_remove = vtk.vtkIdList()
    subject_hierarchy_node.GetItemChildren(
        folder_item_id,
        item_ids_to_remove,
        True,
    )

    nodes_to_remove = []

    for index in range(item_ids_to_remove.GetNumberOfIds()):
        item_id = item_ids_to_remove.GetId(index)
        node = subject_hierarchy_node.GetItemDataNode(item_id)

        if node is not None:
            nodes_to_remove.append(node)

    for node in nodes_to_remove:
        slicer.mrmlScene.RemoveNode(node)