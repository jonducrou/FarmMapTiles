# FarmMapTiles

## Summary

Drone orthomosaic map tiles with timelapse capability, hosted on GitHub Pages.

## Current State (2026-01-04)

### Completed
- [x] Static orthomosaic from 23 DJI images (already deployed)
- [x] Timelapse processing scripts created
- [x] Scanned 370 pCloud videos → found 8 good mapping videos
- [x] Copied 8 good videos locally to `videos/` (6.3GB)
- [x] Leaflet viewer updated with date slider
- [x] Extracted frames from all 8 videos with GPS geotags
- [x] Ran OpenDroneMap for 6 dates (5 successful, 1 failed)
- [x] Generated tiles for 5 dates with RTK alignment shift
- [x] Converted tiles to WebP format (89% size reduction, ~1.7GB → ~200MB)

### Timelapse Dates Available
| Date | Tiles | Status |
|------|-------|--------|
| 2023-02-18 | 2,076 | ✓ |
| 2023-09-16 | 7,848 | ✓ |
| 2023-11-11 | 7,020 | ✓ |
| 2023-12-28 | - | ✗ (drone was hovering, no camera movement) |
| 2024-10-26 | 8,202 | ✓ |
| 2025-04-17 | 5,433 | ✓ |

### Next Steps
1. [x] Deploy timelapse tiles to GitHub Pages

## Timelapse Processing Pipeline

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/scan_videos.py` | Scan videos, filter by nadir pitch (-90°) and altitude (~120m) |
| `scripts/extract_frames.py` | Extract frames with GPS EXIF from embedded subtitle telemetry |
| `scripts/process_date.sh` | Run ODM and generate tiles for a single date |
| `scripts/process_all.sh` | Master script: scan → extract → process all dates |

### Filter Criteria

Videos are included if:
- Camera Pitch: -85° to -95° (nadir)
- Altitude: 100m to 140m
- Valid GPS coordinates

### Running the Pipeline

```bash
# Full pipeline from video directory
./scripts/process_all.sh /path/to/drone/videos

# Or step by step:
python3 scripts/scan_videos.py /path/to/videos manifest.json
python3 scripts/extract_frames.py --manifest manifest.json frames 2
./scripts/process_date.sh 2023-02-18 frames/2023-02-18
```

## Output Structure

```
tiles/
├── {z}/{x}/{y}.png           # Original static tiles
├── 2023-02-18/{z}/{x}/{y}.png  # Date-specific tiles
└── 2023-03-15/{z}/{x}/{y}.png
viewer_manifest.json          # Available dates for slider
```

## Usage

### Leaflet / Web
```javascript
L.tileLayer('https://jonducrou.github.io/FarmMapTiles/tiles/{z}/{x}/{y}.png', {
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
tile_layer_url: https://jonducrou.github.io/FarmMapTiles/tiles/{z}/{x}/{y}.png
tile_layer_options:
  tms: true
  minZoom: 15
  maxZoom: 22
```

## Tools Required

- **exiftool** - Video metadata extraction
- **ffmpeg** - Frame and subtitle extraction
- **OpenDroneMap** (Docker) - Orthomosaic generation
- **GDAL** - Georeferencing and tile generation
- **Python 3** - Processing scripts
