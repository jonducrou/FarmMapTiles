# FarmMapTiles Specification

## Purpose
Convert DJI drone aerial imagery into a Leaflet-compatible tile source, hosted on GitHub Pages.

## Source Data
- 6 DJI drone images (DJI_0551-0556.JPG)
- GPS coordinates embedded in EXIF data
- Location: Queensland, Australia (~28.697°S, 151.934°E)
- Images have significant overlap

## Output
- Seamless orthomosaic from stitched drone images
- Slippy map tiles (z/x/y structure) for Leaflet
- Static HTML viewer
- Hosted on GitHub Pages (no server required)

## Technical Requirements
- OpenDroneMap for image stitching/orthomosaic generation
- GDAL (gdal2tiles.py) for tile generation
- Leaflet.js for map display
