#!/usr/bin/env python3
"""Build Google Earth Mobile-friendly timezone border KMZ overlays.

This script downloads Natural Earth's public-domain timezone shapefile,
renders the polygon rings into transparent PNG rasters, and packages those
rasters as KML/KMZ GroundOverlays.

Why raster? Google Earth Mobile can lag badly on polygon-heavy KML feature
layers. A GroundOverlay is one georeferenced texture instead of hundreds of
interactive vector features.
"""

from __future__ import annotations

import argparse
import struct
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

NATURAL_EARTH_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_time_zones.zip"


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


def read_polygon_rings(shp_path: Path) -> list[list[list[tuple[float, float]]]]:
    """Read polygon rings from an ESRI Shapefile without GDAL/Fiona.

    Supports the polygon record shape used by Natural Earth's timezone layer.
    Returns: list of shapes, each shape is a list of rings, each ring is
    [(lon, lat), ...].
    """
    data = shp_path.read_bytes()
    pos = 100  # fixed-size shapefile header
    shapes: list[list[list[tuple[float, float]]]] = []

    while pos < len(data):
        _record_number, content_words = struct.unpack(">2i", data[pos : pos + 8])
        pos += 8
        content = data[pos : pos + content_words * 2]
        pos += content_words * 2

        shape_type = struct.unpack("<i", content[:4])[0]
        if shape_type not in (5, 15, 25):  # Polygon, PolygonZ, PolygonM
            shapes.append([])
            continue

        num_parts, num_points = struct.unpack("<2i", content[36:44])
        parts = list(struct.unpack(f"<{num_parts}i", content[44 : 44 + 4 * num_parts]))
        points_offset = 44 + 4 * num_parts
        points = [
            struct.unpack("<2d", content[points_offset + i * 16 : points_offset + i * 16 + 16])
            for i in range(num_points)
        ]

        rings: list[list[tuple[float, float]]] = []
        for i, start in enumerate(parts):
            end = parts[i + 1] if i + 1 < len(parts) else num_points
            rings.append(points[start:end])
        shapes.append(rings)

    return shapes


def project(lon_lat: tuple[float, float], width: int, height: int) -> tuple[int, int]:
    lon, lat = lon_lat
    x = (lon + 180.0) / 360.0 * (width - 1)
    y = (90.0 - lat) / 180.0 * (height - 1)
    return int(round(x)), int(round(y))


def render_overlay(
    rings_by_shape: list[list[list[tuple[float, float]]]],
    width: int,
    height: int,
    output_png: Path,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Contrast halo: makes borders readable on mixed satellite/terrain imagery.
    halo_width = max(2, width // 2048)
    line_width = max(1, width // 4096)

    for rings in rings_by_shape:
        for ring in rings:
            points = [project(point, width, height) for point in ring]
            if len(points) >= 2:
                draw.line(points, fill=(0, 0, 0, 190), width=halo_width, joint="curve")

    for rings in rings_by_shape:
        for ring in rings:
            points = [project(point, width, height) for point in ring]
            if len(points) >= 2:
                draw.line(points, fill=(255, 230, 40, 245), width=line_width, joint="curve")

    image.save(output_png, optimize=True)


def write_kmz(output_kmz: Path, png_path: Path) -> None:
    output_kmz.parent.mkdir(parents=True, exist_ok=True)
    kml = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>Earth timezone borders raster overlay</name>
  <description>Rasterized Natural Earth timezone borders. Accurate visual overlay, no vector features, designed to avoid Google Earth Mobile vector lag.</description>
  <GroundOverlay>
    <name>Timezone borders</name>
    <Icon><href>files/{png_path.name}</href></Icon>
    <LatLonBox>
      <north>90</north>
      <south>-90</south>
      <east>180</east>
      <west>-180</west>
    </LatLonBox>
  </GroundOverlay>
</Document>
</kml>
'''
    with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml", kml)
        archive.write(png_path, f"files/{png_path.name}")


def parse_resolution(value: str) -> tuple[int, int, str]:
    label, dims = value.split(":", 1) if ":" in value else (value, value)
    width_s, height_s = dims.lower().split("x", 1)
    return int(width_s), int(height_s), label


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", default=NATURAL_EARTH_URL)
    parser.add_argument("--workdir", type=Path, default=Path("build/natural-earth"))
    parser.add_argument("--outdir", type=Path, default=Path("dist"))
    parser.add_argument(
        "--resolution",
        action="append",
        default=None,
        help="Label and image size, e.g. 4k:4096x2048. Can be repeated. Defaults to 4K and 8K.",
    )
    args = parser.parse_args()
    resolutions = args.resolution or ["4k:4096x2048", "8k:8192x4096"]

    zip_path = args.workdir / "ne_10m_time_zones.zip"
    extract_dir = args.workdir / "ne_10m_time_zones"
    download(args.source_url, zip_path)
    shp_path = extract(zip_path, extract_dir)
    rings_by_shape = read_polygon_rings(shp_path)

    built_kmz: list[Path] = []
    for spec in resolutions:
        width, height, label = parse_resolution(spec)
        png_path = args.outdir / f"timezone_borders_raster_{label}.png"
        kmz_path = args.outdir / f"earth_timezones_raster_{label}.kmz"
        render_overlay(rings_by_shape, width, height, png_path)
        write_kmz(kmz_path, png_path)
        built_kmz.append(kmz_path)
        print(f"wrote {kmz_path} ({kmz_path.stat().st_size} bytes)")

    bundle = args.outdir / "earth_timezones_raster_overlays.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for kmz_path in built_kmz:
            archive.write(kmz_path, kmz_path.name)
    print(f"wrote {bundle} ({bundle.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
