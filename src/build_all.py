#!/usr/bin/env python3
"""Build everything: overlay KMZ, color legend, and README preview composite.

Single entry point. Run from repo root:

    python3 src/build_all.py

All tunable values live in src/config.json — edit that instead of code.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from core import (
    get_config,
    read_dbf_zone_values,
)
from make_legend import make_legend
from make_raster_overlay import (
    download,
    extract,
    parse_resolution,
    read_dbf_records,
    read_polygon_rings,
    render_overlay,
    write_kmz,
)


def build_all(
    workdir: str | Path,
    outdir: str | Path,
    resolution: str,
    source_url: str,
) -> None:
    cfg = get_config()
    P = cfg["preview"]
    L = cfg["legend"]
    paths = cfg["paths"]

    workdir = Path(workdir)
    outdir = Path(outdir)

    print("=" * 50)
    print("Step 1/3: Downloading Natural Earth data (if needed)...")
    print("=" * 50)
    zip_path = workdir / "ne_10m_time_zones.zip"
    extract_dir = workdir / "ne_10m_time_zones"
    download(source_url, zip_path)
    shp_path = extract(zip_path, extract_dir)

    print("\n" + "=" * 50)
    print("Step 2/3: Rendering overlay PNG + KMZ...")
    print("=" * 50)
    rings_by_shape = read_polygon_rings(shp_path)
    shape_records = read_dbf_records(shp_path.with_suffix(".dbf"))
    unique_zones = read_dbf_zone_values(shp_path.with_suffix(".dbf"))
    zone_index_map = {z: i for i, z in enumerate(unique_zones)} if unique_zones else None
    total_zones = len(unique_zones) if unique_zones else 40

    width, height, label = parse_resolution(resolution)
    png_path = outdir / f"timezone_borders_raster_{label}.png"
    kmz_path = outdir / f"earth_timezones_raster_{label}.kmz"

    render_overlay(rings_by_shape, width, height, png_path,
                   shape_records=shape_records, zone_index_map=zone_index_map,
                   total_zones=total_zones)
    write_kmz(kmz_path, png_path)
    print(f"  KMZ: {kmz_path} ({kmz_path.stat().st_size} bytes)")

    print("\n" + "=" * 50)
    print("Step 3/3: Generating legend + README composite...")
    print("=" * 50)

    # Legend (default config size)
    zone_values = read_dbf_zone_values(shp_path.with_suffix(".dbf"))
    print(f"  Zones: {len(zone_values)} unique offsets")
    legend_img = make_legend(zone_values, bg_color=tuple(L["background_rgb"]))
    legend_path = Path(paths["legend_output"])
    legend_path.parent.mkdir(parents=True, exist_ok=True)
    legend_img.save(legend_path, optimize=True)
    print(f"  Legend: {legend_path} ({legend_path.stat().st_size} bytes)")

    # Composite (legend auto-sized to overlay width)
    overlay = Image.open(png_path).convert("RGBA")
    o_w, o_h = overlay.size
    bg = Image.new("RGBA", overlay.size, (*P["overlay_background_rgb"], 255))
    map_img = Image.alpha_composite(bg, overlay).convert("RGB")

    l_height = max(140, round(140 * o_w / 2240.0))
    legend_full = make_legend(zone_values, width=o_w, height=l_height,
                              bg_color=tuple(P["legend_background_rgb"])).convert("RGB")
    l_h = legend_full.size[1]

    final_w = o_w
    final_h = o_h + P["gap"] + l_h
    canvas = Image.new("RGB", (final_w, final_h), tuple(P["legend_background_rgb"]))
    canvas.paste(map_img, (0, 0))
    canvas.paste(legend_full, (0, o_h + P["gap"]))

    composite_path = Path(paths["preview_output"])
    composite_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(composite_path, optimize=True, quality=P["quality"])
    print(f"  Composite: {composite_path} ({composite_path.stat().st_size} bytes)")

    print("\n[OK] All done. Files:")
    print(f"   {kmz_path}")
    print(f"   {png_path}")
    print(f"   {legend_path}")
    print(f"   {composite_path}")


def main() -> None:
    cfg = get_config()["paths"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, default=Path(cfg["workdir"]))
    parser.add_argument("--outdir", type=Path, default=Path(cfg["overlay_outdir"]))
    parser.add_argument("--resolution", default=cfg["default_resolution"])
    parser.add_argument("--source-url", default=cfg["natural_earth_url"])
    args = parser.parse_args()
    build_all(
        workdir=args.workdir, outdir=args.outdir,
        resolution=args.resolution, source_url=args.source_url,
    )


if __name__ == "__main__":
    main()
