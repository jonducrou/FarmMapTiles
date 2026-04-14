#!/bin/bash
#
# Master processing script for timelapse map generation
#
# This script orchestrates the full pipeline:
# 1. Scan videos to create manifest
# 2. Extract frames from valid videos
# 3. Process each date through ODM and tiling
#
# Usage: process_all.sh <video_dir>
# Example: process_all.sh /path/to/drone/videos
#

set -e

VIDEO_DIR=$1
MANIFEST="manifest.json"
FRAMES_DIR="frames"
FRAME_INTERVAL=2  # Extract 1 frame every 2 seconds

if [ -z "$VIDEO_DIR" ]; then
    echo "Usage: process_all.sh <video_dir>"
    echo "Example: process_all.sh /path/to/drone/videos"
    exit 1
fi

if [ ! -d "$VIDEO_DIR" ]; then
    echo "Error: Video directory not found: $VIDEO_DIR"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "=========================================="
echo "Phase 1: Scanning videos"
echo "=========================================="
python3 scripts/scan_videos.py "$VIDEO_DIR" "$MANIFEST"

# Check if any valid videos found
VALID_COUNT=$(python3 -c "import json; d=json.load(open('$MANIFEST')); print(d['summary']['valid'])")
if [ "$VALID_COUNT" -eq 0 ]; then
    echo "No valid mapping videos found. Exiting."
    exit 0
fi

echo ""
echo "=========================================="
echo "Phase 2: Extracting frames"
echo "=========================================="
python3 scripts/extract_frames.py --manifest "$MANIFEST" "$FRAMES_DIR" "$FRAME_INTERVAL"

echo ""
echo "=========================================="
echo "Phase 3: Processing dates"
echo "=========================================="

# Get list of dates from manifest
DATES=$(python3 -c "import json; d=json.load(open('$MANIFEST')); print(' '.join(d['dates'].keys()))")

for DATE in $DATES; do
    echo ""
    echo "Processing date: $DATE"

    if [ -d "$FRAMES_DIR/$DATE" ]; then
        bash scripts/process_date.sh "$DATE" "$FRAMES_DIR/$DATE"
    else
        echo "  Warning: No frames directory for $DATE"
    fi
done

echo ""
echo "=========================================="
echo "Phase 4: Updating manifest for viewer"
echo "=========================================="

# Create viewer manifest with available dates
python3 -c "
import json
import os

with open('$MANIFEST') as f:
    manifest = json.load(f)

dates_with_tiles = []
for date in manifest['dates'].keys():
    tile_dir = f'tiles/{date}'
    if os.path.isdir(tile_dir):
        tile_count = sum(1 for _ in os.walk(tile_dir) for f in _[2] if f.endswith('.png'))
        dates_with_tiles.append({
            'date': date,
            'tiles': tile_count,
            'videos': len(manifest['dates'][date])
        })

viewer_manifest = {
    'dates': sorted(dates_with_tiles, key=lambda x: x['date']),
    'generated': '$(date -Iseconds)'
}

with open('viewer_manifest.json', 'w') as f:
    json.dump(viewer_manifest, f, indent=2)

print(f'Viewer manifest: {len(dates_with_tiles)} dates with tiles')
"

echo ""
echo "=========================================="
echo "Complete!"
echo "=========================================="
echo ""
echo "Open index.html in a browser to view the timelapse map"
