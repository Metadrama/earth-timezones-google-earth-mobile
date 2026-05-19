#!/usr/bin/env python3
"""Generate a one-row discrete-block color legend for the 40 timezone offsets.

Matching the exact colors used by make_raster_overlay.py. Outputs a 2240×140
PNG with dark background, staggered labels, and the legend used in the README.

Usage:
    python3 src/make_legend.py                              # default output
    python3 src/make_legend.py --output docs/my-legend.png   # custom path
"""

from __future__ import annotations

import argparse
import colorsys
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def read_dbf_zone_values(dbf_path: Path) -> list[str]:
    """Read unique sorted zone values from the Natural Earth DBF."""
    data = dbf_path.read_bytes()
    _version, _year, _month, _day, record_count, header_len, record_len = \
        struct.unpack("<BBBBIHH20x", data[:32])

    fields: list[tuple[str, str, int]] = []
    offset = 32
    while offset < header_len and data[offset] != 0x0D:
        descriptor = data[offset: offset + 32]
        name = descriptor[:11].split(b"\0", 1)[0].decode("ascii")
        field_type = chr(descriptor[11])
        length = descriptor[16]
        fields.append((name, field_type, length))
        offset += 32

    zones: set[str] = set()
    pos = header_len
    for _ in range(record_count):
        record = data[pos: pos + record_len]
        pos += record_len
        if not record or record[:1] == b"*":
            continue
        cursor = 1
        values: dict[str, str] = {}
        for name, _ft, length in fields:
            raw = record[cursor: cursor + length]
            cursor += length
            values[name] = raw.decode("latin1", errors="replace").strip()
        z = values.get("zone") or values.get("name")
        if z:
            zones.add(z)

    return sorted(zones, key=float)


def offset_color(idx: int, total: int = 40) -> tuple[int, int, int]:
    """Exact match to make_raster_overlay.py's timezone_color()."""
    n = total - 1
    hue_deg = 210.0 - (idx / n) * 210.0 if n > 0 else 105.0
    sat = 0.95 if idx % 2 == 0 else 0.55
    r, g, b = colorsys.hsv_to_rgb(hue_deg / 360.0, sat, 1.0)
    return (int(r * 255), int(g * 255), int(b * 255))


def format_offset(val: str) -> str:
    """Format a zone value like -5.00 → UTC-5, 5.75 → UTC+5:45"""
    f = float(val)
    if f == 0:
        return "UTC±0"
    sign = "+" if f > 0 else "-"
    whole = int(abs(f))
    frac = abs(f) - whole
    if frac == 0:
        return f"UTC{sign}{whole}"
    elif frac == 0.5:
        return f"UTC{sign}{whole}:30"
    elif frac == 0.75:
        return f"UTC{sign}{whole}:45"
    return f"UTC{sign}{whole}"


def make_legend_staggered(
    zone_values: list[str],
    width: int = 2240,
    height: int = 140,
    out_path: str | Path = "docs/legend-staggered.png",
) -> None:
    """Render a 2240×140 legend with discrete color blocks, staggered labels,
    dark background, and thin separators between each timezone offset."""
    total = len(zone_values)
    bg_color = (18, 22, 31)

    # Block layout
    block_w = 54
    sep_w = 1
    bar_top = 31
    bar_bot = 62

    inner_w = total * block_w + (total - 1) * sep_w
    margin = (width - inner_w) // 2

    # Fonts
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    footer_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Draw discrete color blocks with separators
    for i in range(total):
        color = offset_color(i, total)
        x0 = margin + i * (block_w + sep_w)
        x1 = x0 + block_w - 1

        for y in range(bar_top, bar_bot + 1):
            for x in range(x0, x1 + 1):
                img.putpixel((x, y), color)

        # Thin separator after each block except the last
        if i < total - 1:
            sx = x1 + 1
            for y in range(bar_top, bar_bot + 1):
                img.putpixel((sx, y), (35, 39, 48))

    # Staggered labels: even idx above bar, odd idx below bar
    for i, z in enumerate(zone_values):
        lbl = format_offset(z)
        x_center = margin + i * (block_w + sep_w) + block_w // 2
        bbox = font.getbbox(lbl)
        tw = bbox[2] - bbox[0]

        if i % 2 == 0:
            # Above bar
            draw.text((x_center - tw // 2, 8), lbl, fill=(200, 204, 213), font=font)
        else:
            # Below bar — two alternating rows for readability
            ty = 66 if i % 4 == 1 else 78
            draw.text((x_center - tw // 2, ty), lbl, fill=(130, 134, 143), font=font)

    # Footer text
    footer = "Color legend — 40 timezone offsets (UTC−12 to UTC+14) · blue → red spectrum"
    fw = footer_font.getbbox(footer)[2] - footer_font.getbbox(footer)[0]
    draw.text(((width - fw) // 2, 124), footer, fill=(90, 94, 103), font=footer_font)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, optimize=True)
    print(f"wrote {out_path} — {width}×{height}px ({out_path.stat().st_size} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, default=Path("build/natural-earth"))
    parser.add_argument("--output", type=Path, default=Path("docs/legend-staggered.png"),
                        help="Output path (default: docs/legend-staggered.png)")
    parser.add_argument("--width", type=int, default=2240,
                        help="Canvas width (default: 2240)")
    parser.add_argument("--height", type=int, default=140,
                        help="Canvas height (default: 140)")
    args = parser.parse_args()

    dbf_path = args.workdir / "ne_10m_time_zones" / "ne_10m_time_zones.dbf"
    if not dbf_path.exists():
        print(f"ERROR: {dbf_path} not found. Run make_raster_overlay.py first to download Natural Earth data.")
        return 1

    zone_values = read_dbf_zone_values(dbf_path)
    print(f"Found {len(zone_values)} unique zone values")

    make_legend_staggered(
        zone_values,
        width=args.width,
        height=args.height,
        out_path=args.output,
    )


if __name__ == "__main__":
    main()
