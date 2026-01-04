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
