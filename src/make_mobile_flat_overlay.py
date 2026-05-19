#!/usr/bin/env python3
"""Build Google Earth Mobile-compatible flat tiled timezone overlay KMZs.

Google Earth Mobile rejects KML SuperOverlay plumbing on some builds with:
"Unsupported element: NetworkLink" and "Unsupported element: Region".

This generator deliberately emits only a single doc.kml containing many simple
GroundOverlay elements. No NetworkLink. No Region. No Lod. The tradeoff is that
all overlays in the pack are loaded together, so use this for regional packs or
modest global zooms instead of a full global z8 pyramid.
"""

from __future__ import annotations

import argparse
import shutil
import zipfile
from collections import defaultdict
from pathlib import Path

from make_tiled_overlay import (
    NATURAL_EARTH_URL,
    Tile,
    candidate_segments_by_tile,
    download,
    extract,
    read_polygon_rings,
    render_tile,
    tile_bounds,
)


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    """Parse west,south,east,north."""
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be west,south,east,north")
    west, south, east, north = parts
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise argparse.ArgumentTypeError("bbox must satisfy -180 <= west < east <= 180 and -90 <= south < north <= 90")
    return west, south, east, north


def intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    aw, a_s, ae, an = a
    bw, b_s, be, bn = b
    return not (ae <= bw or be <= aw or an <= b_s or bn <= a_s)


def write_flat_doc_kml(
    out_dir: Path,
    png_tiles: list[Tile],
    name: str,
    description: str,
) -> None:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Document>',
        f'  <name>{escape_xml(name)}</name>',
        f'  <description>{escape_xml(description)}</description>',
    ]

    for tile in sorted(png_tiles):
        west, south, east, north = tile_bounds(tile)
        href = f"tiles/{tile.z}/{tile.x}/{tile.y}.png"
        parts.append(f"""  <GroundOverlay>
    <name>Timezone borders z{tile.z}/{tile.x}/{tile.y}</name>
    <Icon><href>{href}</href></Icon>
    <LatLonBox>
      <north>{north:.10f}</north>
      <south>{south:.10f}</south>
      <east>{east:.10f}</east>
      <west>{west:.10f}</west>
    </LatLonBox>
  </GroundOverlay>""")

    parts.extend(['</Document>', '</kml>'])
    (out_dir / "doc.kml").write_text("\n".join(parts) + "\n", encoding="utf-8")


def escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def package_kmz(source_dir: Path, output_kmz: Path) -> None:
    output_kmz.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir).as_posix())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", default=NATURAL_EARTH_URL)
    parser.add_argument("--workdir", type=Path, default=Path("build/natural-earth"))
    parser.add_argument("--outdir", type=Path, default=Path("dist/mobile-flat-se-asia"))
    parser.add_argument("--kmz", type=Path, default=Path("dist/earth_timezones_mobile_flat_se_asia_z8.kmz"))
    parser.add_argument("--max-zoom", type=int, default=8)
    parser.add_argument("--tile-size", type=int, default=512)
    parser.add_argument(
        "--bbox",
        type=parse_bbox,
        default=parse_bbox("90,-15,145,25"),
        help="west,south,east,north. Default covers Southeast Asia.",
    )
    parser.add_argument("--name", default="Earth timezone borders - mobile flat Southeast Asia")
    args = parser.parse_args()

    zip_path = args.workdir / "ne_10m_time_zones.zip"
    extract_dir = args.workdir / "ne_10m_time_zones"
    download(args.source_url, zip_path)
    shp_path = extract(zip_path, extract_dir)
    rings = read_polygon_rings(shp_path)

    print(f"rings: {len(rings)}")
    segments_by_tile = candidate_segments_by_tile(rings, args.max_zoom)
    bbox = args.bbox
    candidate_tiles = sorted(
        tile
        for tile in segments_by_tile
        if tile.z == args.max_zoom and intersects(tile_bounds(tile), bbox)
    )
    print(f"candidate z{args.max_zoom} tiles in bbox: {len(candidate_tiles)}")

    if args.outdir.exists():
        shutil.rmtree(args.outdir)
    args.outdir.mkdir(parents=True, exist_ok=True)

    png_tiles: list[Tile] = []
    tile_dir = args.outdir / "tiles"
    for tile in candidate_tiles:
        png_path = tile_dir / str(tile.z) / str(tile.x) / f"{tile.y}.png"
        if render_tile(tile, segments_by_tile.get(tile, []), args.tile_size, png_path):
            png_tiles.append(tile)

    west, south, east, north = bbox
    description = (
        "Google Earth Mobile-compatible flat raster tile pack. "
        "Uses only simple raster overlays with geographic boxes. "
        f"Bounds: west={west}, south={south}, east={east}, north={north}. "
        f"Zoom={args.max_zoom}, tile_size={args.tile_size}px."
    )
    write_flat_doc_kml(args.outdir, png_tiles, args.name, description)
    package_kmz(args.outdir, args.kmz)

    total_png = sum(p.stat().st_size for p in tile_dir.rglob("*.png"))
    total_kml = (args.outdir / "doc.kml").stat().st_size
    print(f"png tiles: {len(png_tiles)}, png bytes: {total_png}")
    print(f"doc.kml bytes: {total_kml}")
    print(f"wrote {args.kmz} ({args.kmz.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
