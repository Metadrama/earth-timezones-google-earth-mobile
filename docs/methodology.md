# Methodology Notes

## Problem

Google Earth Mobile (Samsung Z Flip 3) has multiple hard limits:

1. **SuperOverlay** (tiles + `NetworkLink`/`Region`/`Lod`) → rejected with "Unsupported element"
2. **Flat tile packs** (~951 PNGs) → "max external image limit reached" at ~22 references
3. **Single oversized texture** (4096×2979+) → partially renders due to mobile GPU texture-size limit

After testing all three failure modes, the proven solution is:

## Solution: one-image global spectrum overlay

One `GroundOverlay`, one PNG, sized to the confirmed working limit.

### Texture constraints

- **Dimensions:** 4096 × 2048 (confirmed full render on device)
- **Short side ≤ 2048 px** (the effective mobile texture-size limit)
- **One image only** — avoids the ~22 image-reference cap

### Rendering

The 2-pass approach proven in the first working yellow overlay:

```python
halo_width = max(2, width // 2048)    # = 2 at 4096
line_width = max(1, width // 4096)     # = 1 at 4096

# Pass 1: black shadow for contrast
draw.line(points, fill=(0, 0, 0, 190), width=halo_width, joint="curve")

# Pass 2: colored core
draw.line(points, fill=color, width=line_width, joint="curve")
```

`joint="curve"` produces smooth joins between line segments. The shadow provides contrast on any basemap color.

### Color assignment

Each of the 40 unique `zone` values from Natural Earth's DBF metadata gets one fixed color:

1. **Sort** all 40 offsets by numeric value → index 0 (UTC−12) to 39 (UTC+14)
2. **Hue:** `210° × (1 − idx/39)` — linear from sky blue to red (210 skips dark blue)
3. **Saturation:** `0.95` if even index (vivid), `0.55` if odd (washed) — keeps neighbors distinct
4. **Value:** always `1.0` — no dim colors to blend into dark ocean

This gives 40 distinct, single colors that form a visible cold→warm spectrum.

## Data

Natural Earth `ne_10m_time_zones` — public domain.
