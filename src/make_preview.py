#!/usr/bin/env python3
"""Composite the timezone overlay with the color legend into a single preview image.

Generates the legend at the same width as the overlay so it spans edge-to-edge.

Usage:
    python3 src/make_preview.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from core import (
    read_dbf_zone_values,
    get_config,
)
from make_legend import make_legend


def composite_preview(
    overlay_path: str | Path,
    dbf_path: str | Path,
    output_path: str | Path,
) -> None:
    cfg = get_config()
    P = cfg["preview"]
    paths = cfg["paths"]

    overlay_path = Path(overlay_path)
    overlay = Image.open(overlay_path).convert("RGBA")
    o_w, o_h = overlay.size

    bg = Image.new("RGBA", overlay.size, (*P["overlay_background_rgb"], 255))
    map_img = Image.alpha_composite(bg, overlay).convert("RGB")

    # Legend at overlay width
    zone_values = read_dbf_zone_values(Path(dbf_path))
    l_height = max(140, round(140 * o_w / 2240.0))
    legend_img = make_legend(
        zone_values, width=o_w, height=l_height,
        bg_color=tuple(P["legend_background_rgb"]),
    ).convert("RGB")
    l_h = legend_img.size[1]

    final_w = o_w
    final_h = o_h + P["gap"] + l_h
    canvas = Image.new("RGB", (final_w, final_h), tuple(P["legend_background_rgb"]))
    canvas.paste(map_img, (0, 0))
    canvas.paste(legend_img, (0, o_h + P["gap"]))

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, optimize=True, quality=P["quality"])
    print(f"wrote {out_path} — {final_w}×{final_h}px ({out_path.stat().st_size} bytes)")


def main() -> None:
    cfg = get_config()["paths"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay", type=Path, default=Path(cfg["default_overlay_png"]))
    parser.add_argument("--dbf", type=Path, default=Path(cfg["default_dbf"]))
    parser.add_argument("--output", type=Path, default=Path(cfg["preview_output"]))
    args = parser.parse_args()
    composite_preview(overlay_path=args.overlay, dbf_path=args.dbf, output_path=args.output)


if __name__ == "__main__":
    main()
