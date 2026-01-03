# FarmMapTiles - Complete

## Summary

Converted 23 DJI drone images into Leaflet-compatible map tiles, hosted on GitHub Pages.

## What Was Done

1. **OpenDroneMap Processing** - Stitched 23 nadir drone images into a seamless orthomosaic (6039x4168 px)

2. **Tile Generation** - Created 1348 tiles at zoom levels 15-22 using gdal2tiles.py (TMS format)

3. **RTK Alignment** - Shifted orthomosaic +2m east, +1m north to align with RTK GPS positions

4. **Deployment** - Hosted on GitHub Pages at https://jonducrou.github.io/FarmMapTiles/

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

## Tools Used

- **OpenDroneMap** (Docker) - Orthomosaic generation
- **GDAL** - Georeferencing adjustment and tile generation
- **GitHub Pages** - Static tile hosting
