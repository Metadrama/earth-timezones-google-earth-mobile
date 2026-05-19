# Earth Timezone Borders for Google Earth Mobile

A lightweight Google Earth Mobile overlay for visualizing timezone borders without the lag from polygon-heavy KML files.

The approach: **render timezone boundaries into a transparent PNG and load it as a KML `GroundOverlay`**. One image, one KML entry. No panels, no tiles, no SuperOverlay — the approach proven to work on the tested device at 4096×2048.

## Color coding

Each timezone offset gets its own color in a **rainbow spectrum** — intuitive without labels:

| Offset | Color | Offset | Color |
|--------|-------|--------|-------|
| UTC-12 → UTC-8 | deep blue → blue | UTC+3 → UTC+6 | green → teal |
| UTC-7 → UTC-3 | cyan → teal-green | UTC+7 → UTC+9 | lime → yellow |
| UTC-2 → UTC+2 | green → yellow-green | UTC+10 → UTC+14 | orange → red |

The pattern: **cooler (blue) = earlier offset, warmer (red) = later offset**.

## Download

**`earth_timezones_raster_4k_spectrum.kmz`** — 4096×2048, global, ~163 KB.

Download from the [v1.0 release](https://github.com/Metadrama/earth-timezones-google-earth-mobile/releases/tag/v1.0).

## Usage

1. Download the `.kmz` file.
2. Delete any previous timezone overlay from Google Earth Projects.
3. Open the `.kmz` with Google Earth Mobile.

## Why this works

Built with the exact same renderer as the proven global yellow overlay:
- One `GroundOverlay`, one PNG — no tile count issues
- 4096×2048 — texture size proven to render fully
- 2-pass stroke (black shadow + colored core) — thin lines, proven
- `joint="curve"` for smooth joins

## Rebuild

```bash
pip install Pillow
python3 src/make_raster_overlay.py --resolution "4k:4096x2048"
```

The `make_raster_overlay.py` script reads Natural Earth's `ne_10m_time_zones` shapefile and its DBF metadata, renders spectrum-colored rings onto a transparent PNG, and packages as a KMZ.

## Credits

- Timezone boundary data: [Natural Earth](https://www.naturalearthdata.com/), public domain.
- Rendering: [Pillow](https://python-pillow.org/).

## License

MIT. Natural Earth data is public domain.
