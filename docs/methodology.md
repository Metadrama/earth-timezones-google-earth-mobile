# Methodology Notes

## Problem

Google Earth Mobile cannot load many images or a single very large texture. Previous approaches broke on these limits:

- tiled SuperOverlay: rejected `NetworkLink`/`Region`
- flat tile packs: too many image references (~951) hit "max external image limit"
- one-image regional at 4096×2979+: partially rendered due to mobile texture-size clipping

## Solution: spectrum single-image global overlay

Keep the KML minimal. One `GroundOverlay`, one PNG. No tiles, no SuperOverlay.

Texture size fixed at 4096×2048 — the exact dimension proven to render fully on the tested device.

Use a 2-pass rendering approach (black shadow + colored core) with thin strokes (`max(2, width//2048)` halo, `max(1, width//4096)` core line) and `joint="curve"` for smooth joins. This matches the proven yellow overlay exactly.

Color each timezone polygon ring by its UTC offset using a rainbow spectrum (blue→cyan→green→yellow→orange→red). The hue maps linearly from UTC-12 (blue) to UTC+14 (red), so any region gets a visible gradient.

## Data

Natural Earth `ne_10m_time_zones` — public domain.

## Generator

`src/make_raster_overlay.py` reads the NE shapefile and DBF, renders spectrum-colored rings with the proven 2-pass/joint="curve" approach, and packages as a KMZ.
