#!/usr/bin/env python3
"""Build a tiled Google Earth timezone border SuperOverlay.

This is the mobile-friendly v2 architecture: instead of one global high-res
image or thousands of vector polygon features, generate many small raster
GroundOverlay tiles and connect them with KML Region/LOD NetworkLinks.

Google Earth should load only the KML/PNG tiles near the camera.
"""

from __future__ import annotations

import argparse
import math
import struct
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

NATURAL_EARTH_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_time_zones.zip"


@dataclass(frozen=True, order=True)
class Tile:
    z: int
    x: int
    y: int


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 0:
        return
    print(f"Downloading {url}")
    urllib.request.urlretrieve(url, target)


def extract(zip_path: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    shp = target_dir / "ne_10m_time_zones.shp"
    if shp.exists():
        return shp
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(target_dir)
    return shp


def read_polygon_rings(shp_path: Path) -> list[list[tuple[float, float]]]:
    """Read all polygon rings from Natural Earth's timezone shapefile."""
    data = shp_path.read_bytes()
    pos = 100
    rings: list[list[tuple[float, float]]] = []

    while pos < len(data):
        _record_number, content_words = struct.unpack(">2i", data[pos : pos + 8])
        pos += 8
        content = data[pos : pos + content_words * 2]
        pos += content_words * 2

        shape_type = struct.unpack("<i", content[:4])[0]
        if shape_type not in (5, 15, 25):
            continue

        num_parts, num_points = struct.unpack("<2i", content[36:44])
        parts = list(struct.unpack(f"<{num_parts}i", content[44 : 44 + 4 * num_parts]))
        points_offset = 44 + 4 * num_parts
        points = [
            struct.unpack("<2d", content[points_offset + i * 16 : points_offset + i * 16 + 16])
            for i in range(num_points)
        ]

        for i, start in enumerate(parts):
            end = parts[i + 1] if i + 1 < len(parts) else num_points
            ring = points[start:end]
            if len(ring) >= 2:
                rings.append(ring)

    return rings


def tile_count(z: int) -> int:
    return 1 << z


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = tile_count(z)
    # Clamp to valid world extent. lon=180/lat=-90 sit exactly on the edge.
    lon = min(179.999999, max(-180.0, lon))
    lat = min(89.999999, max(-90.0, lat))
    x = int((lon + 180.0) / 360.0 * n)
    y = int((90.0 - lat) / 180.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def tile_bounds(tile: Tile) -> tuple[float, float, float, float]:
    """Return west, south, east, north."""
    n = tile_count(tile.z)
    west = -180.0 + tile.x * 360.0 / n
    east = -180.0 + (tile.x + 1) * 360.0 / n
    north = 90.0 - tile.y * 180.0 / n
    south = 90.0 - (tile.y + 1) * 180.0 / n
    return west, south, east, north


def project(point: tuple[float, float], bounds: tuple[float, float, float, float], size: int) -> tuple[int, int]:
    lon, lat = point
    west, south, east, north = bounds
    x = (lon - west) / (east - west) * (size - 1)
    y = (north - lat) / (north - south) * (size - 1)
    return int(round(x)), int(round(y))


def bbox_intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    aw, a_s, ae, an = a
    bw, b_s, be, bn = b
    return not (ae < bw or be < aw or an < b_s or bn < a_s)


def ring_bbox(ring: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return min(lons), min(lats), max(lons), max(lats)


def candidate_segments_by_tile(
    rings: list[list[tuple[float, float]]], max_zoom: int
) -> dict[Tile, list[tuple[tuple[float, float], tuple[float, float]]]]:
    """Map each touched tile to only the line segments it needs to draw.

    This is much faster than checking/drawing whole polygon rings for every
    tile. It also avoids huge false positives from large polygon bounding boxes.
    """
    segments_by_tile: dict[Tile, list[tuple[tuple[float, float], tuple[float, float]]]] = defaultdict(list)
    for ring in rings:
        for a, b in zip(ring, ring[1:]):
            lon1, lat1 = a
            lon2, lat2 = b
            if abs(lon2 - lon1) > 180:
                # Avoid turning antimeridian jumps into a line across the world.
                continue
            min_lon, max_lon = sorted((lon1, lon2))
            min_lat, max_lat = sorted((lat1, lat2))
            for z in range(max_zoom + 1):
                n = tile_count(z)
                x1, y1 = lonlat_to_tile(min_lon, max_lat, z)
                x2, y2 = lonlat_to_tile(max_lon, min_lat, z)
                for x in range(max(0, x1 - 1), min(n - 1, x2 + 1) + 1):
                    for y in range(max(0, y1 - 1), min(n - 1, y2 + 1) + 1):
                        segments_by_tile[Tile(z, x, y)].append((a, b))
    return segments_by_tile


def tiles_with_ancestors(tiles: set[Tile]) -> set[Tile]:
    keep: set[Tile] = {Tile(0, 0, 0)}
    for tile in tiles:
        t = tile
        while True:
            keep.add(t)
            if t.z == 0:
                break
            t = Tile(t.z - 1, t.x // 2, t.y // 2)
    return keep


def render_tile(
    tile: Tile,
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
    size: int,
    out_png: Path,
) -> bool:
    bounds = tile_bounds(tile)
    if not segments:
        return False

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    for a, b in segments:
        pts = [project(a, bounds, size), project(b, bounds, size)]
        draw.line(pts, fill=(0, 0, 0, 190), width=3)
    for a, b in segments:
        pts = [project(a, bounds, size), project(b, bounds, size)]
        draw.line(pts, fill=(255, 230, 40, 245), width=1)

    if image.getbbox() is None:
        return False

    out_png.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_png, optimize=True)
    return True


def region_xml(tile: Tile, min_lod: int, max_lod: int = -1) -> str:
    west, south, east, north = tile_bounds(tile)
    return f"""<Region>
  <LatLonAltBox><north>{north:.10f}</north><south>{south:.10f}</south><east>{east:.10f}</east><west>{west:.10f}</west></LatLonAltBox>
  <Lod><minLodPixels>{min_lod}</minLodPixels><maxLodPixels>{max_lod}</maxLodPixels></Lod>
</Region>"""


def child_tiles(tile: Tile) -> list[Tile]:
    z = tile.z + 1
    return [
        Tile(z, tile.x * 2, tile.y * 2),
        Tile(z, tile.x * 2 + 1, tile.y * 2),
        Tile(z, tile.x * 2, tile.y * 2 + 1),
        Tile(z, tile.x * 2 + 1, tile.y * 2 + 1),
    ]


def write_tile_kml(
    tile: Tile,
    has_png: bool,
    keep: set[Tile],
    max_zoom: int,
    tile_dir: Path,
    tile_size: int,
) -> None:
    href_base = f"{tile.z}/{tile.x}/{tile.y}"
    parts = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "<kml xmlns=\"http://www.opengis.net/kml/2.2\"><Document>"]
    parts.append(f"<name>Timezone tile z{tile.z} x{tile.x} y{tile.y}</name>")
    parts.append(region_xml(tile, 64 if tile.z == 0 else 128))

    if has_png:
        west, south, east, north = tile_bounds(tile)
        overlay_max_lod = -1 if tile.z == max_zoom else 512
        parts.append(f"""<GroundOverlay>
  <name>Timezone borders z{tile.z}/{tile.x}/{tile.y}</name>
  {region_xml(tile, 0, overlay_max_lod)}
  <Icon><href>{tile.y}.png</href></Icon>
  <LatLonBox><north>{north:.10f}</north><south>{south:.10f}</south><east>{east:.10f}</east><west>{west:.10f}</west></LatLonBox>
</GroundOverlay>""")

    if tile.z < max_zoom:
        for child in child_tiles(tile):
            if child not in keep:
                continue
            rel = f"../../{child.z}/{child.x}/{child.y}.kml"
            parts.append(f"""<NetworkLink>
  <name>z{child.z}/{child.x}/{child.y}</name>
  {region_xml(child, 128)}
  <Link><href>{rel}</href><viewRefreshMode>onRegion</viewRefreshMode></Link>
</NetworkLink>""")

    parts.append("</Document></kml>")
    kml_path = tile_dir / str(tile.z) / str(tile.x) / f"{tile.y}.kml"
    kml_path.parent.mkdir(parents=True, exist_ok=True)
    kml_path.write_text("\n".join(parts), encoding="utf-8")


def write_root_kml(out_dir: Path, max_zoom: int, tile_size: int) -> None:
    root = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>Earth timezone borders tiled overlay</name>
  <description>Rasterized Natural Earth timezone borders as KML Region/LOD tiles. Designed for Google Earth Mobile.</description>
  <NetworkLink>
    <name>Timezone overlay root</name>
    {region_xml(Tile(0, 0, 0), 1)}
    <Link><href>tiles/0/0/0.kml</href><viewRefreshMode>onRegion</viewRefreshMode></Link>
  </NetworkLink>
</Document>
</kml>
'''
    (out_dir / "doc.kml").write_text(root, encoding="utf-8")


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
    parser.add_argument("--outdir", type=Path, default=Path("dist/tiled-superoverlay"))
    parser.add_argument("--kmz", type=Path, default=Path("dist/earth_timezones_tiled_superoverlay_z8.kmz"))
    parser.add_argument("--max-zoom", type=int, default=8)
    parser.add_argument("--tile-size", type=int, default=512)
    args = parser.parse_args()

    zip_path = args.workdir / "ne_10m_time_zones.zip"
    extract_dir = args.workdir / "ne_10m_time_zones"
    download(args.source_url, zip_path)
    shp_path = extract(zip_path, extract_dir)
    rings = read_polygon_rings(shp_path)

    print(f"rings: {len(rings)}")
    segments_by_tile = candidate_segments_by_tile(rings, args.max_zoom)
    keep = tiles_with_ancestors(set(segments_by_tile))
    print(f"segment tiles: {len(segments_by_tile)}")
    print(f"candidate/ancestor KML tiles: {len(keep)}")

    if args.outdir.exists():
        # Only remove generated tile tree files, not dist itself.
        import shutil
        shutil.rmtree(args.outdir)
    args.outdir.mkdir(parents=True, exist_ok=True)
    tile_dir = args.outdir / "tiles"

    has_png: set[Tile] = set()
    by_zoom: dict[int, list[Tile]] = defaultdict(list)
    for tile in keep:
        by_zoom[tile.z].append(tile)

    for z in range(args.max_zoom + 1):
        tiles = sorted(by_zoom.get(z, []))
        rendered = 0
        for tile in tiles:
            png_path = tile_dir / str(tile.z) / str(tile.x) / f"{tile.y}.png"
            if render_tile(tile, segments_by_tile.get(tile, []), args.tile_size, png_path):
                has_png.add(tile)
                rendered += 1
        print(f"z{z}: {len(tiles)} KML tiles, {rendered} PNG overlays")

    for tile in sorted(keep):
        write_tile_kml(tile, tile in has_png, keep, args.max_zoom, tile_dir, args.tile_size)
    write_root_kml(args.outdir, args.max_zoom, args.tile_size)
    package_kmz(args.outdir, args.kmz)

    total_png = sum(p.stat().st_size for p in tile_dir.rglob("*.png"))
    total_kml = sum(p.stat().st_size for p in args.outdir.rglob("*.kml"))
    print(f"png tiles: {len(has_png)}, png bytes: {total_png}")
    print(f"kml files: {len(list(args.outdir.rglob('*.kml')))}, kml bytes: {total_kml}")
    print(f"wrote {args.kmz} ({args.kmz.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
