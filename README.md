# Earth Timezone Borders for Google Earth Mobile

A lightweight Google Earth Mobile overlay for visualizing timezone borders without the lag from polygon-heavy KML files.

The approach is simple: **render timezone boundaries into a transparent PNG and load it as a `GroundOverlay`**. One image, one KML entry, no tiles, no SuperOverlay, no image-count limit problems.

## Color coding

Each timezone offset gets its own color in a **rainbow spectrum**:

| Offset  | Color        | Offset  | Color        |
|---------|-------------|---------|--------------|
| UTC+5   | blue        | UTC+8   | green        |
| UTC+5:30 | blue-cyan  | UTC+9   | yellow-green |
| UTC+6   | cyan        | UTC+10  | orange       |
| UTC+6:30 | teal       | UTC+11  | red          |
| UTC+7   | green-teal  |         |              |

The pattern is intuitive without needing a legend: **bluer = earlier offset, redder = later offset**.

## Download

Three artifacts in [`dist/`](dist/):

| File | Size | Region | Resolution | px/deg |
|------|------|--------|-----------|--------|
| `earth_timezones_regional_se_asia_28k_spectrum.kmz` | ~65 KB | SE Asia (90–145°E, 15°S–25°N) | 2816×2048 | 51 |
| `earth_timezones_regional_se_asia_extended_4k_spectrum.kmz` | ~84 KB | Extended SE Asia (77.5–157.5°E) | 4096×2048 | 51 |
| `earth_timezones_regional_global_4k_spectrum.kmz` | ~239 KB | Global (-180–180°, -90–90°) | 4096×2048 | 11 |

**Recommendation:** start with the regional 28K (SE Asia core). If it renders fully and you want more area, switch to the extended 4K. The global version is a universal fallback.

## Usage

1. Download the `.kmz` file.
2. Open it with Google Earth Mobile (or import via Projects → Import KML/KMZ file).
3. If you previously imported a different version, delete the old layer first.

## Rebuild

```bash
pip install Pillow
python3 src/make_regional_raster_overlay.py --width 2816 --bbox 90,-15,145,25 --label se_asia_28k_spectrum --color-scheme spectrum
```

Customize `--width`, `--bbox`, and `--color-scheme spectrum|neon`.

## Why this works

Earlier attempts failed because:
- **SuperOverlay** → some mobile builds reject `NetworkLink`/`Region`
- **Tile packs** → hundreds of PNGs hit the mobile image-count limit (~22)
- **Single oversized image** → 4096+ textures partially render on mobile

**This version** uses a single image with texture dimensions guaranteed to fit mobile GPU limits (no side > 2048 for the shorter dimension). The 4096×2048 variant matches the exact dimensions that tested working.

## Credits

- Timezone boundary data: [Natural Earth](https://www.naturalearthdata.com/), public domain.
- Rendering: [Pillow](https://python-pillow.org/).
- Built for Google Earth Mobile after vector timezone KML proved too laggy in practice.

## License

MIT. Natural Earth data is public domain.
