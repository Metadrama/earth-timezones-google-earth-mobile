# Methodology Notes

## Problem

Google Earth Mobile can become extremely slow when loading timezone KML files as vector “map features”. The bottleneck appears to be feature/rendering overhead rather than raw file size alone.

A polygon timezone layer is costly because it may contain:

- many polygon placemarks
- many rings and island fragments
- thousands of coordinate vertices
- fill and outline styling
- clickable feature metadata and labels

Simplifying vector geometry reduces coordinates but also damages the exact border shapes. In testing, even a heavily simplified ~100 KB vector KML still lagged on mobile and looked visibly lossy.

## Tested approaches

### 1. Direct vector KML

Accurate, but very slow on Google Earth Mobile.

### 2. Simplified vector KML

Faster on paper, but still laggy because it remains a feature layer. Geometry loss becomes visible when simplification is strong enough to reduce size meaningfully.

### 3. Single raster GroundOverlay

Good first fix.

The timezone boundaries are rendered once into a transparent PNG. The KMZ loads that image as one global `GroundOverlay`. This avoids mobile vector feature management and preserves the source geometry visually at the chosen raster resolution.

Weakness: close zoom becomes blurry unless the single global image becomes extremely large. For example, keeping Peninsular Malaysia around 1080p detail would imply a global raster roughly 80,000 px wide, which is poor for mobile decode/runtime.

### 4. Tiled raster SuperOverlay

This was the first v2 approach.

The timezone borders are split into many small raster tiles. KML `Region` and `Lod` rules tell compatible Google Earth clients to load child tiles only when their geographic region is large enough on screen.

This changes the workload:

- low zoom: a few low-detail parent tiles
- close zoom: high-detail tiles only near the camera
- empty tiles: skipped
- vector features: avoided

However, some Google Earth Mobile builds reject the required SuperOverlay elements and show:

```text
Unsupported element: 'NetworkLink'.
Unsupported element: 'Region'.
```

So the SuperOverlay remains useful as a desktop/advanced experiment, but it is not the safest phone artifact.

### 5. Flat tiled regional GroundOverlay pack

This was the v2.1 mobile fallback.

The timezone borders are still rasterized into many 512 × 512 PNG tiles, but the KMZ contains only one `doc.kml` with simple `GroundOverlay` entries. It deliberately avoids `NetworkLink`, `Region`, and `Lod`.

Tradeoff:

- compatible with stricter Google Earth Mobile KML parsing
- sharper than a single global raster in the chosen region
- but all listed overlays load together
- on tested Google Earth Mobile, hundreds of PNG references can trigger: `max external image limit being reached`

### 6. One-image regional GroundOverlay pack

This was the v0.1 strict mobile-compatible approach.

The timezone borders are rendered into one high-resolution regional transparent PNG and placed with one `GroundOverlay`. The current styling uses alternating neon light cyan and neon magenta from timezone offset metadata, plus thicker shadow/glow strokes for zoomed-out visibility. This avoids both failure classes seen on mobile:

- no `NetworkLink` / `Region` / `Lod`
- no hundreds of image references

The tradeoff is that this is regional and bounded by mobile texture/decode limits, so both 8K and 4K regional variants are produced.

On the tested phone, both the 4K and 8K one-image variants rendered only partially. That strongly suggests a mobile texture-size/decode limit rather than KML incompatibility: the app accepted the `GroundOverlay`, but did not display the full large texture.

### 7. Low-count paneled regional GroundOverlay pack

Chosen v0.2 approach.

The timezone borders are rendered as a high-resolution virtual regional raster, then split into a small grid of max-2048 px PNG panels. The KMZ still uses only one root `doc.kml` and simple `GroundOverlay` + `LatLonBox` entries.

This targets the observed mobile compatibility envelope:

- no `NetworkLink` / `Region` / `Lod`
- far fewer image references than the flat tiled pack
- no single giant texture, so mobile texture-size clipping should be avoided
- higher effective regional resolution than the one-image 8K pack

## Projection

The raster tiles use a simple geographic/equirectangular mapping per tile:

```text
x = (longitude - tile_west) / (tile_east - tile_west) * tile_width
y = (tile_north - latitude) / (tile_north - tile_south) * tile_height
```

Each tile is placed with a KML `LatLonBox`:

```text
north = tile north latitude
south = tile south latitude
east  = tile east longitude
west  = tile west longitude
```

## Overlay structures

### Strict mobile paneled regional pack

The generated v0.2 strict mobile KMZ contains:

```text
doc.kml
panels/panel_<row>_<col>.png
```

The root `doc.kml` contains one `GroundOverlay` per non-empty panel:

1. `Icon/href` pointing to the panel PNG.
2. `LatLonBox` placing that panel geographically.

It contains no `NetworkLink`, no `Region`, and no `Lod`. The current primary artifact has 40 image references; the fallback has 26.

### Strict mobile one-image regional pack

The generated strict mobile KMZ contains:

```text
doc.kml
files/timezone_borders_regional_<label>.png
```

The root `doc.kml` contains one `GroundOverlay`:

1. `Icon/href` pointing to the single PNG.
2. `LatLonBox` placing the regional image geographically.

It contains no `NetworkLink`, no `Region`, no `Lod`, and only one image reference.

Styling strategy:

1. Read Natural Earth's DBF metadata alongside the shapefile rings.
2. Use the timezone `zone` offset as the deterministic color code.
3. Alternate whole-hour offsets between neon light cyan and neon magenta; half-hour/quarter-hour offsets are assigned by rounded half-hour step.
4. Draw in three passes: black shadow, translucent neon glow, bright neon core. This keeps the borders visible on satellite/terrain imagery without using common map colors like yellow, red, blue, or green.

### Flat tiled regional pack

The generated flat tiled KMZ contains:

```text
doc.kml
tiles/<z>/<x>/<y>.png
```

The root `doc.kml` contains one `GroundOverlay` per rendered PNG tile:

1. `Icon/href` pointing to `tiles/<z>/<x>/<y>.png`.
2. `LatLonBox` placing that tile geographically.

It contains no `NetworkLink`, no `Region`, and no `Lod`.

### SuperOverlay experiment

The generated SuperOverlay KMZ contains:

```text
doc.kml
tiles/<z>/<x>/<y>.kml
tiles/<z>/<x>/<y>.png
```

The root `doc.kml` links to the root tile. Each tile KML contains:

1. A `GroundOverlay` pointing to that tile's PNG if the tile has visible timezone borders.
2. A `Region` / `Lod` block limiting when that overlay is active.
3. `NetworkLink`s to child tile KML files, also guarded by `Region` / `Lod`.

## Resolution choice

Current recommended mobile artifact:

- File: `earth_timezones_regional_se_asia_16k_neon_panels.kmz`
- Region: Southeast Asia (`west=90`, `south=-15`, `east=145`, `north=25`)
- Virtual image size: 16384 × 11916 px
- Panel max size: 2048 × 2048 px
- Image references: 40
- KMZ size: about 2.6 MB
- KML compatibility: `GroundOverlay` + `LatLonBox`; no SuperOverlay elements
- Styling: alternating neon light cyan / neon magenta, thicker shadow/glow linework

The 12K fallback is `earth_timezones_regional_se_asia_12k_neon_panels.kmz`, virtual image size 12288 × 8937 px, 26 image references, about 1.8 MB.

Previous v0.1 one-image artifact:

- File: `earth_timezones_regional_se_asia_8k_neon.kmz`
- Image size: 8192 × 5958 px
- Image references: 1
- KMZ size: about 248 KB
- Known mobile risk: partial rendering from large-texture limits

Flat tiled experiment:

- File: `earth_timezones_mobile_flat_se_asia_z9.kmz`
- PNG tiles: 951
- KMZ size: about 661 KB
- Known mobile risk: max external image-count limit

The z8 flat tiled variant has 457 PNG tiles and is about 360 KB.

Current SuperOverlay experiment:

- Max zoom: z8
- Tile size: 512 × 512 px
- Effective world width at max zoom: 512 × 2^8 = 131,072 px
- Peninsular Malaysia at roughly 5° wide: about 1,820 px across
- KMZ size: about 30 MB
- Internal KML files: 42,454
- Internal PNG tiles: 18,752

The SuperOverlay targets close-zoom readability on compatible clients while avoiding one huge global texture.

## Why regional 16K panels

A Samsung S21 Ultra-class screen can make a country-scale view reveal blur in the 4K/8K global single-image overlays.

A global 8K image spreads 8192 px across 360°:

```text
pixels per degree = 8192 / 360 ≈ 23 px/degree
5° viewport ≈ 114 px
```

The Southeast Asia 8K regional image spreads 8192 px across 55°:

```text
pixels per degree = 8192 / 55 ≈ 149 px/degree
5° viewport ≈ 745 px
```

That is much sharper than the global 8K overlay while still using only one image reference. The thicker neon stroke is deliberately less subtle than the earlier yellow linework, because low-zoom visibility on mobile mattered more than hiding the overlay into the base map.

The v0.2 paneled 16K regional image spreads 16384 px across 55°:

```text
pixels per degree = 16384 / 55 ≈ 298 px/degree
5° viewport ≈ 1,489 px
```

The 16K image is split into 40 non-empty panels, each no larger than 2048 px per side. This uses more image references than v0.1, but stays far below the hundreds-of-images limit that broke the flat z9 tile pack.

For comparison, tiled z8/z9 provides more theoretical local detail, but it failed the observed mobile compatibility envelope: SuperOverlay elements are unsupported, and flat tile packs hit image-count limits.

## Future architecture

Possible next improvements:

1. More paneled regional packs: Europe, North America, Middle East, global low-zoom.
2. Tune neon visual styles for dark, satellite, and terrain basemaps.
3. A CI workflow that rebuilds artifacts and validates all internal KML files.
