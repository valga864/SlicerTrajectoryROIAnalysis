cmake_minimum_required(VERSION 3.20.6...3.22.6 FATAL_ERROR)

project(TrajectoryROIAnalysisExtension)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/valga864/SlicerTrajectoryROIAnalysis")
set(EXTENSION_CATEGORY "Quantification")
set(EXTENSION_CONTRIBUTORS "Valentina Gäumann (Department of Biomedical Engineering, Linköping University)")
set(EXTENSION_DESCRIPTION "Trajectory ROI Analysis provides spherical ROI quantification, trajectory-based signal analysis, MRI intensity statistics, and segmentation overlap analysis in 3D Slicer. No related patents are known.")
set(EXTENSION_ICONURL "https://raw.githubusercontent.com/valga864/SlicerTrajectoryROIAnalysis/main/TrajectoryROIAnalysis/Resources/Icons/TrajectoryROIAnalysis.png")
set(EXTENSION_SCREENSHOTURLS "https://raw.githubusercontent.com/valga864/SlicerTrajectoryROIAnalysis/main/ScreenshotUI_TrajectoryROIAnalysis.png")
set(EXTENSION_DEPENDS "NA") # Specified as a list or "NA" if no dependencies

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(TrajectoryROIAnalysis)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
