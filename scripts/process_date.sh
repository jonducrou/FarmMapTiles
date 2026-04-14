#!/bin/bash
#
# Process frames for a single date through ODM and tile generation
#
# Usage: process_date.sh <date> <frames_dir>
# Example: process_date.sh 2023-02-18 frames/2023-02-18
#

set -e

DATE=$1
FRAMES_DIR=$2
TILES_OUTPUT="tiles/$DATE"

if [ -z "$DATE" ] || [ -z "$FRAMES_DIR" ]; then
    echo "Usage: process_date.sh <date> <frames_dir>"
    echo "Example: process_date.sh 2023-02-18 frames/2023-02-18"
    exit 1
fi

if [ ! -d "$FRAMES_DIR" ]; then
    echo "Error: Frames directory not found: $FRAMES_DIR"
    exit 1
fi

FRAME_COUNT=$(ls -1 "$FRAMES_DIR"/*.jpg 2>/dev/null | wc -l)
echo "Processing $DATE with $FRAME_COUNT frames"

# Create working directory
WORK_DIR="odm_work/$DATE"
mkdir -p "$WORK_DIR/images"

# Copy frames to ODM input directory
echo "Copying frames to ODM work directory..."
cp "$FRAMES_DIR"/*.jpg "$WORK_DIR/images/"

# Run OpenDroneMap
echo "Running OpenDroneMap..."
docker run --rm \
    -v "$(pwd)/$WORK_DIR:/datasets/code" \
    opendronemap/odm \
    --project-path /datasets \
    --orthophoto-resolution 2.5 \
    --feature-quality ultra \
    --pc-quality high \
    --mesh-octree-depth 12 \
    --orthophoto-cutline

# Check for output
ORTHO_PATH="$WORK_DIR/odm_orthophoto/odm_orthophoto.tif"
if [ ! -f "$ORTHO_PATH" ]; then
    echo "Error: Orthomosaic not generated"
    exit 1
fi

echo "Orthomosaic generated: $ORTHO_PATH"

# Get bounds and apply RTK shift (+2.3m east, +1.45m north)
# At this latitude, approximately:
# 1m east ≈ 0.0000103° longitude
# 1m north ≈ 0.0000090° latitude
SHIFT_LON=0.0000237  # 2.3m east
SHIFT_LAT=0.0000131  # 1.45m north

echo "Applying RTK alignment shift..."
SHIFTED_PATH="$WORK_DIR/odm_orthophoto/odm_orthophoto_shifted.tif"

# Get current bounds
BOUNDS=$(gdalinfo -json "$ORTHO_PATH" | python3 -c "
import json, sys
d = json.load(sys.stdin)
c = d['cornerCoordinates']
print(f\"{c['upperLeft'][0]} {c['upperLeft'][1]} {c['lowerRight'][0]} {c['lowerRight'][1]}\")
")

read UL_X UL_Y LR_X LR_Y <<< "$BOUNDS"

# Apply shift
NEW_UL_X=$(echo "$UL_X + $SHIFT_LON" | bc -l)
NEW_UL_Y=$(echo "$UL_Y + $SHIFT_LAT" | bc -l)
NEW_LR_X=$(echo "$LR_X + $SHIFT_LON" | bc -l)
NEW_LR_Y=$(echo "$LR_Y + $SHIFT_LAT" | bc -l)

gdal_translate -a_ullr $NEW_UL_X $NEW_UL_Y $NEW_LR_X $NEW_LR_Y \
    "$ORTHO_PATH" "$SHIFTED_PATH"

# Generate tiles
echo "Generating tiles..."
mkdir -p "$TILES_OUTPUT"

gdal2tiles.py \
    --zoom=15-22 \
    --tmscompatible \
    --webviewer=none \
    "$SHIFTED_PATH" \
    "$TILES_OUTPUT"

# Count tiles
TILE_COUNT=$(find "$TILES_OUTPUT" -name "*.png" | wc -l)
echo "Generated $TILE_COUNT tiles in $TILES_OUTPUT"

# Clean up ODM work directory (optional - comment out to keep)
# rm -rf "$WORK_DIR"

echo "Done processing $DATE"
