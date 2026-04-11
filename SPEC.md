# FarmMapTiles Specification

## Purpose

Serve drone orthomosaic imagery as map tiles for use in Leaflet-based applications, including Home Assistant's ha-map-card.

## Source Data

- DJI drone video recordings (MP4)
- Nadir orientation (-90° gimbal pitch)
- Flight altitude: 40–140m (50m preferred for higher resolution)
- Location: Queensland, Australia (-28.6975°S, 151.9338°E)
- GPS telemetry extracted from embedded subtitle streams

## Output

- **Tiles**: TMS format, zoom levels 15-22, WebP (q85)
- **Coverage**: ~210m x 300m
- **Resolution**: ~2.5cm/pixel at 50m altitude, ~5cm/pixel at 120m
- **Hosting**: GitHub Pages (static, no server required)

## ODM Settings (High Quality)

- `--orthophoto-resolution 2.5` — native resolution at 50m altitude
- `--feature-quality ultra` — best feature matching across overlapping frames
- `--pc-quality high` — dense point cloud (`ultra` requires >150GB disk)
- `--mesh-octree-depth 12` — fine mesh to avoid gaps in orthomosaic
- `--orthophoto-cutline` — better blending (has a known MultiPolygon bug; pipeline handles this)

## Alignment

Orthomosaic shifted +2.3m east, +1.45m north to align with RTK GPS reference points.
