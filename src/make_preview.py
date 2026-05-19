#!/usr/bin/env python3
"""Composite the timezone overlay PNG with the color legend into a single preview image.

Generates the legend at the same width as the overlay so it spans edge-to-edge.

Usage:
    python3 src/make_preview.py
    python3 src/make_preview.py --overlay dist/timezone_borders_raster_4k.png --output docs/preview-with-legend.png
"""

from __future__ import annotations

import argparse
import colorsys
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


# ── helpers shared with make_legend.py ──────────────────────────────────

def read_dbf_zone_values(dbf_path: Path) -> list[str]:
    data = dbf_path.read_bytes()
    _version, _year, _month, _day, record_count, header_len, record_len = \
        struct.unpack("<BBBBIHH20x", data[:32])
    fields: list[tuple[str, str, int]] = []
    offset = 32
    while offset < header_len and data[offset] != 0x0D:
        desc = data[offset: offset + 32]
        name = desc[:11].split(b"\0", 1)[0].decode("ascii")
        fields.append((name, chr(desc[11]), desc[16]))
        offset += 32
    zones: set[str] = set()
    pos = header_len
    for _ in range(record_count):
        record = data[pos: pos + record_len]
        pos += record_len
        if not record or record[:1] == b"*":
            continue
        vals: dict[str, str] = {}
        c = 1
        for n, _ft, length in fields:
            vals[n] = record[c: c + length].decode("latin1", errors="replace").strip()
            c += length
        z = vals.get("zone") or vals.get("name")
        if z:
            zones.add(z)
    return sorted(zones, key=float)


def offset_color(idx: int, total: int) -> tuple[int, int, int]:
    n = total - 1
    hue_deg = 210.0 - (idx / n) * 210.0 if n > 0 else 105.0
    sat = 0.95 if idx % 2 == 0 else 0.55
    r, g, b = colorsys.hsv_to_rgb(hue_deg / 360.0, sat, 1.0)
    return (int(r * 255), int(g * 255), int(b * 255))


def format_offset(val: str) -> str:
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


def generate_legend(
    zone_values: list[str],
    width: int,
    bg_color: tuple[int, int, int] = (18, 22, 31),
) -> Image.Image:
    """Generate a discrete-block staggered-legend at the given width.
    Returns an RGB Image with height = 140 * (width / 2240) rounded up.
    """
    total = len(zone_values)

    # Scale the canonical 2240×140 layout proportionally
    scale = width / 2240.0
    l_height = max(140, round(140 * scale))
    block_w = max(54, round(54 * scale))
    sep_w = 1
    bar_h = max(32, round(32 * scale))
    bar_top = max(31, round(31 * scale))
    bar_bot = bar_top + bar_h - 1
    font_size = max(12, round(12 * scale))
    footer_size = max(10, round(10 * scale))

    inner_w = total * block_w + (total - 1) * sep_w
    margin = (width - inner_w) // 2

    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    footer_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", footer_size)

    img = Image.new("RGB", (width, l_height), bg_color)
    draw = ImageDraw.Draw(img)

    # Blocks + separators
    for i in range(total):
        color = offset_color(i, total)
        x0 = margin + i * (block_w + sep_w)
        x1 = x0 + block_w - 1
        for y in range(bar_top, bar_bot + 1):
            for x in range(x0, x1 + 1):
                img.putpixel((x, y), color)
        if i < total - 1:
            sx = x1 + 1
            for y in range(bar_top, bar_bot + 1):
                img.putpixel((sx, y), (35, 39, 48))

    # Staggered labels
    for i, z in enumerate(zone_values):
        lbl = format_offset(z)
        x_center = margin + i * (block_w + sep_w) + block_w // 2
        bbox = font.getbbox(lbl)
        tw = bbox[2] - bbox[0]

        if i % 2 == 0:
            label_y = max(8, round(8 * scale))
            draw.text((x_center - tw // 2, label_y), lbl, fill=(200, 204, 213), font=font)
        else:
            row1_y = max(66, round(66 * scale))
            row2_y = max(78, round(78 * scale))
            ty = row1_y if i % 4 == 1 else row2_y
            draw.text((x_center - tw // 2, ty), lbl, fill=(130, 134, 143), font=font)

    # Footer
    footer = "Color legend — 40 timezone offsets (UTC−12 to UTC+14) · blue → red spectrum"
    fw = footer_font.getbbox(footer)[2] - footer_font.getbbox(footer)[0]
    footer_y = l_height - max(16, round(16 * scale))
    draw.text(((width - fw) // 2, footer_y), footer, fill=(90, 94, 103), font=footer_font)

    return img


# ── composite ────────────────────────────────────────────────────────────


def composite_preview(
    overlay_path: str | Path,
    dbf_path: str | Path,
    output_path: str | Path,
    background_color: tuple[int, int, int] = (12, 15, 24),
    legend_bg: tuple[int, int, int] = (18, 22, 31),
    gap: int = 30,
    quality: int = 90,
) -> None:
    """Composite overlay + auto-sized legend into a single image."""
    # Load overlay
    overlay = Image.open(overlay_path).convert("RGBA")
    o_w, o_h = overlay.size
    bg = Image.new("RGBA", overlay.size, (*background_color, 255))
    map_img = Image.alpha_composite(bg, overlay).convert("RGB")

    # Generate legend at overlay width
    zone_values = read_dbf_zone_values(Path(dbf_path))
    legend = generate_legend(zone_values, o_w, legend_bg)
    l_h = legend.size[1]

    # Build final canvas
    final_w = o_w
    final_h = o_h + gap + l_h
    canvas = Image.new("RGB", (final_w, final_h), legend_bg)

    canvas.paste(map_img, (0, 0))
    canvas.paste(legend, (0, o_h + gap))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, optimize=True, quality=quality)
    print(f"wrote {output_path} — {final_w}×{final_h}px ({output_path.stat().st_size} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)

    # Default overlay path
    default_overlay = Path("dist/timezone_borders_raster_4k.png")
    # Default DBF path (relative to workdir)
    default_dbf = Path("build/natural-earth/ne_10m_time_zones/ne_10m_time_zones.dbf")

    parser.add_argument("--overlay", type=Path, default=default_overlay,
                        help=f"Overlay PNG (default: {default_overlay})")
    parser.add_argument("--dbf", type=Path, default=default_dbf,
                        help=f"Natural Earth DBF for zone data (default: {default_dbf})")
    parser.add_argument("--output", type=Path, default=Path("docs/preview-with-legend.png"),
                        help="Output path (default: docs/preview-with-legend.png)")
    parser.add_argument("--quality", type=int, default=90, help="JPEG quality (default: 90)")
    parser.add_argument("--gap", type=int, default=30, help="Vertical gap (default: 30)")
    args = parser.parse_args()

    composite_preview(
        overlay_path=args.overlay,
        dbf_path=args.dbf,
        output_path=args.output,
        gap=args.gap,
        quality=args.quality,
    )


if __name__ == "__main__":
    main()
