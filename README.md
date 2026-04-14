# FarmMapTiles

Drone orthomosaic timelapse served as map tiles on GitHub Pages. Fly a DJI drone over your property, run the pipeline, and get browsable aerial imagery with a date slider.

**Live viewer:** https://jonducrou.github.io/FarmMapTiles/

## Quick Start

### View tiles locally

```bash
python3 -m http.server 8080
open http://localhost:8080
```

### Process new drone videos

```bash
# Copy DJI videos to an external drive, then:
./scripts/pipeline.sh /Volumes/External/drone_videos /Volumes/External/odm_work
```

The pipeline is self-recovering -- re-run the same command after a failure or interruption and it picks up where it left off.

## Requirements

| Tool | Purpose |
|------|---------|
| Docker/OrbStack | Runs OpenDroneMap (allocate >= 32GB RAM) |
| ffmpeg | Frame extraction from video |
| exiftool | GPS EXIF tagging of extracted frames |
| GDAL (`gdal_translate`, `gdal2tiles.py`) | Georeferencing and tile generation |
| cwebp | WebP tile compression |
| Python 3 | Processing scripts |

Install on macOS:

```bash
brew install ffmpeg exiftool gdal webp
# Docker: install OrbStack (https://orbstack.dev) or Docker Desktop
# Allocate >= 32GB RAM in Docker settings
```

## How It Works

1. **Scan** -- finds DJI videos with nadir camera angle and 40-140m altitude
2. **Extract frames** -- pulls geotagged frames at distance-based intervals (adapts spacing to altitude for consistent overlap)
3. **OpenDroneMap** -- stitches frames into a georeferenced orthomosaic
4. **Align** -- applies RTK GPS shift (+2.3m east, +1.45m north)
5. **Tile** -- generates TMS tiles at zoom levels 15-22
6. **Convert** -- compresses tiles to WebP (q85, ~89% size reduction)
7. **Deploy** -- copies tiles into the repo's `tiles/` directory

Each date tracks its own state in `<work_dir>/<date>/state.json`, so you can process multiple dates and resume at any point.

## Disk Space

ODM needs ~80GB free per date being processed. Use an external drive for the work directory to avoid filling your boot disk. Final tiles are small (~200MB total for all dates).

## Available Dates

| Date | Tiles | Altitude | Resolution |
|------|-------|----------|------------|
| 2023-02-18 | 2,076 | 120m | 5cm/px |
| 2023-09-16 | 7,848 | 120m | 5cm/px |
| 2023-11-11 | 7,020 | 120m | 5cm/px |
| 2024-10-26 | 8,202 | 120m | 5cm/px |
| 2025-04-17 | 5,433 | 120m | 5cm/px |
| 2026-04-03 | 1,469 | 50m | 2.5cm/px |

## Using Tiles Elsewhere

### Leaflet

```javascript
L.tileLayer('https://jonducrou.github.io/FarmMapTiles/tiles/2026-04-03/{z}/{x}/{y}.webp', {
    tms: true,
    minZoom: 15,
    maxZoom: 22
});
```

### Home Assistant (ha-map-card)

```yaml
type: custom:map-card
entities:
  - entity: device_tracker.your_device
tile_layer_url: https://jonducrou.github.io/FarmMapTiles/tiles/2026-04-03/{z}/{x}/{y}.webp
tile_layer_options:
  tms: true
  minZoom: 15
  maxZoom: 22
```

## Project Structure

```
index.html              # Leaflet viewer with date slider
viewer_manifest.json    # Dates available in the viewer
tiles/                  # Generated map tiles (committed to repo)
  2023-02-18/           # One folder per survey date
  2026-04-03/           # etc.
scripts/
  pipeline.sh           # Main self-recovering pipeline
  extract_frames.py     # Frame extraction with GPS tagging
  scan_videos.py        # Video scanning and filtering
  process_date.sh       # ODM + tile generation for one date
SPEC.md                 # Technical specification
PLAN.md                 # Project status and tasks
DECISIONS.md            # Approaches tried and outcomes
```

## Configuration

Edit the top of `scripts/pipeline.sh` to tune:

```bash
FRAME_OVERLAP=0.80        # front overlap (0.75-0.85 typical)
ORTHO_RESOLUTION=2.5      # cm/pixel
FEATURE_QUALITY=ultra     # ODM feature matching quality
PC_QUALITY=high           # point cloud density (ultra needs >150GB disk)
MESH_OCTREE_DEPTH=12      # mesh detail (higher = fewer gaps)
SHIFT_LON=0.0000237       # RTK east shift in degrees
SHIFT_LAT=0.0000131       # RTK north shift in degrees
```

## Tips

- **50m altitude flights produce the best results** -- 2.5cm/pixel vs 5cm/pixel at 120m
- Fly multiple passes over the same area from different angles for better stitching
- The pipeline skips videos where the drone is hovering (< 1 m/s horizontal speed)
- If ODM fails, intermediates are preserved so you can resume with `--rerun-from`
- After processing, commit and push to deploy via GitHub Pages
