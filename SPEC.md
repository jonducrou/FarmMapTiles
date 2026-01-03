# FarmMapTiles Specification

## Purpose

Serve drone orthomosaic imagery as map tiles for use in Leaflet-based applications, including Home Assistant's ha-map-card.

## Source Data

- 23 DJI drone images (DJI_0560-0582.JPG)
- Nadir orientation (-90° gimbal pitch)
- ~120m altitude
- Location: Queensland, Australia (-28.6975°S, 151.9338°E)

## Output

- **Tiles**: TMS format, zoom levels 15-22
- **Coverage**: ~210m x 300m
- **Resolution**: ~5cm/pixel at max zoom
- **Hosting**: GitHub Pages (static, no server required)

## Alignment

Orthomosaic shifted +2m east, +1m north to align with RTK GPS reference points.
