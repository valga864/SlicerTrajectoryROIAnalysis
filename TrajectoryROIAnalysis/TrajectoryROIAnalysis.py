import os
import vtk
import slicer
import importlib
import sys
import tempfile
import numpy as np
        
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin
from slicer.parameterNodeWrapper import parameterNodeWrapper

LIB_MODULES = [
    "Lib.constants",
    "Lib.csv_io",
    "Lib.geometry",
    "Lib.plotting",
    "Lib.roi",
    "Lib.segmentation",
    "Lib.statistics",
    "Lib.trajectory",
    "Lib.utils",
    "Lib.visualization",
]

for module_name in LIB_MODULES:
    if module_name in sys.modules:
        importlib.reload(sys.modules[module_name])

from Lib.constants import (
    DEFAULT_GREY_STAT,
    DEFAULT_PLOT_MODE,
    DEFAULT_ROI_CENTER_SOURCE,
    DEFAULT_CSV_COORDINATE_SYSTEM,
    CSV_ROI_CENTER_COLUMNS,
    REQUIRED_CSV_COLUMNS,
    ROI_RADIUS_MM,
    make_roi_name_from_radius,
    PREFERRED_MODALITIES,
    is_preferred_modality,
    is_excluded_volume_name,
    get_modality_key,
    DEFAULT_ROI_CENTER_OFFSET_MM,
    ROI_FOLDER_NAME,
)

from Lib.csv_io import (
    read_csv_rows,
    validate_required_columns,
    ensure_columns,
    write_csv_rows,
    sort_rows_by_distance,
    match_rows_to_points_by_point_id,
)

from Lib.visualization import (
    remove_nodes_in_folder,
    create_sphere_roi_model,
    create_roi_voxel_segmentation,
    create_roi_voxel_cube_model,
)

from Lib.plotting import (
    cleanup_old_plot_nodes,
    show_single_plot_minmax,
    show_plot_two_y_axes,
    show_plot_zscore_native,
)

from Lib.roi import (
    get_roi_prefix,
    compute_sphere_roi_statistics,
)

from Lib.statistics import write_statistics_to_row

from Lib.trajectory import (
    get_all_point_positions_ras,
    offset_point_along_trajectory,
    build_point_metadata,
)

from Lib.segmentation import (
    build_segment_masks_for_reference,
    roi_indices_to_mask,
    classify_roi_by_segment_overlap,
    compute_overlap_counts,
)

from Lib.utils import cleanup_string_for_csv, ffloat, make_offset_name


#
# TrajectoryROIAnalysis
#

class TrajectoryROIAnalysis(ScriptedLoadableModule):
    """Uses ScriptedLoadableModule base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)

        self.parent.title = _("Trajectory ROI Analysis")
        self.parent.categories = [translate("qSlicerAbstractCoreModule", "Quantification")]
        self.parent.dependencies = []
        self.parent.contributors = ["Valentina Gäumann (Department of Biomedical Engineering, Linköping University)"]

        self.parent.helpText = _("""
            Compute spherical ROI statistics along biopsy trajectory points.

            The ROI radius is user-defined. The ROI name is derived from the selected
            radius, for example radius 2.0 mm creates SphereR2 and radius 1.0 mm
            creates SphereR1.

            Voxel selection is based on voxel centers inside the spherical ROI.
            The module exports MRI grey-value statistics and visualizes Signal1,
            Signal2, and MRI intensity values along the trajectory.
            """)

        self.parent.acknowledgementText = _("""
    Developed for trajectory-based ROI analysis in 3D Slicer.
    """)

#
# TrajectoryROIAnalysisParameterNode
#

@parameterNodeWrapper
class TrajectoryROIAnalysisParameterNode:
    pointsNode: slicer.vtkMRMLMarkupsFiducialNode
    inputCsvPath: str = ""
    greyStat: str = DEFAULT_GREY_STAT
    plotMode: str = DEFAULT_PLOT_MODE
    roiRadiusMm: float = ROI_RADIUS_MM
    roiCenterSource: str = DEFAULT_ROI_CENTER_SOURCE
    csvCoordinateSystem: str = DEFAULT_CSV_COORDINATE_SYSTEM
    externalToRasTransformNode: slicer.vtkMRMLTransformNode
    showSignal1: bool = False
    showSignal2: bool = False
    roiCenterOffsetMm: float = DEFAULT_ROI_CENTER_OFFSET_MM
    createRoiCompositionReport: bool = True
    createOutputCsv: bool = True
    createVoxelCubeDebugModels: bool = False

    normalizationSegmentationNode: slicer.vtkMRMLSegmentationNode
    normalizationSegmentId: str = ""

#
# TrajectoryROIAnalysisWidget
#

class TrajectoryROIAnalysisWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Uses ScriptedLoadableModuleWidget base class, available at:
    https://github.com/Slicer/Slicer/blob/main/Base/Python/slicer/ScriptedLoadableModule.py
    """

    def __init__(self, parent=None) -> None:
        """Called when the user opens the module the first time and the widget is initialized."""
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)  # needed for parameter node observation
        self.logic = None
        self._parameterNode = None
        self._parameterNodeGuiTag = None

    def setup(self) -> None:
        """Called when the user opens the module the first time and the widget is initialized."""
        ScriptedLoadableModuleWidget.setup(self)

        # Load widget from .ui file (created by Qt Designer).
        # Additional widgets can be instantiated manually and added to self.layout.
        uiWidget = slicer.util.loadUI(self.resourcePath("UI/TrajectoryROIAnalysis.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)

        # Keep form labels aligned across collapsible sections
        for label_name in [
            "labelInputCsv",
            "labelRoiRadius",
            "labelRoiCenterOffset",
            "labelRoiCenterSource",
            "labelCsvCoordinateSystem",
            "labelNormalizationSegmentation",
            "labelNormalizationSegment",
            "labelPlotMode",
            "labelShowSignal1",
            "labelShowSignal2",
            "labelCreateRoiCompositionReport",
            "labelCreateOutputCsv",
            "labelCreateVoxelCubeDebugModels",
        ]:
            if hasattr(self.ui, label_name):
                getattr(self.ui, label_name).setMinimumWidth(130)

        # Set scene in MRML widgets. Make sure that in Qt designer the top-level qMRMLWidget's
        # "mrmlSceneChanged(vtkMRMLScene*)" signal in is connected to each MRML widget's.
        # "setMRMLScene(vtkMRMLScene*)" slot.
        uiWidget.setMRMLScene(slicer.mrmlScene)

        # Create logic class. Logic implements all computations that should be possible to run
        # in batch mode, without a graphical user interface.
        self.logic = TrajectoryROIAnalysisLogic()

        # Connections

        # These connections ensure that we update parameter node when scene is closed
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose)
        self.ui.normalizationSegmentationSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onNormalizationSegmentationChanged)
        self.ui.normalizationSegmentComboBox.connect("currentIndexChanged(int)", self.onGuiChanged)

        self.ui.roiCenterSourceMarkupsRadioButton.connect("toggled(bool)", self.onRoiCenterSourceChanged)
        self.ui.roiCenterSourceCsvRadioButton.connect("toggled(bool)", self.onRoiCenterSourceChanged)
        self.ui.csvCoordinateSystemRasRadioButton.connect("toggled(bool)", self.onRoiCenterSourceChanged)
        self.ui.csvCoordinateSystemExternalRadioButton.connect("toggled(bool)", self.onRoiCenterSourceChanged)
        self.ui.externalToRasTransformSelector.connect("currentNodeChanged(vtkMRMLNode*)",self.onGuiChanged,)


        # Buttons
        self.ui.applyButton.connect("clicked(bool)", self.onApplyButton)
        self.ui.inputCsvPathLineEdit.connect("currentPathChanged(QString)", self.onGuiChanged)
        self.ui.plotModeComboBox.connect("currentIndexChanged(int)", self.onGuiChanged)
        self.ui.roiRadiusSpinBox.connect("valueChanged(double)", self.onGuiChanged)
        self.ui.roiCenterOffsetSpinBox.connect("valueChanged(double)", self.onGuiChanged)
        self.ui.createRoiCompositionReportCheckBox.connect("toggled(bool)",self.onGuiChanged,)
        self.ui.createOutputCsvCheckBox.connect("toggled(bool)",self.onGuiChanged,)
        self.ui.createVoxelCubeDebugModelsCheckBox.connect("toggled(bool)",self.onGuiChanged,)
        self.ui.showSignal1CheckBox.connect("toggled(bool)", self.onGuiChanged)
        self.ui.showSignal2CheckBox.connect("toggled(bool)", self.onGuiChanged)

        self.ui.helpPointsButton.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "Select the Markups Fiducial node containing the biopsy trajectory points.\n\n"
                "PointID in the CSV must match the Slicer point index:\n"
                "P1 = PointID 0, P2 = PointID 1, etc.",
                windowTitle="Measurement points",
            )
        )

        self.ui.helpCsvButton.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "Required CSV columns:\n"
                "- PointID\n"
                "- DistanceToTarget_mm\n\n"
                "Required for SD plots when Signal1 is shown:\n"
                "- Signal1_mean\n"
                "- Signal1_SD\n\n"
                "Optional signal 2 columns:\n"
                "- Signal2_mean\n"
                "- Signal2_SD\n\n"
                "Required when ROI center source is CSV coordinates:\n"
                "- Center_X\n"
                "- Center_Y\n"
                "- Center_Z",
                windowTitle="Input CSV",
            )
        )

        self.ui.helpRoiCenterSourceButton.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "Choose where the spherical ROI centers come from.\n\n"
                "Markups points:\n"
                "The ROI centers are based on the selected Slicer Markups points. "
                "The optional ROI center offset shifts the center along the local trajectory direction.\n\n"
                "CSV coordinates:\n"
                "The ROI centers are read from CSV columns:\n"
                "- Center_X\n"
                "- Center_Y\n"
                "- Center_Z\n\n"
                "Coordinate system:\n"
                "Use RAS if the CSV coordinates are already in Slicer RAS coordinates.\n"
                "Use External if the CSV coordinates are in External space; then select a "
                "External-to-RAS transform node.",
                windowTitle="ROI center source",
            )
        )

        self.ui.helpNormalizationSegmentationButton.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "Select one segmentation containing the tissue-class segments.\n\n"
                "The segmentation is used to classify each ROI by overlap with the selected "
                "segments. It is also used for the ROI composition report.",
                windowTitle="Segmentation",
            )
        )

        self.ui.helpNormalizationSegmentButton.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "Select the segment used as normalization reference.\n\n"
                "If a normalization segment is selected, the mean intensity inside this "
                "segment is used to create normalized MRI mean columns in the output CSV.",
                windowTitle="Normalization segment",
            )
        )

        self.ui.helpPlotModeButton.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "Scaled (Min-Max):\n"
                "Signal1, Signal2, and MRI signals are scaled to 0–1. "
                "Mean curves are shown with ±SD lines when SD columns are available.\n\n"
                "Z-score with SD:\n"
                "Signals are z-score normalized across trajectory points. "
                "SD is shown as ±SD lines or bands.\n\n"
                "Two Y axes (raw):\n"
                "Shows exactly one left-axis signal: either Signal1 or Signal2. "
                "Do not select both. MRI grey values are shown on the right axis. "
                "Mean curves are shown with ±SD bands.",
                windowTitle="Plot mode",
            )
        )

        self.ui.helpSignal1Button.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "If checked, Signal1_mean from the CSV is added to the plots.\n\n"
                "For plots with SD visualization, the CSV must also contain Signal1_SD.\n\n"
                "For Two Y axes (raw), Signal1 can be selected only if Signal2 is not selected.",
                windowTitle="Show signal 1",
            )
        )

        self.ui.helpSignal2Button.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "If checked, Signal2_mean from the CSV is added to the plots.\n\n"
                "For plots with SD visualization, the CSV must also contain Signal2_SD.\n\n"
                "For Two Y axes (raw), Signal2 can be selected only if Signal1 is not selected.",
                windowTitle="Show signal 2",
            )
        )

        self.ui.helpRoiRadiusButton.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "Set the spherical ROI radius in millimeters.\n\n"
                "Example:\n"
                "- Radius 2.0 mm creates SphereR2\n"
                "- Radius 1.5 mm creates SphereR1p5\n"
                "- Radius 1.0 mm creates SphereR1\n\n"
                "The selected radius is used for voxel selection, statistics, "
                "ROI visualization, segmentation export, CSV column names, and reports.\n\n"
                "Voxel selection is based on voxel centers. If no voxel center lies inside "
                "the ROI, increase the radius or check the ROI center coordinates.",
                windowTitle="ROI radius",
            )
        )

        self.ui.helpRoiCenterOffsetButton.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "Set the ROI center offset in millimeters along the local trajectory direction.\n\n"
                "0.0 mm = ROI center stays exactly on the selected Markups point or CSV coordinate\n"
                "+0.5 mm = shift forward along the trajectory\n"
                "-0.5 mm = shift backward along the trajectory",
                windowTitle="ROI center offset",
            )
        )

        self.ui.helpCreateRoiCompositionReportButton.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "If enabled, a text report is written next to the input CSV.\n\n"
                "The report summarizes, for each ROI, how many ROI voxels overlap with each "
                "segment in the selected segmentation.\n\n"
                "The report is mainly intended for quality control and documentation.",
                windowTitle="ROI composition report",
            )
        )

        self.ui.helpCreateOutputCsvButton.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "If enabled, a results CSV is written next to the input CSV.\n\n"
                "The output CSV contains the original input columns plus the computed ROI "
                "statistics for each selected MRI volume.\n\n"
                "If disabled, plots are still generated using a temporary internal CSV, "
                "but no results CSV is saved permanently.",
                windowTitle="Output CSV",
            )
        )

        self.ui.helpCsvCoordinateSystemButton.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "Choose the coordinate system used by Center_X, Center_Y, and Center_Z in the input CSV.\n\n"
                "RAS:\n"
                "Use this if the CSV coordinates are already in Slicer RAS world coordinates.\n\n"
                "External:\n"
                "Use this if the CSV coordinates come from an external coordinate system. "
                "In this case, select an External-to-RAS transform node. "
                "The CSV center coordinates are first transformed into Slicer RAS space, "
                "and the optional ROI center offset is then applied along the trajectory.",
                windowTitle="CSV coordinate system",
            )
        )

        self.ui.helpExternalToRasTransformButton.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "Select the transform that maps the external CSV coordinate system into "
                "Slicer RAS world coordinates.\n\n"
                "This is only required when CSV coordinate system is set to External.\n\n"
                "The transform is applied to each CSV center point:\n"
                "External Center_X/Center_Y/Center_Z → Slicer RAS.\n\n"
                "After this transformation, the optional ROI center offset is applied "
                "along the local trajectory direction in RAS space.",
                windowTitle="External to RAS transform",
            )
        )

        self.ui.helpVoxelCubeDebugModelsButton.connect(
            "clicked(bool)",
            lambda checked: slicer.util.infoDisplay(
                "Create one 3D cube model for every selected ROI voxel.\n\n"
                "This option is intended for debugging and visual quality control only.\n\n"
                "It can become slow or memory-intensive for large ROIs, small voxel sizes, "
                "or many trajectory points because each selected voxel is converted into "
                "individual cube geometry.\n\n"
                "The standard ROI voxel segmentation is still created and is usually sufficient "
                "for checking which voxels were selected.",
                windowTitle="Debug voxel cubes",
            )
        )

        # Make sure parameter node is initialized (needed for module reload)
        self.initializeParameterNode()
           
    def cleanup(self) -> None:
        """Called when the application closes and the module widget is destroyed."""
        self.removeObservers()

    def enter(self) -> None:
        """Called each time the user opens this module."""
        # Make sure parameter node exists and observed
        self.initializeParameterNode()

    def exit(self) -> None:
        """Called each time the user opens a different module."""
        # Do not react to parameter node changes (GUI will be updated when the user enters into the module)
        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self._parameterNodeGuiTag = None
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._checkCanApply)

    def onSceneStartClose(self, caller, event) -> None:
        """Called just before the scene is closed."""
        # Parameter node will be reset, do not use it anymore
        self.setParameterNode(None)

    def onSceneEndClose(self, caller, event) -> None:
        """Called just after the scene is closed."""
        # If this module is shown while the scene is closed then recreate a new parameter node immediately
        if self.parent.isEntered:
            self.initializeParameterNode()

    def initializeParameterNode(self) -> None:
        self.setParameterNode(self.logic.getParameterNode())

        if self._parameterNode and not self._parameterNode.pointsNode:
            first_points_node = slicer.mrmlScene.GetFirstNodeByClass(
                "vtkMRMLMarkupsFiducialNode"
            )
            if first_points_node:
                self._parameterNode.pointsNode = first_points_node

    def setParameterNode(self, inputParameterNode: TrajectoryROIAnalysisParameterNode | None) -> None:
        """
        Set and observe parameter node.
        Observation is needed because when the parameter node is changed then the GUI must be updated immediately.
        """

        if self._parameterNode:
            self._parameterNode.disconnectGui(self._parameterNodeGuiTag)
            self.removeObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._checkCanApply)
        self._parameterNode = inputParameterNode
        if self._parameterNode:
            # Note: in the .ui file, a Qt dynamic property called "SlicerParameterName" is set on each
            # ui element that needs connection.
            self._parameterNodeGuiTag = self._parameterNode.connectGui(self.ui)
            if hasattr(self.ui, "roiCenterSourceMarkupsRadioButton"):
                self.ui.roiCenterSourceMarkupsRadioButton.checked = (
                    self._parameterNode.roiCenterSource == "Markups points"
                )
                self.ui.roiCenterSourceCsvRadioButton.checked = (
                    self._parameterNode.roiCenterSource == "CSV coordinates"
                )

            if hasattr(self.ui, "csvCoordinateSystemRasRadioButton"):
                self.ui.csvCoordinateSystemRasRadioButton.checked = (
                    self._parameterNode.csvCoordinateSystem == "RAS"
                )
                self.ui.csvCoordinateSystemExternalRadioButton.checked = (
                    self._parameterNode.csvCoordinateSystem == "External"
                )

            if hasattr(self.ui, "roiRadiusSpinBox"):
                self.ui.roiRadiusSpinBox.value = float(self._parameterNode.roiRadiusMm)

            if hasattr(self.ui, "roiCenterOffsetSpinBox"):
                self.ui.roiCenterOffsetSpinBox.value = float(self._parameterNode.roiCenterOffsetMm)

            self.onRoiCenterSourceChanged()
            self.addObserver(self._parameterNode, vtk.vtkCommand.ModifiedEvent, self._checkCanApply)
            self._checkCanApply()


    def onNormalizationSegmentationChanged(self, node=None):
        self._updateNormalizationSegmentComboBox()
        self.onGuiChanged()


    def _updateNormalizationSegmentComboBox(self):
        if not hasattr(self.ui, "normalizationSegmentComboBox"):
            return

        combo = self.ui.normalizationSegmentComboBox
        current_id = self._parameterNode.normalizationSegmentId if self._parameterNode else ""

        combo.blockSignals(True)
        combo.clear()

        combo.addItem("None", "")

        seg_node = self.ui.normalizationSegmentationSelector.currentNode()
        if seg_node and seg_node.GetSegmentation():
            segmentation = seg_node.GetSegmentation()
            for i in range(segmentation.GetNumberOfSegments()):
                segment_id = segmentation.GetNthSegmentID(i)
                segment = segmentation.GetSegment(segment_id)
                combo.addItem(segment.GetName(), segment_id)

        index = combo.findData(current_id)
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.setCurrentIndex(0)

        combo.blockSignals(False)

    def onRoiCenterSourceChanged(self, *args):
        if not self._parameterNode:
            return

        use_markups = self.ui.roiCenterSourceMarkupsRadioButton.checked
        use_csv = self.ui.roiCenterSourceCsvRadioButton.checked
        use_external = self.ui.csvCoordinateSystemExternalRadioButton.checked

        # Show Markups selector only when ROI centers come from Markups points.
        self.ui.labelPoints.visible = use_markups
        self.ui.pointsSelectorContainer.visible = use_markups

        # Show CSV coordinate system options only when ROI centers come from CSV coordinates.
        self.ui.labelCsvCoordinateSystem.visible = use_csv
        self.ui.csvCoordinateSystemContainer.visible = use_csv

        show_external_options = use_csv and use_external

        self.ui.labelExternalToRasTransform.visible = show_external_options
        self.ui.externalToRasTransformContainer.visible = show_external_options

        self.onGuiChanged()

    def onGuiChanged(self, *args):
        if not self._parameterNode:
            return

        if hasattr(self.ui, "inputCsvPathLineEdit"):
            self._parameterNode.inputCsvPath = self.ui.inputCsvPathLineEdit.currentPath or ""

        if hasattr(self.ui, "plotModeComboBox"):
            self._parameterNode.plotMode = self.ui.plotModeComboBox.currentText

        if hasattr(self.ui, "roiRadiusSpinBox"):
            self._parameterNode.roiRadiusMm = float(self.ui.roiRadiusSpinBox.value)

        if hasattr(self.ui, "roiCenterOffsetSpinBox"):
            self._parameterNode.roiCenterOffsetMm = float(self.ui.roiCenterOffsetSpinBox.value)

        if hasattr(self.ui, "createRoiCompositionReportCheckBox"):
            self._parameterNode.createRoiCompositionReport = (
                self.ui.createRoiCompositionReportCheckBox.checked
            )

        if hasattr(self.ui, "createOutputCsvCheckBox"):
            self._parameterNode.createOutputCsv = (
                self.ui.createOutputCsvCheckBox.checked
            )

        if hasattr(self.ui, "createVoxelCubeDebugModelsCheckBox"):
            self._parameterNode.createVoxelCubeDebugModels = (
                self.ui.createVoxelCubeDebugModelsCheckBox.checked
            )

        if hasattr(self.ui, "showSignal1CheckBox"):
            self._parameterNode.showSignal1 = self.ui.showSignal1CheckBox.checked

        if hasattr(self.ui, "showSignal2CheckBox"):
            self._parameterNode.showSignal2 = self.ui.showSignal2CheckBox.checked

        if hasattr(self.ui, "normalizationSegmentationSelector"):
            self._parameterNode.normalizationSegmentationNode = (
                self.ui.normalizationSegmentationSelector.currentNode()
            )

        if hasattr(self.ui, "normalizationSegmentComboBox"):
            if self.ui.normalizationSegmentComboBox.count > 0:
                self._parameterNode.normalizationSegmentId = (
                    self.ui.normalizationSegmentComboBox.itemData(
                        self.ui.normalizationSegmentComboBox.currentIndex
                    ) or ""
                )
            else:
                self._parameterNode.normalizationSegmentId = ""

        if hasattr(self.ui, "roiCenterSourceMarkupsRadioButton"):
            if self.ui.roiCenterSourceMarkupsRadioButton.checked:
                self._parameterNode.roiCenterSource = "Markups points"
            else:
                self._parameterNode.roiCenterSource = "CSV coordinates"

        if hasattr(self.ui, "csvCoordinateSystemRasRadioButton"):
            if self.ui.csvCoordinateSystemRasRadioButton.checked:
                self._parameterNode.csvCoordinateSystem = "RAS"
            else:
                self._parameterNode.csvCoordinateSystem = "External"

        if hasattr(self.ui, "externalToRasTransformSelector"):
            self._parameterNode.externalToRasTransformNode = (
                self.ui.externalToRasTransformSelector.currentNode()
            )

    def _checkCanApply(self, caller=None, event=None) -> None:
        use_markups = (
            self._parameterNode.roiCenterSource == "Markups points"
        )

        points_node = self._parameterNode.pointsNode
        points_ok = (
            not use_markups
            or (
                points_node is not None
                and points_node.GetNumberOfControlPoints() >= 1
            )
        )

        csv_path = (self._parameterNode.inputCsvPath or "").strip()
        csv_ok = bool(csv_path) and os.path.exists(csv_path)

        if points_ok and csv_ok:
            self.ui.applyButton.enabled = True
            self.ui.applyButton.toolTip = _("Run ROI trajectory analysis.")
        else:
            self.ui.applyButton.enabled = False
            if not points_ok:
                self.ui.applyButton.toolTip = _("Select Markups measurement points.")
            elif not csv_ok:
                self.ui.applyButton.toolTip = _("Select a valid input CSV file.")

    def onApplyButton(self) -> None:
        self.onGuiChanged()

        with slicer.util.tryWithErrorDisplay(
            _("Failed to run ROI trajectory analysis."),
            waitCursor=True,
        ):
            output_csv_path = self.logic.run(
                points_node=self._parameterNode.pointsNode,
                input_csv_path=self._parameterNode.inputCsvPath,
                grey_stat=self._parameterNode.greyStat,
                plot_mode=self.ui.plotModeComboBox.currentText,
                roi_radius_mm=self._parameterNode.roiRadiusMm,
                roi_center_offset_mm=self._parameterNode.roiCenterOffsetMm,
                create_roi_composition_report=self._parameterNode.createRoiCompositionReport,
                create_output_csv=self._parameterNode.createOutputCsv,
                show_signal1=self._parameterNode.showSignal1,
                show_signal2=self._parameterNode.showSignal2,
                roi_center_source=self._parameterNode.roiCenterSource,
                csv_coordinate_system=self._parameterNode.csvCoordinateSystem,
                normalization_segmentation_node=self._parameterNode.normalizationSegmentationNode,
                normalization_segment_id=self._parameterNode.normalizationSegmentId,
                external_to_ras_transform_node=self._parameterNode.externalToRasTransformNode,
                create_voxel_cube_debug_models=self._parameterNode.createVoxelCubeDebugModels,
            )

            if output_csv_path:
                slicer.util.infoDisplay(
                    f"ROI analysis completed.\n\nOutput CSV:\n{output_csv_path}"
                )
            else:
                slicer.util.infoDisplay(
                    "ROI analysis completed.\n\nNo output CSV was written."
                )

#
# TrajectoryROIAnalysisLogic
#

class TrajectoryROIAnalysisLogic(ScriptedLoadableModuleLogic):

    def __init__(self) -> None:
        ScriptedLoadableModuleLogic.__init__(self)

    def getParameterNode(self):
        return TrajectoryROIAnalysisParameterNode(super().getParameterNode())

    def validateInputs(self, points_node, csv_path, roi_center_source):
        use_markups = roi_center_source == "Markups points"

        if use_markups:
            if points_node is None:
                raise ValueError("No Markups Fiducial node selected.")

            if points_node.GetNumberOfControlPoints() < 1:
                raise ValueError("The Markups node must contain at least one point.")

        if not csv_path:
            raise ValueError("No input CSV selected.")

        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Input CSV does not exist: {csv_path}")

        rows, fieldnames = read_csv_rows(csv_path)
        validate_required_columns(fieldnames, REQUIRED_CSV_COLUMNS)

        if not rows:
            raise ValueError("Input CSV contains no rows.")
        
    def write_roi_composition_report(self, txt_path, report_lines):
        os.makedirs(os.path.dirname(txt_path), exist_ok=True)

        with open(txt_path, "w", encoding="utf-8") as f:
            for line in report_lines:
                f.write(line + "\n")

    def get_roi_center_ras(
        self,
        roi_center_positions_ras,
        point_index,
        roi_center_offset_mm=DEFAULT_ROI_CENTER_OFFSET_MM,
    ):
        """
        Return the final ROI center in Slicer RAS coordinates.

        roi_center_positions_ras already contains one RAS coordinate per point.
        - Markups mode: coordinates come from the selected Markups node.
        - CSV RAS mode: coordinates come from Center_X/Y/Z.
        - CSV External mode: coordinates come from Center_X/Y/Z and are transformed to RAS first.

        The optional offset is then applied along the local trajectory direction.
        roi_center_offset_mm = 0.0 means no shift.
        """
        if roi_center_positions_ras is None:
            raise ValueError("Internal error: ROI center positions were not initialized.")

        original_center_ras = roi_center_positions_ras[point_index]

        return offset_point_along_trajectory(
            original_center_ras,
            roi_center_positions_ras,
            point_index,
            offset_mm=roi_center_offset_mm,
        )

    def transform_point_with_transform_node(self, point_xyz, transform_node):
        if transform_node is None:
            raise ValueError(
                "External CSV coordinates require a External-to-RAS transform node."
            )

        transform_to_world = vtk.vtkGeneralTransform()
        transform_node.GetTransformToWorld(transform_to_world)

        out = [0.0, 0.0, 0.0]
        transform_to_world.TransformPoint(
            [
                float(point_xyz[0]),
                float(point_xyz[1]),
                float(point_xyz[2]),
            ],
            out,
        )

        return np.array(out, dtype=float)
    
    def build_roi_center_positions_ras_from_rows(
        self,
        rows,
        roi_center_source,
        points_node=None,
        csv_coordinate_system="RAS",
        external_to_ras_transform_node=None,
    ):


        if roi_center_source == "Markups points":
            return get_all_point_positions_ras(points_node)

        if roi_center_source != "CSV coordinates":
            raise ValueError(f"Unknown ROI center source: {roi_center_source}")

        positions = []

        for row in rows:
            coords = np.array(
                [
                    ffloat(row.get("Center_X")),
                    ffloat(row.get("Center_Y")),
                    ffloat(row.get("Center_Z")),
                ],
                dtype=float,
            )

            if not np.all(np.isfinite(coords)):
                raise ValueError(
                    f"Invalid CSV ROI center coordinates for PointID {row.get('PointID')}. "
                    "Expected finite numeric values in Center_X, Center_Y, Center_Z."
                )

            if csv_coordinate_system == "RAS":
                center_ras = coords

            elif csv_coordinate_system == "External":
                center_ras = self.transform_point_with_transform_node(
                    coords,
                    external_to_ras_transform_node,
                )

            else:
                raise ValueError(
                    f"Unknown CSV coordinate system: {csv_coordinate_system}"
                )

            positions.append(center_ras)

        return np.asarray(positions, dtype=float)

    def _validate_roi_parameters(self, roi_radius_mm, roi_center_offset_mm):
        try:
            roi_radius_mm = float(roi_radius_mm)
        except Exception:
            raise ValueError("ROI radius must be a numeric value.")

        if roi_radius_mm <= 0:
            raise ValueError("ROI radius must be larger than 0 mm.")

        try:
            roi_center_offset_mm = float(roi_center_offset_mm)
        except Exception:
            raise ValueError("ROI center offset must be a numeric value.")

        roi_name = make_roi_name_from_radius(roi_radius_mm)

        return roi_radius_mm, roi_center_offset_mm, roi_name

    
    def _load_and_validate_csv(self, input_csv_path, roi_center_source):
        rows, fieldnames = read_csv_rows(input_csv_path)
        validate_required_columns(fieldnames, REQUIRED_CSV_COLUMNS)

        if not rows:
            raise ValueError("Input CSV contains no rows.")

        roi_center_source = (roi_center_source or DEFAULT_ROI_CENTER_SOURCE).strip()

        if roi_center_source == "CSV coordinates":
            validate_required_columns(fieldnames, CSV_ROI_CENTER_COLUMNS)
        elif roi_center_source != "Markups points":
            raise ValueError(f"Unknown ROI center source: {roi_center_source}")

        return rows, fieldnames, roi_center_source
    

    def _validate_csv_coordinate_system(
        self,
        roi_center_source,
        csv_coordinate_system,
        external_to_ras_transform_node,
    ):
        csv_coordinate_system = (
            csv_coordinate_system or DEFAULT_CSV_COORDINATE_SYSTEM
        ).strip()

        if roi_center_source == "CSV coordinates":
            if csv_coordinate_system == "External" and external_to_ras_transform_node is None:
                raise ValueError(
                    "External CSV coordinates require a transform node. "
                    "Please select an External-to-RAS transform."
                )

            if csv_coordinate_system not in ["RAS", "External"]:
                raise ValueError(
                    f"Unknown CSV coordinate system: {csv_coordinate_system}"
                )

        return csv_coordinate_system
    

    def _prepare_rows_for_analysis(
        self,
        rows,
        fieldnames,
        points_node,
        roi_center_source,
    ):
        if roi_center_source == "Markups points":
            point_metadata = build_point_metadata(points_node)

            rows = match_rows_to_points_by_point_id(
                rows,
                fieldnames,
                point_metadata,
            )

            rows = sort_rows_by_distance(rows)
            number_of_points = points_node.GetNumberOfControlPoints()

        else:
            for row_index, row in enumerate(rows):
                row["_SlicerPointIndex"] = row_index
                row["_OriginalCsvRowIndex"] = row_index

            number_of_points = len(rows)

        for row_index, row in enumerate(rows):
            row["_TrajectoryIndex"] = row_index

        if len(rows) != number_of_points:
            raise ValueError(
                f"CSV row count ({len(rows)}) does not match number of Markups points ({number_of_points})."
            )

        return rows, number_of_points
    

    def _get_valid_volume_nodes(self):
        all_volume_nodes = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")

        if isinstance(all_volume_nodes, dict):
            all_volume_nodes = list(all_volume_nodes.values())

        volume_nodes = []

        for volume_node in all_volume_nodes:
            volume_name = volume_node.GetName() or ""

            if is_excluded_volume_name(volume_name):
                continue

            if not is_preferred_modality(volume_name):
                continue

            volume_array = slicer.util.arrayFromVolume(volume_node)

            if volume_array.ndim == 3:
                volume_nodes.append(volume_node)
            else:
                print(
                    f"[WARN] Skipping volume '{volume_name}' "
                    f"because it is not a 3D scalar volume. Shape: {volume_array.shape}"
                )

        if not volume_nodes:
            raise ValueError(
                "No valid 3D MRI volume found. Expected one of: "
                + ", ".join(PREFERRED_MODALITIES)
            )

        return volume_nodes
    

    def _clear_previous_outputs(self):
        remove_nodes_in_folder(ROI_FOLDER_NAME)
        cleanup_old_plot_nodes()


    def _create_roi_sphere_models(
        self,
        rows,
        roi_center_positions_ras,
        roi_radius_mm,
        roi_center_offset_mm,
        roi_name,
    ):
        for row in rows:
            point_index = int(row["_SlicerPointIndex"])

            center_ras = self.get_roi_center_ras(
                roi_center_positions_ras=roi_center_positions_ras,
                point_index=point_index,
                roi_center_offset_mm=roi_center_offset_mm,
            )

            create_sphere_roi_model(
                center_ras=center_ras,
                radius_mm=roi_radius_mm,
                name=f"{roi_name}_P{point_index + 1}",
                opacity=0.25,
            )


    def _initialize_roi_composition_report(
        self,
        roi_name,
        roi_radius_mm,
        input_csv_path,
        roi_center_source,
        grey_stat,
        plot_mode,
        csv_coordinate_system,
        roi_center_offset_mm,
        points_node,
        normalization_segmentation_node,
    ):
        roi_composition_lines = []
        roi_composition_lines.append("=" * 80)
        roi_composition_lines.append(f"{roi_name} ROI composition report")
        roi_composition_lines.append(f"ROI radius: {roi_radius_mm:.2f} mm")
        roi_composition_lines.append(f"ROI diameter: {2.0 * roi_radius_mm:.2f} mm")
        roi_composition_lines.append(f"Input CSV: {input_csv_path}")
        roi_composition_lines.append(f"ROI center source: {roi_center_source}")
        roi_composition_lines.append(f"Grey statistic: {grey_stat}")
        roi_composition_lines.append(f"Plot mode: {plot_mode}")
        roi_composition_lines.append(f"CSV coordinate system: {csv_coordinate_system}")
        roi_composition_lines.append(
            f"ROI center offset: {roi_center_offset_mm:.2f} mm"
        )
        roi_composition_lines.append(
            "Voxel inclusion rule: voxel center inside spherical ROI in RAS space"
        )
        roi_composition_lines.append(
            "Variance/SD definition: NumPy var/std with ddof=0"
        )
        roi_composition_lines.append(
            f"Slicer version: {slicer.app.applicationVersion}"
        )

        if points_node is not None:
            roi_composition_lines.append(f"Points node: {points_node.GetName()}")
        else:
            roi_composition_lines.append("Points node: None")

        if normalization_segmentation_node is not None:
            roi_composition_lines.append(
                f"Segmentation node: {normalization_segmentation_node.GetName()}"
            )

        roi_composition_lines.append("=" * 80)

        return roi_composition_lines   


    def _write_output_csv(
        self,
        input_csv_path,
        roi_name,
        roi_center_offset_mm,
        rows,
        fieldnames,
        new_columns,
        create_output_csv,
    ):
        output_fieldnames = ensure_columns(fieldnames, new_columns)

        if create_output_csv:
            base, ext = os.path.splitext(input_csv_path)
            offset_name = make_offset_name(roi_center_offset_mm)
            output_csv_path = f"{base}_{roi_name}_{offset_name}_results.csv"
        else:
            temporary_csv = tempfile.NamedTemporaryFile(
                suffix=".csv",
                delete=False,
            )
            output_csv_path = temporary_csv.name
            temporary_csv.close()

        rows_for_output = sort_rows_by_distance(list(rows))
        write_csv_rows(output_csv_path, rows_for_output, output_fieldnames)

        return output_csv_path  


    def _show_plot(
        self,
        output_csv_path,
        plot_mode,
        grey_stat,
        show_signal1,
        show_signal2,
        roi_name,
    ):
        plot_mode = (plot_mode or DEFAULT_PLOT_MODE).strip()

        if plot_mode == "Two Y axes (raw)":
            if show_signal1 == show_signal2:
                raise ValueError(
                    "Two Y axes (raw) requires exactly one left-axis signal. "
                    "Please select either Show Signal1 or Show Signal2, but not both."
                )

            show_plot_two_y_axes(
                output_csv_path,
                grey_stat=grey_stat,
                show_signal1=show_signal1,
                show_signal2=show_signal2,
                parent=slicer.util.mainWindow(),
                roi_name=roi_name,
            )

        elif plot_mode == "Scaled (Min-Max)":
            show_single_plot_minmax(
                output_csv_path,
                grey_stat=grey_stat,
                show_signal1=show_signal1,
                show_signal2=show_signal2,
                roi_name=roi_name,
            )

        elif plot_mode == "Z-score with SD":
            show_plot_zscore_native(
                output_csv_path,
                grey_stat=grey_stat,
                show_signal1=show_signal1,
                show_signal2=show_signal2,
                roi_name=roi_name,
            )

        else:
            raise ValueError(f"Unknown plot mode: {plot_mode}")           
        

    def run(
        self,
        points_node,
        input_csv_path,
        grey_stat=DEFAULT_GREY_STAT,
        plot_mode=DEFAULT_PLOT_MODE,
        roi_radius_mm=ROI_RADIUS_MM,
        roi_center_source=DEFAULT_ROI_CENTER_SOURCE,
        roi_center_offset_mm=DEFAULT_ROI_CENTER_OFFSET_MM,
        create_roi_composition_report=True,
        create_output_csv=True,
        create_voxel_cube_debug_models=False,
        csv_coordinate_system=DEFAULT_CSV_COORDINATE_SYSTEM,
        show_signal1=False,
        show_signal2=False,
        normalization_segmentation_node=None,
        normalization_segment_id="",
        external_to_ras_transform_node=None,
    ):
        self.validateInputs(points_node, input_csv_path, roi_center_source)


        if create_roi_composition_report:
            if normalization_segmentation_node is None:
                raise ValueError(
                    "ROI composition report requires a segmentation.\n\n"
                    "Please select a segmentation in the interface before enabling "
                    "'Create ROI composition report'."
                )

            segmentation = normalization_segmentation_node.GetSegmentation()

            if segmentation is None or segmentation.GetNumberOfSegments() == 0:
                raise ValueError(
                    "ROI composition report requires a valid segmentation.\n\n"
                    "The selected segmentation does not contain any segments."
                )

        roi_radius_mm, roi_center_offset_mm, roi_name = self._validate_roi_parameters(
            roi_radius_mm,
            roi_center_offset_mm,
        )

        rows, fieldnames, roi_center_source = self._load_and_validate_csv(
            input_csv_path,
            roi_center_source,
        )

        csv_coordinate_system = self._validate_csv_coordinate_system(
            roi_center_source,
            csv_coordinate_system,
            external_to_ras_transform_node,
        )

        rows, number_of_points = self._prepare_rows_for_analysis(
            rows,
            fieldnames,
            points_node,
            roi_center_source,
        )

        volume_nodes = self._get_valid_volume_nodes()
        
        roi_center_positions_ras = self.build_roi_center_positions_ras_from_rows(
            rows=rows,
            roi_center_source=roi_center_source,
            points_node=points_node,
            csv_coordinate_system=csv_coordinate_system,
            external_to_ras_transform_node=external_to_ras_transform_node,
        )


        self._clear_previous_outputs()


        self._create_roi_sphere_models(
            rows,
            roi_center_positions_ras,
            roi_radius_mm,
            roi_center_offset_mm,
            roi_name,
        )

        new_columns = []
        cube_models_created = False
        voxel_segmentation_created = False

        roi_composition_lines = self._initialize_roi_composition_report(
            roi_name=roi_name,
            roi_radius_mm=roi_radius_mm,
            input_csv_path=input_csv_path,
            roi_center_source=roi_center_source,
            grey_stat=grey_stat,
            plot_mode=plot_mode,
            csv_coordinate_system=csv_coordinate_system,
            roi_center_offset_mm=roi_center_offset_mm,
            points_node=points_node,
            normalization_segmentation_node=normalization_segmentation_node,
        )

        for volume_node in volume_nodes:
            volume_name = volume_node.GetName()
            prefix = get_roi_prefix(volume_name, roi_name)
            indices_by_point = [None] * number_of_points

            is_reference_volume = get_modality_key(volume_name) == "T1w_Gd"

            volume_columns = [
                f"{prefix}Mean",
                f"{prefix}Median",
                f"{prefix}Q1",
                f"{prefix}Q3",
                f"{prefix}IQR",
                f"{prefix}Var",
                f"{prefix}SD",
                f"{prefix}Count",
            ]

            if normalization_segmentation_node is not None and normalization_segment_id:
                volume_columns.append(f"{prefix}Mean_NormBySelectedSegmentMean")

            if is_reference_volume:
                volume_columns.extend([
                    f"{prefix}Segmentation_TissueClass",
                    f"{prefix}Segmentation_OverlapFraction",
                ])

            new_columns.extend(volume_columns)

            norm_ref_mean = None

            if normalization_segmentation_node is not None and normalization_segment_id:
                from Lib.segmentation import compute_selected_segment_reference_statistics
                from Lib.statistics import compute_roi_statistics

                ref_stats = compute_selected_segment_reference_statistics(
                    normalization_segmentation_node,
                    normalization_segment_id,
                    volume_node,
                    compute_roi_statistics,
                )

                norm_ref_mean = ref_stats["mean"]

            segmentation_masks = None

            if is_reference_volume and normalization_segmentation_node is not None:
                segmentation_masks = build_segment_masks_for_reference(
                    normalization_segmentation_node,
                    volume_node,
                )

            for row in rows:
                point_index = int(row["_SlicerPointIndex"])

                center_ras = self.get_roi_center_ras(
                    roi_center_positions_ras=roi_center_positions_ras,
                    point_index=point_index,
                    roi_center_offset_mm=roi_center_offset_mm,
                )

                indices, stats = compute_sphere_roi_statistics(
                    volume_node,
                    center_ras,
                    radius_mm=roi_radius_mm,
                )

                if indices is None or len(indices) == 0:
                    raise ValueError(
                        f"No voxel center lies inside the ROI for PointID {row.get('PointID')} "
                        f"({roi_name}, radius {roi_radius_mm} mm). "
                        "Increase the ROI radius or check the ROI center coordinates."
                    )

                if create_voxel_cube_debug_models and not cube_models_created:
                    create_roi_voxel_cube_model(
                        indices=indices,
                        reference_volume_node=volume_node,
                        name=f"{roi_name}_VoxelCubes_P{point_index + 1}",
                    )

                indices_by_point[point_index] = indices

                write_statistics_to_row(row, prefix, stats, norm_ref_mean=norm_ref_mean)

                roi_mask = roi_indices_to_mask(
                    indices,
                    volume_node,
                )

                if is_reference_volume:
                    point_label = f"P{point_index + 1}"
                    roi_voxel_count = int(stats["count"])

                    roi_composition_lines.append("")
                    roi_composition_lines.append("-" * 80)
                    roi_composition_lines.append(
                        f"{point_label} | PointID {point_index} | ROI voxels: {roi_voxel_count}"
                    )
                    roi_composition_lines.append(f"Volume: {volume_name}")

                    def append_segmentation_composition(label, segment_masks):
                        roi_composition_lines.append("")
                        roi_composition_lines.append(f"{label}:")

                        if not segment_masks:
                            roi_composition_lines.append("  No segmentation selected or no segments exported.")
                            return

                        total_overlap = 0

                        for segment_id, info in segment_masks.items():
                            result = compute_overlap_counts(roi_mask, info["mask"])

                            overlap_count = result["overlap_count"]
                            fraction = result["overlap_fraction_of_roi"]

                            if roi_voxel_count > 0:
                                percent = 100.0 * fraction
                            else:
                                percent = float("nan")

                            total_overlap += overlap_count

                            roi_composition_lines.append(
                                f"  {info['name']}: "
                                f"{overlap_count}/{roi_voxel_count} voxels "
                                f"= {percent:.2f}%"
                            )

                        if roi_voxel_count > 0:
                            unclassified_count = roi_voxel_count - total_overlap
                            unclassified_percent = 100.0 * unclassified_count / roi_voxel_count
                            roi_composition_lines.append(
                                f"  Unclassified / no segment overlap: "
                                f"{unclassified_count}/{roi_voxel_count} voxels "
                                f"= {unclassified_percent:.2f}%"
                            )
                    append_segmentation_composition(
                        "Selected segmentation",
                        segmentation_masks,
                    )

                    if segmentation_masks is not None:
                        classification = classify_roi_by_segment_overlap(
                            roi_mask,
                            segmentation_masks,
                        )

                        row[f"{prefix}Segmentation_TissueClass"] = classification["segment_name"]
                        row[f"{prefix}Segmentation_OverlapFraction"] = classification["overlap_fraction_of_roi"]
                    else:
                        row[f"{prefix}Segmentation_TissueClass"] = ""
                        row[f"{prefix}Segmentation_OverlapFraction"] = ""                            
        
            if not voxel_segmentation_created:
                create_roi_voxel_segmentation(
                    indices_by_point=indices_by_point,
                    reference_volume_node=volume_node,
                    name=f"{roi_name}_selected_voxels_ALL",
                    roi_name=roi_name,
                )

            cube_models_created = True
            voxel_segmentation_created = True
        
        output_csv_path = self._write_output_csv(
            input_csv_path=input_csv_path,
            roi_name=roi_name,
            roi_center_offset_mm=roi_center_offset_mm,
            rows=rows,
            fieldnames=fieldnames,
            new_columns=new_columns,
            create_output_csv=create_output_csv,
        )

        if create_roi_composition_report and normalization_segmentation_node is not None:
            base, ext = os.path.splitext(input_csv_path)

            segmentation_name = cleanup_string_for_csv(
                normalization_segmentation_node.GetName()
            )

            offset_name = make_offset_name(roi_center_offset_mm)

            output_txt_path = (
                f"{base}_{roi_name}_{offset_name}_{segmentation_name}_roi_composition_report.txt"
            )

            self.write_roi_composition_report(
                output_txt_path,
                roi_composition_lines,
            )

        try:
            self._show_plot(
                output_csv_path=output_csv_path,
                plot_mode=plot_mode,
                grey_stat=grey_stat,
                show_signal1=show_signal1,
                show_signal2=show_signal2,
                roi_name=roi_name,
            )

        finally:
            if not create_output_csv and output_csv_path and os.path.exists(output_csv_path):
                try:
                    os.remove(output_csv_path)
                except Exception as exc:
                    print(f"[WARN] Could not remove temporary CSV '{output_csv_path}': {exc}")

        if not create_output_csv:
            return ""

        return output_csv_path   


#
# TrajectoryROIAnalysisTest
#

class TrajectoryROIAnalysisTest(ScriptedLoadableModuleTest):

    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.delayDisplay("Trajectory ROI Analysis basic test passed.")
