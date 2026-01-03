# FarmMapTiles Implementation Plan

## Completed

1. **ODM Processing** - Created orthomosaic from 23 DJI drone images
   - Output: 6039 x 4168 px GeoTIFF
   - Coverage: ~210m x 300m area
   - Location: -28.6975°S, 151.9338°E (Queensland)

2. **Tile Generation** - Created 120 tiles at zoom levels 15-20
   - Used gdal2tiles.py
   - Output: `tiles/` directory with z/x/y structure

3. **Leaflet Viewer** - `index.html` with:
   - Esri satellite + OSM base layers
   - Farm orthomosaic overlay
   - Layer control for toggling

## To Deploy on GitHub Pages

1. Create a GitHub repo
2. Push the tiles and index.html
3. Enable GitHub Pages (Settings > Pages > Source: main branch)
4. Access at: `https://<username>.github.io/<repo>/`

## Notes

- The `code/` directory contains ODM intermediate files (~150MB) - excluded via .gitignore
- Tiles + HTML are ~15MB total - well within GitHub Pages limits
