# Trajectory ROI Analysis User Guide

This document describes the inputs, outputs, file formats, naming conventions, plotting options, and limitations of the Trajectory ROI Analysis extension for 3D Slicer.

The guide is intended for users who want to prepare compatible input data, perform trajectory-based ROI analysis, and interpret the generated results.

For installation instructions and general project information, see:

```text
README.md
```

# Input Requirements and Naming Conventions

Trajectory ROI Analysis relies on predefined CSV column names and MRI volume naming conventions.

The following identifiers are currently hardcoded:

## Required CSV Columns

```text
PointID
DistanceToTarget_mm
```
DistanceToTarget_mm must contain numeric values.

## CSV Coordinate Columns

```text
Center_X
Center_Y
Center_Z
```

## Optional Signal Columns

```text
Signal1_mean
Signal1_SD

Signal2_mean
Signal2_SD
```

## Recognized MRI Modalities

```text
T1w_Gd
T1w_trans
T2w_Flair_trans
T2w_trans
postOp_trans
```

Changing these names requires modification of the source code.


# Inputs

## Required Inputs

| Input             | Description                                |
| ----------------- | ------------------------------------------ |
| Input CSV         | CSV file containing trajectory information |
| ROI Radius        | Radius of spherical ROI in millimeters     |
| MRI Volumes       | Registered scalar MRI volumes              |
| ROI Center Source | Markups points or CSV coordinates          |

---

## ROI Radius

The ROI radius defines the size of the spherical region of interest around each ROI center.

All voxel centers located inside the sphere are included in the analysis.

Units:

```text
millimeters (mm)
```

Default value:

```text
2.0 mm
```

Larger radii include more voxels and sample a larger tissue volume.

Smaller radii provide more localized measurements but may contain only a small number of voxels.

---

## ROI Center Offset

The ROI center can optionally be shifted along the local trajectory direction before ROI generation.

Units:

```text
millimeters (mm)
```

Default value:

```text
0.0 mm
```

Offset direction:

* positive values move the ROI center in trajectory direction
* negative values move the ROI center opposite to the trajectory direction
* 0 mm uses the original point location

The offset is applied before voxel selection and ROI statistics are computed.

---

## Markups Mode

Requires:

```text
vtkMRMLMarkupsFiducialNode
```

Point mapping:

```text
P1 → PointID 0
P2 → PointID 1
P3 → PointID 2
...
```
Additional requirements:

* PointID values must be unique.
* PointID values must contain no gaps.
* The CSV must contain exactly one row for every trajectory point.
* Missing PointID values are not allowed.
* Additional PointID values are not allowed.

---

## CSV Coordinate Mode

Required columns:

```text
Center_X
Center_Y
Center_Z
```

Coordinate systems:

* RAS
* External (requires transform)

Coordinate values must be finite numeric values.

The following are rejected:

* empty cells
* text values
* NaN values
* non-numeric values

---

## Optional Inputs

| Input                 | Purpose                                 |
| --------------------- | ----------------------------------------|
| Segmentation          | ROI classification                      |
| Normalization Segment | Intensity normalization                 |
| Signal1 columns       | Optional signal plotting and comparison |
| Signal2 columns       | Optional signal plotting and comparison |

---

# Outputs

## Result CSV

The output CSV is written into the same directory as the selected input CSV.

Output filename:

```text
<input>_<ROIName>_<OffsetName>_results.csv
```

Example:

```text
trajectory_points_SphereR2_Offset0_results.csv
```

Computed statistics:

* Mean
* Median
* Q1
* Q3
* IQR
* Variance
* Standard deviation
* Voxel count

Optional:

```text
Mean_NormBySelectedSegmentMean
```

---

## ROI Composition Report

Optional report:

```text
<input>_<ROIName>_<OffsetName>_<SegmentationName>_roi_composition_report.txt
```

Contains:

* ROI settings
* segmentation overlap
* tissue composition
* voxel counts

---

## Scene Outputs

The module creates:

* ROI sphere models
* ROI voxel segmentation
* optional voxel cube debug models
* plots

All generated nodes are stored inside:

```text
Sphere ROIs
```

---

# CSV Format

## Minimal CSV

### Markups Mode

```csv
PointID,DistanceToTarget_mm
0,12.4
1,10.2
2,8.0
```

### CSV Coordinate Mode

```csv
PointID,DistanceToTarget_mm,Center_X,Center_Y,Center_Z
0,12.4,10.0,20.0,30.0
1,10.2,10.5,20.1,29.8
2,8.0,11.0,20.2,29.6
```

---

## Required Columns

| Column              | Required            |
| ------------------- | ------------------- |
| PointID             | Yes                 |
| DistanceToTarget_mm | Yes                 |
| Center_X            | CSV coordinate mode |
| Center_Y            | CSV coordinate mode |
| Center_Z            | CSV coordinate mode |

---

## Optional Signal Columns

```text
Signal1_mean
Signal1_SD

Signal2_mean
Signal2_SD
```

---

# MRI Volume Naming

Recognized modalities:

| Modality        |
| --------------- |
| T1w_Gd          |
| T1w_trans       |
| T2w_Flair_trans |
| T2w_trans       |
| postOp_trans    |

The modality identifier may appear anywhere in the volume name.

Examples:

```text
sub-p001_T1w_Gd
Patient05_T2w_trans
Study_postOp_trans
```

Volumes that do not contain one of the recognized modality identifiers are not treated as recognized MRI modalities for modality-specific plotting and color assignment.

Volumes containing the following substrings are ignored:

```text
slicerpoints
insidelm
labelmap
mask
segmentation
selected_voxels
voxelcubes
tmp_
```
These names are automatically excluded because they typically represent temporary, derived, segmentation, or debugging volumes rather than source MRI data.

All MRI volumes must be spatially registered.

---

# Segmentation and Normalization

## Tissue Classification

Each ROI is classified according to the segment with the highest voxel overlap.

Segmentation overlap calculations are performed in the geometry of the T1w_Gd volume.

ROIs without overlap are reported as:

```text
Unclassified
```

---

## Intensity Normalization

ROI means can optionally be normalized by the mean intensity of a selected segmentation segment:

```text
ROI Mean / Selected Segment Mean
```

---

# Plot Modes

## Scaled (Min-Max)

* scales curves to 0–1
* supports MRI and signal comparison
* supports SD visualization

Requirements for Signal1:

```text
Signal1_mean
Signal1_SD
```

Requirements for Signal2:

```text
Signal2_mean
Signal2_SD
```

MRI SD columns are also required for SD visualization.

---

## Two Y Axes (Raw)

* one signal on left axis
* MRI values on right axis
* native units preserved

Requirements:

* corresponding mean and SD columns available
* Matplotlib installed

Valid:

* Signal1 only
* Signal2 only

Invalid:

* Signal1 and Signal2 simultaneously
* no signal selected

---

## Z-Score with SD

* z-score normalization
* SD visualization
* comparison of relative changes

The same SD column requirements as for the Min-Max plot apply.

---

# Limitations

* All MRI volumes must be spatially registered.
* ROI membership is determined using voxel centers.
* A voxel is included only if its center lies inside the spherical ROI.
* Small ROIs combined with large voxel sizes may contain no voxels.
* Volume detection depends on MRI naming conventions.
* MRI modality recognition depends on predefined modality identifiers.
* CSV parsing depends on predefined column names.
* Tissue classification depends on segmentation overlap.
* ROIs without segmentation overlap are labeled as `Unclassified`.
* T1w_Gd is used as segmentation reference volume.
* Debug voxel models can become slow for large ROIs.
* Intended for research use only.
* Not a medical device.


---