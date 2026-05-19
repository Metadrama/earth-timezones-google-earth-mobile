# Methodology Notes

## Problem

Google Earth Mobile cannot load many images or a single very large texture. Previous approaches broke on these limits:

- tiled SuperOverlay: rejected `NetworkLink`/`Region`
- flat tile packs: too many image references (~951) hit "max external image limit"
- one-image regional 4K (4096×2979) and 8K (8192×5958): partially rendered (~25%) due to mobile texture-size clipping

## The fix: spectrum single-image overlay

Keep the KML minimal. One `GroundOverlay`, one PNG. No tile images. No SuperOverlay elements.

Restrict image dimensions so the shorter side ≤ 2048 px. The tested working dimension is 4096×2048 (global 4K raster). Regional variants use the same constraint.

Color-code each timezone border by UTC offset using a rainbow spectrum (blue→cyan→green→yellow→orange→red). This replaces the earlier yellow linework and the experimental neon cyan/magenta alternation.

## Data

Natural Earth `ne_10m_time_zones` — public domain.

## Generator

`src/make_regional_raster_overlay.py` reads the NE shapefile, clips to the target bbox, renders spectrum-colored segments onto a transparent PNG, and packages it as a KMZ.

```bash
python3 src/make_regional_raster_overlay.py --width 2816 --bbox 90,-15,145,25 --label se_asia_28k_spectrum --color-scheme spectrum
```

The `--color-scheme` argument supports `spectrum` (default) and `neon` (v0.1-style cyan/magenta alternation).
