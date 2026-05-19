#!/usr/bin/env python3
"""Generate a one-row discrete-block color legend.

Reads zone data from the Natural Earth DBF and renders a dark-background
PNG with discrete color blocks, thin separators, and staggered labels.
All tunable values live in config.json.

Usage:
    python3 src/make_legend.py
    python3 src/make_legend.py --width 4096 --height 256
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core import (
    format_offset,
    offset_color,
    read_dbf_zone_values,
    get_config,
    resolve_font,
)


def make_legend(
    zone_values: list[str],
    width: int | None = None,
    height: int | None = None,
    bg_color: tuple[int, int, int] | None = None,
) -> Image.Image:
    """Render discrete-block color legend with staggered labels.

    Args:
        zone_values: Sorted list of zone offset strings.
        width: Canvas width. Default from config.json (2240).
        height: Canvas height. Default from config.json (140).
        bg_color: Background RGB. Default from config.json.

    Returns:
        PIL Image (RGB mode).
    """
    L = get_config()["legend"]
    width = width or L["width"]
    height = height or L["height"]
    bg_color = bg_color or tuple(L["background_rgb"])

    total = len(zone_values)
    scale = width / L["width"]

    block_w = max(L["block_width_base"], round(L["block_width_base"] * scale))
    sep_w = L["separator_width"]
    bar_top = max(L["bar_top_base"], round(L["bar_top_base"] * scale))
    bar_bot = bar_top + max(L["bar_height_base"], round(L["bar_height_base"] * scale)) - 1

    inner_w = total * block_w + (total - 1) * sep_w
    margin = (width - inner_w) // 2

    font = ImageFont.truetype(resolve_font(1), round(L["label_font_size_base"] * max(1, scale)))
    footer_font = ImageFont.truetype(resolve_font(1, style="regular"),
                                      round(L["footer_font_size_base"] * max(1, scale)))

    img = Image.new("RGB", (width, height), bg_color)
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
                img.putpixel((sx, y), tuple(L["separator_rgb"]))

    # Staggered labels
    for i, z in enumerate(zone_values):
        lbl = format_offset(z)
        x_center = margin + i * (block_w + sep_w) + block_w // 2
        bbox = font.getbbox(lbl)
        tw = bbox[2] - bbox[0]

        if i % 2 == 0:
            label_y = max(L["even_label_y_base"], round(L["even_label_y_base"] * scale))
            draw.text((x_center - tw // 2, label_y), lbl, fill=tuple(L["even_label_rgb"]), font=font)
        else:
            row1 = round(L["odd_label_row1_y_base"] * scale)
            row2 = round(L["odd_label_row2_y_base"] * scale)
            ty = row1 if i % 4 == 1 else row2
            draw.text((x_center - tw // 2, ty), lbl, fill=tuple(L["odd_label_rgb"]), font=font)

    # Footer
    fw = footer_font.getbbox(L["footer_text"])[2] - footer_font.getbbox(L["footer_text"])[0]
    footer_y = height - round(L["footer_y_base"] * scale)
    draw.text(((width - fw) // 2, footer_y), L["footer_text"], fill=tuple(L["footer_rgb"]), font=footer_font)

    return img


def main() -> None:
    cfg = get_config()["paths"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, default=Path(cfg["workdir"]))
    parser.add_argument("--output", type=Path, default=Path(cfg["legend_output"]),
                        help="Output path")
    parser.add_argument("--width", type=int, default=None, help="Canvas width")
    parser.add_argument("--height", type=int, default=None, help="Canvas height")
    args = parser.parse_args()

    dbf_path = args.workdir / "ne_10m_time_zones" / "ne_10m_time_zones.dbf"
    if not dbf_path.exists():
        print(f"ERROR: {dbf_path} not found. Run make_raster_overlay.py first.")
        return 1

    zone_values = read_dbf_zone_values(dbf_path)
    print(f"Found {len(zone_values)} unique zone values")

    img = make_legend(zone_values, width=args.width, height=args.height)
    out_path = args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, optimize=True)
    print(f"wrote {out_path} — {img.size[0]}×{img.size[1]}px ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
