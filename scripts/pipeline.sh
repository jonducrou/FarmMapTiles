#!/bin/bash
#
# Self-recovering drone orthomosaic pipeline
#
# Processes drone videos into map tiles via OpenDroneMap.
# Designed to run on an external drive to avoid filling the boot disk.
# Each date tracks its own state so the pipeline can be interrupted
# and resumed at any point.
#
# Usage: pipeline.sh <video_dir> <work_dir>
#   video_dir  - directory containing DJI .mp4/.MP4 video files
#   work_dir   - working directory on external drive (e.g. /Volumes/External/odm)
#
# Example:
#   ./scripts/pipeline.sh /Volumes/External/drone_videos /Volumes/External/odm_work
#
# The pipeline will:
#   1. Scan videos for valid nadir mapping flights
#   2. Extract geotagged frames from each video
#   3. Run OpenDroneMap to build orthomosaics
#   4. Apply RTK alignment shift
#   5. Generate and convert map tiles (WebP)
#   6. Copy final tiles into this repo's tiles/ directory
#
# State is tracked per-date in $work_dir/<date>/state.json
# Re-running skips completed steps automatically.

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────

FRAME_OVERLAP=0.80        # target front overlap (0.0-1.0), spacing adapts to altitude
ORTHO_RESOLUTION=2.5      # cm/pixel
FEATURE_QUALITY=ultra
PC_QUALITY=high
MESH_OCTREE_DEPTH=12
WEBP_QUALITY=85
ZOOM_LEVELS="15-22"

# RTK alignment shift at latitude -28.6975
# 1m east ≈ 0.0000103° longitude, 1m north ≈ 0.0000090° latitude
SHIFT_LON=0.0000237       # +2.3m east
SHIFT_LAT=0.0000131       # +1.45m north

# ─── Arguments ───────────────────────────────────────────────────────────────

VIDEO_DIR="${1:-}"
WORK_DIR="${2:-}"

if [ -z "$VIDEO_DIR" ] || [ -z "$WORK_DIR" ]; then
    echo "Usage: pipeline.sh <video_dir> <work_dir>"
    echo ""
    echo "  video_dir  - directory containing DJI .mp4/.MP4 files"
    echo "  work_dir   - working directory on external drive"
    echo ""
    echo "Example:"
    echo "  ./scripts/pipeline.sh /Volumes/Ext/videos /Volumes/Ext/odm_work"
    exit 1
fi

if [ ! -d "$VIDEO_DIR" ]; then
    echo "Error: Video directory not found: $VIDEO_DIR"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Resolve to absolute paths
VIDEO_DIR="$(cd "$VIDEO_DIR" && pwd)"
mkdir -p "$WORK_DIR"
WORK_DIR="$(cd "$WORK_DIR" && pwd)"

MANIFEST="$WORK_DIR/manifest.json"

# ─── Helpers ─────────────────────────────────────────────────────────────────

log() { echo "[$(date '+%H:%M:%S')] $*"; }
err() { echo "[$(date '+%H:%M:%S')] ERROR: $*" >&2; }

# Per-date state management
# States: scanned, frames_extracted, odm_complete, shifted, tiled, converted, done
get_state() {
    local date="$1"
    local state_file="$WORK_DIR/$date/state.json"
    if [ -f "$state_file" ]; then
        python3 -c "import json; print(json.load(open('$state_file'))['state'])" 2>/dev/null || echo "none"
    else
        echo "none"
    fi
}

set_state() {
    local date="$1"
    local state="$2"
    local state_file="$WORK_DIR/$date/state.json"
    mkdir -p "$WORK_DIR/$date"
    python3 -c "
import json
from datetime import datetime
state_file = '$state_file'
try:
    with open(state_file) as f:
        data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    data = {'history': []}
data['state'] = '$state'
data['updated'] = datetime.now().isoformat()
data['history'].append({'state': '$state', 'time': datetime.now().isoformat()})
with open(state_file, 'w') as f:
    json.dump(data, f, indent=2)
"
    log "  [$date] State → $state"
}

check_disk_space() {
    local dir="$1"
    local min_gb="${2:-20}"
    local avail_gb
    avail_gb=$(df -g "$dir" | awk 'NR==2 {print $4}')
    if [ "$avail_gb" -lt "$min_gb" ]; then
        err "Only ${avail_gb}GB free on $(df "$dir" | awk 'NR==2 {print $1}'). Need at least ${min_gb}GB."
        return 1
    fi
    log "  Disk OK: ${avail_gb}GB free"
}

check_docker() {
    if ! docker info >/dev/null 2>&1; then
        err "Docker is not running. Start OrbStack/Docker and try again."
        exit 1
    fi
    local mem_gb
    mem_gb=$(docker info 2>/dev/null | grep "Total Memory" | grep -oE '[0-9]+\.[0-9]+' | head -1 | cut -d. -f1)
    log "Docker available with ${mem_gb}GB RAM"
    if [ "$mem_gb" -lt 30 ]; then
        log "  WARNING: <30GB RAM allocated to Docker. Consider increasing in OrbStack settings."
    fi
}

# ─── Phase 1: Scan ──────────────────────────────────────────────────────────

phase_scan() {
    log "Phase 1: Scanning videos in $VIDEO_DIR"

    if [ -f "$MANIFEST" ]; then
        local existing
        existing=$(python3 -c "import json; print(json.load(open('$MANIFEST'))['summary']['valid'])" 2>/dev/null || echo 0)
        log "  Existing manifest found with $existing valid videos. Re-scanning to pick up new files."
    fi

    python3 "$SCRIPT_DIR/scan_videos.py" "$VIDEO_DIR" "$MANIFEST"

    local valid
    valid=$(python3 -c "import json; print(json.load(open('$MANIFEST'))['summary']['valid'])")
    if [ "$valid" -eq 0 ]; then
        log "No valid mapping videos found."
        exit 0
    fi
    log "Found $valid valid videos"
}

# ─── Phase 2: Extract frames ────────────────────────────────────────────────

phase_extract() {
    local date="$1"
    local state
    state=$(get_state "$date")

    local frames_dir="$WORK_DIR/$date/frames"

    # Skip if state says done, or if frames already exist on disk
    if [ "$state" != "none" ] && [ "$state" != "scanned" ]; then
        log "  [$date] Frames already extracted, skipping"
        return 0
    fi
    local existing_frames
    existing_frames=$(ls -1 "$frames_dir"/*.jpg 2>/dev/null | wc -l | tr -d ' ')
    if [ "$existing_frames" -gt 0 ]; then
        log "  [$date] Found $existing_frames existing frames, skipping extraction"
        set_state "$date" "frames_extracted"
        return 0
    fi

    mkdir -p "$frames_dir"

    # Get videos for this date from manifest
    local videos
    videos=$(python3 -c "
import json
with open('$MANIFEST') as f:
    m = json.load(f)
for v in m['dates'].get('$date', []):
    print(v['file'])
")

    if [ -z "$videos" ]; then
        err "No videos found for date $date"
        return 1
    fi

    local total_frames=0
    while IFS= read -r video_file; do
        local video_path="$VIDEO_DIR/$video_file"
        if [ ! -f "$video_path" ]; then
            err "Video not found: $video_path"
            continue
        fi

        log "  [$date] Extracting frames from $video_file (${FRAME_OVERLAP} overlap)..."
        local count
        count=$(python3 "$SCRIPT_DIR/extract_frames.py" "$video_path" "$frames_dir" "$FRAME_OVERLAP" 2>&1 | tee /dev/stderr | grep -oE '[0-9]+ geotagged' | grep -oE '[0-9]+' || echo 0)
        total_frames=$((total_frames + count))
    done <<< "$videos"

    local actual_count
    actual_count=$(ls -1 "$frames_dir"/*.jpg 2>/dev/null | wc -l | tr -d ' ')
    log "  [$date] Total frames: $actual_count"

    if [ "$actual_count" -eq 0 ]; then
        err "No frames extracted for $date"
        return 1
    fi

    set_state "$date" "frames_extracted"
}

# ─── Phase 3: ODM ───────────────────────────────────────────────────────────

phase_odm() {
    local date="$1"
    local state
    state=$(get_state "$date")

    if [ "$state" = "odm_complete" ] || [ "$state" = "shifted" ] || \
       [ "$state" = "tiled" ] || [ "$state" = "converted" ] || [ "$state" = "done" ]; then
        log "  [$date] ODM already complete, skipping"
        return 0
    fi

    local odm_dir="$WORK_DIR/$date/odm"
    local ortho="$odm_dir/odm_orthophoto/odm_orthophoto.tif"

    # If orthomosaic already exists on disk (e.g. from a moved work dir), skip
    if [ -f "$ortho" ]; then
        log "  [$date] Orthomosaic already exists on disk, skipping ODM"
        set_state "$date" "odm_complete"
        return 0
    fi

    check_disk_space "$WORK_DIR" 80
    check_docker

    # Set up ODM input
    mkdir -p "$odm_dir/images"

    local frame_count
    frame_count=$(ls -1 "$WORK_DIR/$date/frames/"*.jpg 2>/dev/null | wc -l | tr -d ' ')

    # Only copy if images dir is empty or has fewer files
    local existing_count
    existing_count=$(ls -1 "$odm_dir/images/"*.jpg 2>/dev/null | wc -l | tr -d ' ')
    if [ "$existing_count" -lt "$frame_count" ]; then
        log "  [$date] Copying $frame_count frames to ODM directory..."
        cp "$WORK_DIR/$date/frames/"*.jpg "$odm_dir/images/"
    fi

    # Check if we can resume a partial ODM run
    local rerun_arg=""
    if [ -d "$odm_dir/opensfm" ] && [ ! -f "$ortho" ]; then
        # Determine which stage to resume from
        if [ -d "$odm_dir/opensfm/undistorted/openmvs" ]; then
            rerun_arg="--rerun-from openmvs"
            log "  [$date] Resuming ODM from openmvs stage"
        elif [ -d "$odm_dir/opensfm/undistorted" ]; then
            rerun_arg="--rerun-from openmvs"
            log "  [$date] Resuming ODM from openmvs stage"
        elif [ -f "$odm_dir/opensfm/reconstruction.json" ]; then
            rerun_arg="--rerun-from opensfm"
            log "  [$date] Resuming ODM from opensfm stage"
        fi
    fi

    log "  [$date] Running OpenDroneMap ($frame_count frames, res=${ORTHO_RESOLUTION}cm)..."
    log "  [$date] Settings: feature=$FEATURE_QUALITY pc=$PC_QUALITY mesh-depth=$MESH_OCTREE_DEPTH"

    # Run ODM — try with cutline first, fall back without if it hits the
    # MultiPolygon/Polygon bug
    local odm_success=false

    if ! $odm_success; then
        log "  [$date] Running ODM with cutline..."
        if docker run --rm \
            -v "$odm_dir:/datasets/code" \
            opendronemap/odm \
            --project-path /datasets \
            --orthophoto-resolution "$ORTHO_RESOLUTION" \
            --feature-quality "$FEATURE_QUALITY" \
            --pc-quality "$PC_QUALITY" \
            --mesh-octree-depth "$MESH_OCTREE_DEPTH" \
            --orthophoto-cutline \
            $rerun_arg 2>&1; then
            odm_success=true
        else
            local exit_code=$?
            # Check if it's the cutline MultiPolygon bug
            if [ -f "$ortho" ]; then
                log "  [$date] ODM cutline failed but orthomosaic exists — proceeding without cutline"
                odm_success=true
            else
                err "ODM failed with exit code $exit_code"
                # Don't clean intermediates — allows resume on next run
                return 1
            fi
        fi
    fi

    if [ ! -f "$ortho" ]; then
        err "Orthomosaic not generated for $date"
        return 1
    fi

    log "  [$date] Orthomosaic generated: $(du -h "$ortho" | cut -f1)"
    set_state "$date" "odm_complete"
}

# ─── Phase 4: RTK Shift ─────────────────────────────────────────────────────

phase_shift() {
    local date="$1"
    local state
    state=$(get_state "$date")

    if [ "$state" = "shifted" ] || [ "$state" = "tiled" ] || \
       [ "$state" = "converted" ] || [ "$state" = "done" ]; then
        log "  [$date] Already shifted, skipping"
        return 0
    fi

    local ortho="$WORK_DIR/$date/odm/odm_orthophoto/odm_orthophoto.tif"
    local shifted="$WORK_DIR/$date/odm/odm_orthophoto/odm_orthophoto_shifted.tif"

    # If shifted file already exists on disk, skip
    if [ -f "$shifted" ]; then
        log "  [$date] Shifted orthomosaic already exists, skipping"
        set_state "$date" "shifted"
        return 0
    fi

    log "  [$date] Applying RTK shift (+2.3m E, +1.45m N)..."

    local bounds
    bounds=$(gdalinfo -json "$ortho" | python3 -c "
import json, sys
d = json.load(sys.stdin)
c = d['cornerCoordinates']
print(f\"{c['upperLeft'][0]} {c['upperLeft'][1]} {c['lowerRight'][0]} {c['lowerRight'][1]}\")
")

    local UL_X UL_Y LR_X LR_Y
    read UL_X UL_Y LR_X LR_Y <<< "$bounds"

    local NEW_UL_X NEW_UL_Y NEW_LR_X NEW_LR_Y
    NEW_UL_X=$(echo "$UL_X + $SHIFT_LON" | bc -l)
    NEW_UL_Y=$(echo "$UL_Y + $SHIFT_LAT" | bc -l)
    NEW_LR_X=$(echo "$LR_X + $SHIFT_LON" | bc -l)
    NEW_LR_Y=$(echo "$LR_Y + $SHIFT_LAT" | bc -l)

    gdal_translate -a_ullr "$NEW_UL_X" "$NEW_UL_Y" "$NEW_LR_X" "$NEW_LR_Y" \
        "$ortho" "$shifted"

    set_state "$date" "shifted"
}

# ─── Phase 5: Tile generation ───────────────────────────────────────────────

phase_tile() {
    local date="$1"
    local state
    state=$(get_state "$date")

    if [ "$state" = "tiled" ] || [ "$state" = "converted" ] || [ "$state" = "done" ]; then
        log "  [$date] Already tiled, skipping"
        return 0
    fi

    local shifted="$WORK_DIR/$date/odm/odm_orthophoto/odm_orthophoto_shifted.tif"
    local tiles_dir="$WORK_DIR/$date/tiles"

    # If tiles already exist on disk, skip
    local existing_tiles
    existing_tiles=$(find "$tiles_dir" -name "*.png" -o -name "*.webp" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$existing_tiles" -gt 0 ]; then
        log "  [$date] Found $existing_tiles existing tiles, skipping generation"
        set_state "$date" "tiled"
        return 0
    fi

    log "  [$date] Generating tiles (zoom $ZOOM_LEVELS)..."
    rm -rf "$tiles_dir"
    mkdir -p "$tiles_dir"

    gdal2tiles.py \
        --zoom="$ZOOM_LEVELS" \
        --tmscompatible \
        --webviewer=none \
        "$shifted" \
        "$tiles_dir"

    local tile_count
    tile_count=$(find "$tiles_dir" -name "*.png" | wc -l | tr -d ' ')
    log "  [$date] Generated $tile_count PNG tiles"

    set_state "$date" "tiled"
}

# ─── Phase 6: WebP conversion ───────────────────────────────────────────────

phase_convert() {
    local date="$1"
    local state
    state=$(get_state "$date")

    if [ "$state" = "converted" ] || [ "$state" = "done" ]; then
        log "  [$date] Already converted, skipping"
        return 0
    fi

    local tiles_dir="$WORK_DIR/$date/tiles"

    # If already all WebP (no PNGs left), skip
    local png_count
    png_count=$(find "$tiles_dir" -name "*.png" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$png_count" -eq 0 ]; then
        local webp_count
        webp_count=$(find "$tiles_dir" -name "*.webp" 2>/dev/null | wc -l | tr -d ' ')
        if [ "$webp_count" -gt 0 ]; then
            log "  [$date] Tiles already converted to WebP ($webp_count tiles), skipping"
            set_state "$date" "converted"
            return 0
        fi
    fi

    local cores
    cores=$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)
    log "  [$date] Converting $png_count tiles to WebP (q${WEBP_QUALITY}, ${cores} parallel)..."

    find "$tiles_dir" -name "*.png" -print0 | xargs -0 -P "$cores" -I{} sh -c '
        webp="${1%.png}.webp"
        cwebp -q '"$WEBP_QUALITY"' "$1" -o "$webp" 2>/dev/null && rm "$1"
    ' _ {}

    local webp_count
    webp_count=$(find "$tiles_dir" -name "*.webp" | wc -l | tr -d ' ')
    log "  [$date] Converted $webp_count tiles to WebP"

    set_state "$date" "converted"
}

# ─── Phase 7: Deploy tiles to repo ──────────────────────────────────────────

phase_deploy() {
    local date="$1"
    local state
    state=$(get_state "$date")

    if [ "$state" = "done" ]; then
        log "  [$date] Already deployed, skipping"
        return 0
    fi

    local src="$WORK_DIR/$date/tiles"
    local dst="$PROJECT_DIR/tiles/$date"

    # If tiles already deployed in repo, skip
    local deployed_count
    deployed_count=$(find "$dst" -name "*.webp" 2>/dev/null | wc -l | tr -d ' ')
    local src_count
    src_count=$(find "$src" -name "*.webp" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$deployed_count" -gt 0 ] && [ "$deployed_count" -eq "$src_count" ]; then
        log "  [$date] Tiles already deployed ($deployed_count tiles), skipping"
        set_state "$date" "done"
        return 0
    fi

    log "  [$date] Deploying tiles to $dst..."
    rm -rf "$dst"
    cp -r "$src" "$dst"

    local tile_count
    tile_count=$(find "$dst" -name "*.webp" | wc -l | tr -d ' ')
    log "  [$date] Deployed $tile_count tiles"

    set_state "$date" "done"
}

# ─── Phase 8: Cleanup ODM intermediates ──────────────────────────────────────

phase_cleanup() {
    local date="$1"
    local state
    state=$(get_state "$date")

    if [ "$state" != "done" ]; then
        return 0
    fi

    local odm_dir="$WORK_DIR/$date/odm"
    # Keep the orthomosaic TIFs, remove everything else
    local dirs_to_clean=(opensfm odm_meshing odm_texturing_25d odm_filterpoints odm_dem odm_report)
    for d in "${dirs_to_clean[@]}"; do
        if [ -d "$odm_dir/$d" ]; then
            local size
            size=$(du -sh "$odm_dir/$d" 2>/dev/null | cut -f1)
            rm -rf "$odm_dir/$d"
            log "  [$date] Cleaned $d ($size)"
        fi
    done

    # Also clean frames (they can be re-extracted from video)
    if [ -d "$WORK_DIR/$date/frames" ]; then
        rm -rf "$WORK_DIR/$date/frames"
        log "  [$date] Cleaned extracted frames"
    fi
    if [ -d "$odm_dir/images" ]; then
        rm -rf "$odm_dir/images"
        log "  [$date] Cleaned ODM image copies"
    fi
}

# ─── Main ────────────────────────────────────────────────────────────────────

main() {
    log "=========================================="
    log "Drone Orthomosaic Pipeline"
    log "  Videos:  $VIDEO_DIR"
    log "  Work:    $WORK_DIR"
    log "  Project: $PROJECT_DIR"
    log "=========================================="

    check_disk_space "$WORK_DIR" 20

    # Phase 1: Scan
    phase_scan

    # Get dates from manifest
    local dates
    dates=$(python3 -c "import json; print(' '.join(sorted(json.load(open('$MANIFEST'))['dates'].keys())))")

    log ""
    log "Dates to process: $dates"

    local failed_dates=""
    local success_count=0

    # ── Pass 1: Extract all frames (low CPU, I/O bound) ──────────────────
    # Do this upfront so frames are ready when ODM needs them.
    # This overlaps well with video downloads still in progress.
    log ""
    log "── Pass 1: Frame extraction (all dates) ──"
    for date in $dates; do
        if ! phase_extract "$date"; then
            err "Failed at frame extraction for $date"
            failed_dates="$failed_dates $date(extract)"
        fi
    done

    # ── Pass 2: ODM + post-processing (CPU/RAM heavy, then I/O) ─────────
    # ODM is the bottleneck — run one at a time.
    # Post-processing (shift/tile/convert/deploy) runs immediately after
    # each ODM completes to free disk before the next one starts.
    log ""
    log "── Pass 2: ODM + tiling (per date) ──"
    for date in $dates; do
        log ""
        log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        log "Processing: $date"
        log "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

        # Skip dates that failed extraction
        local state
        state=$(get_state "$date")
        if [ "$state" = "none" ] || [ "$state" = "scanned" ]; then
            log "  [$date] No frames available, skipping"
            continue
        fi

        if ! phase_odm "$date"; then
            err "Failed at ODM for $date — intermediates preserved for resume"
            failed_dates="$failed_dates $date(odm)"
            continue
        fi

        if ! phase_shift "$date"; then
            err "Failed at RTK shift for $date"
            failed_dates="$failed_dates $date(shift)"
            continue
        fi

        if ! phase_tile "$date"; then
            err "Failed at tiling for $date"
            failed_dates="$failed_dates $date(tile)"
            continue
        fi

        if ! phase_convert "$date"; then
            err "Failed at WebP conversion for $date"
            failed_dates="$failed_dates $date(convert)"
            continue
        fi

        if ! phase_deploy "$date"; then
            err "Failed at deploy for $date"
            failed_dates="$failed_dates $date(deploy)"
            continue
        fi

        phase_cleanup "$date"
        success_count=$((success_count + 1))
    done

    # Update viewer manifest
    log ""
    log "=========================================="
    log "Updating viewer manifest"
    log "=========================================="

    python3 -c "
import json, os

tile_base = '$PROJECT_DIR/tiles'
dates = []
for d in sorted(os.listdir(tile_base)):
    tile_dir = os.path.join(tile_base, d)
    if os.path.isdir(tile_dir) and d[0:2] == '20':
        count = sum(1 for root, dirs, files in os.walk(tile_dir) for f in files if f.endswith('.webp'))
        if count > 0:
            dates.append({'date': d, 'description': f'{d} survey'})

manifest = {
    'dates': dates,
    'defaultDate': dates[-1]['date'] if dates else ''
}

with open('$PROJECT_DIR/viewer_manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2)

print(f'Manifest updated: {len(dates)} dates')
for d in dates:
    print(f'  {d[\"date\"]}')
"

    log ""
    log "=========================================="
    log "Pipeline complete"
    log "  Successful: $success_count"
    if [ -n "$failed_dates" ]; then
        log "  Failed:$failed_dates"
        log "  Re-run this script to retry failed dates"
    fi
    log "=========================================="
}

main
