# Decisions Log

## 2026-01-04: WebP Format for Tiles

**Problem:** PNG tiles were ~1.7GB total, exceeding GitHub Pages' 1GB soft limit.

**Options Considered:**
1. Limit max zoom to 21 - loses detail
2. JPEG format - lossy, ~70% smaller
3. WebP format - best compression, ~89% smaller
4. PNG compression (pngquant) - ~50% smaller

**Decision:** Use WebP format with quality 85.

**Rationale:**
- 89% size reduction (78KB PNG → 8.5KB WebP per tile)
- ~1.7GB → ~200MB estimated total
- Supported by all modern browsers
- Near-lossless quality at q85
- Fits comfortably within GitHub Pages limits

**Implementation:**
- Convert all PNG tiles using: `cwebp -q 85 input.png -o output.webp`
- Update Leaflet tile layer to use `.webp` extension


## 2026-01-04: Excluded 2023-12-28 from Timelapse

**Problem:** ODM failed for 2023-12-28 with Qhull error during feature matching.

**Root Cause:** All 21 extracted frames had identical GPS coordinates (-28°41'50.28"S, 151°56'4.20"E). The drone was hovering in place, not flying a mapping pattern.

**Decision:** Exclude this date from the timelapse - the source data is unsuitable for orthomosaic generation.


## 2026-04-05: pc-quality ultra Requires Too Much Disk

**Problem:** `--pc-quality ultra` with 1,123 frames consumed >146GB of intermediate files, crashing OrbStack with I/O errors on a 460GB disk.

**Options Considered:**
1. `--pc-quality ultra` — best quality but >150GB disk per date
2. `--pc-quality high` — good quality, ~76GB disk per date
3. `--pc-quality medium` — fast but lower quality

**Decision:** Use `--pc-quality high` with `--mesh-octree-depth 12` and `--orthophoto-cutline`.

**Rationale:**
- `high` produced excellent results at 2.5cm/pixel from 50m altitude
- Adding `--mesh-octree-depth 12` fixed a rectangular gap that appeared with default mesh settings
- `ultra` is impractical without >200GB free disk per date
- The cutline option has a known fiona bug (MultiPolygon != Polygon) — pipeline falls back gracefully


## 2026-04-05: ODM Cutline MultiPolygon Bug

**Problem:** `--orthophoto-cutline` crashes with `fiona.errors.GeometryTypeValidationError: 'MultiPolygon' != 'Polygon'` on some datasets.

**Root Cause:** Bug in ODM's cutline.py — it writes a MultiPolygon to a schema expecting Polygon.

**Decision:** Pipeline tries cutline first, then checks if the orthomosaic TIF was generated despite the crash. If so, proceeds without cutline. The orthomosaic is generated before the cutline step, so the output is usable.


## 2026-04-05: External Drive for ODM Work

**Problem:** ODM intermediate files (opensfm, depth maps, point clouds) consume 76–150GB per date. Processing multiple dates fills the boot disk.

**Decision:** Pipeline accepts a work directory argument, intended for an external drive. All intermediates stay on the external drive; only final WebP tiles (~18MB per date) are copied to the repo.

**Rationale:**
- Boot disk has 460GB total, shared with OS and other projects
- External drive can be dedicated to ODM processing
- Intermediates are cleaned after successful tile deployment
- State files allow resuming after interruption
