# FarmMapTiles

## Summary

Drone orthomosaic map tiles with timelapse capability, hosted on GitHub Pages.

## Current State (2026-04-05)

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
- [x] High-res 2.5cm/pixel tiles from 50m altitude flight (2026-04-03)
- [x] Self-recovering pipeline script for batch processing

### Timelapse Dates Available
| Date | Tiles | Altitude | Resolution | Status |
|------|-------|----------|------------|--------|
| 2023-02-18 | 2,076 | 120m | 5cm | ✓ |
| 2023-09-16 | 7,848 | 120m | 5cm | ✓ |
| 2023-11-11 | 7,020 | 120m | 5cm | ✓ |
| 2023-12-28 | - | - | - | ✗ (drone hovering, no movement) |
| 2024-10-26 | 8,202 | 120m | 5cm | ✓ |
| 2025-04-17 | 5,433 | 120m | 5cm | ✓ |
| 2026-04-03 | 1,469 | 50m | 2.5cm | ✓ (high-res) |

### Next Steps
1. [ ] Source more drone videos for additional timelapse dates
2. [ ] Re-process older dates with improved ODM settings
3. [ ] Revisit RTK alignment with known ground control points

## Pipeline

### Self-Recovering Pipeline (`scripts/pipeline.sh`)

The main entry point for processing. Designed for external drives to avoid
filling the boot disk. Tracks per-date state so it can be interrupted and
resumed at any point.

```bash
# Run the full pipeline
./scripts/pipeline.sh /Volumes/External/drone_videos /Volumes/External/odm_work

# Re-run after a failure — automatically resumes where it left off
./scripts/pipeline.sh /Volumes/External/drone_videos /Volumes/External/odm_work
```

**Processing stages per date:**
1. Scan videos (filter for nadir pitch, 40–140m altitude)
2. Extract geotagged frames (1s intervals)
3. Run OpenDroneMap (with cutline bug fallback)
4. Apply RTK alignment shift
5. Generate TMS tiles (zoom 15–22)
6. Convert to WebP (q85)
7. Deploy to repo `tiles/` directory
8. Clean up ODM intermediates

**Requirements:**
- Docker/OrbStack with ≥32GB RAM allocated
- ≥80GB free disk on work drive per date being processed
- exiftool, ffmpeg, GDAL, cwebp, Python 3

### Legacy Scripts

| Script | Purpose |
|--------|---------|
| `scripts/scan_videos.py` | Scan videos, filter by nadir pitch and altitude |
| `scripts/extract_frames.py` | Extract frames with GPS EXIF from subtitle telemetry |
| `scripts/process_date.sh` | Run ODM and generate tiles for a single date |
| `scripts/process_all.sh` | Old master script (superseded by pipeline.sh) |

### Filter Criteria

Videos are included if:
- Camera Pitch: -85° to -95° (nadir)
- Altitude: 40m to 140m
- Valid GPS coordinates

## Output Structure

```
tiles/
├── {z}/{x}/{y}.png           # Original static tiles
├── 2023-02-18/{z}/{x}/{y}.webp # Date-specific tiles
└── 2026-04-03/{z}/{x}/{y}.webp
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
- **cwebp** - WebP tile conversion
- **Python 3** - Processing scripts
