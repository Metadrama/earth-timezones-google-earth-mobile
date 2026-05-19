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
import colorsys
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


def read_dbf_records(dbf_path: Path) -> list[dict[str, str]]:
    """Read dBase records for the Natural Earth timezone shapefile."""
    data = dbf_path.read_bytes()
    _version, _year, _month, _day, record_count, header_len, record_len = struct.unpack("<BBBBIHH20x", data[:32])
    fields: list[tuple[str, str, int]] = []
    offset = 32
    while offset < header_len and data[offset] != 0x0D:
        descriptor = data[offset : offset + 32]
        name = descriptor[:11].split(b"\0", 1)[0].decode("ascii")
        field_type = chr(descriptor[11])
        length = descriptor[16]
        fields.append((name, field_type, length))
        offset += 32
    records: list[dict[str, str]] = []
    pos = header_len
    for _ in range(record_count):
        record = data[pos : pos + record_len]
        pos += record_len
        if not record or record[:1] == b"*":
            records.append({})
            continue
        cursor = 1
        values: dict[str, str] = {}
        for name, _field_type, length in fields:
            raw = record[cursor : cursor + length]
            cursor += length
            values[name] = raw.decode("latin1", errors="replace").strip()
        records.append(values)
    return records


def timezone_color(record: dict[str, str], zone_bounds: tuple[float, float] | None = None) -> tuple[int, int, int, int]:
    """Map a timezone's UTC offset to a rainbow hue. Returns RGBA tuple."""
    zone_value = record.get("zone") or record.get("name") or "0"
    try:
        zone = float(zone_value)
    except ValueError:
        zone = 0
    if zone_bounds:
        lo, hi = zone_bounds
    else:
        lo, hi = 5.0, 11.0
    if hi == lo:
        frac = 0.5
    else:
        frac = (zone - lo) / (hi - lo)
    frac = max(0.0, min(1.0, frac))
    hue_deg = 240.0 - frac * 240.0
    r, g, b = colorsys.hsv_to_rgb(hue_deg / 360.0, 0.95, 1.0)
    return (int(r * 255), int(g * 255), int(b * 255), 245)


def render_overlay(
    rings_by_shape: list[list[list[tuple[float, float]]]],
    width: int,
    height: int,
    output_png: Path,
    shape_records: list[dict[str, str]] | None = None,
    zone_bounds: tuple[float, float] | None = None,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Contrast halo: makes borders readable on mixed satellite/terrain imagery.
    # These exact widths match the proven working yellow overlay.
    halo_width = max(2, width // 2048)
    line_width = max(1, width // 4096)

    for shape_index, rings in enumerate(rings_by_shape):
        record = shape_records[shape_index] if shape_records and shape_index < len(shape_records) else {}
        color = timezone_color(record, zone_bounds) if record else (255, 230, 40, 245)
        for ring in rings:
            points = [project(point, width, height) for point in ring]
            if len(points) >= 2:
                draw.line(points, fill=(0, 0, 0, 190), width=halo_width, joint="curve")

    for shape_index, rings in enumerate(rings_by_shape):
        record = shape_records[shape_index] if shape_records and shape_index < len(shape_records) else {}
        color = timezone_color(record, zone_bounds) if record else (255, 230, 40, 245)
        for ring in rings:
            points = [project(point, width, height) for point in ring]
            if len(points) >= 2:
                draw.line(points, fill=color, width=line_width, joint="curve")

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
    shape_records = read_dbf_records(shp_path.with_suffix(".dbf"))

    # Compute zone bounds for spectrum color coding
    zones_found = []
    for rec in shape_records:
        zv = rec.get("zone") or rec.get("name") or ""
        try:
            zones_found.append(float(zv))
        except ValueError:
            pass
    zone_bounds = (min(zones_found), max(zones_found)) if zones_found else None

    built_kmz: list[Path] = []
    for spec in resolutions:
        width, height, label = parse_resolution(spec)
        png_path = args.outdir / f"timezone_borders_raster_{label}.png"
        kmz_path = args.outdir / f"earth_timezones_raster_{label}.kmz"
        render_overlay(rings_by_shape, width, height, png_path, shape_records=shape_records, zone_bounds=zone_bounds)
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
