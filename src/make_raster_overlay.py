#!/usr/bin/env python3
"""Build Google Earth Mobile-friendly timezone border KMZ overlays.

Downloads Natural Earth's public-domain timezone shapefile, renders the
polygon rings into transparent PNG rasters, and packages as KML GroundOverlay
inside a KMZ archive.

Usage:
    python3 src/make_raster_overlay.py --resolution "4k:4096x2048"
"""

from __future__ import annotations

import argparse
import struct
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from core import (
    COLOR_ALPHA,
    FALLBACK_COLOR,
    HALO_COLOR,
    HALO_FACTOR,
    JOINT,
    LINE_FACTOR,
    NATURAL_EARTH_URL,
    get_config,
    make_kml,
    offset_color,
    read_dbf_zone_values,
)


# ── shapefile I/O ────────────────────────────────────────────────────────


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
    data = shp_path.read_bytes()
    pos = 100
    shapes: list[list[list[tuple[float, float]]]] = []

    while pos < len(data):
        _record_number, content_words = struct.unpack(">2i", data[pos: pos + 8])
        pos += 8
        content = data[pos: pos + content_words * 2]
        pos += content_words * 2

        shape_type = struct.unpack("<i", content[:4])[0]
        if shape_type not in (5, 15, 25):
            shapes.append([])
            continue

        num_parts, num_points = struct.unpack("<2i", content[36:44])
        parts = list(struct.unpack(f"<{num_parts}i", content[44: 44 + 4 * num_parts]))
        points_offset = 44 + 4 * num_parts
        points = [
            struct.unpack("<2d", content[points_offset + i * 16: points_offset + i * 16 + 16])
            for i in range(num_points)
        ]

        rings: list[list[tuple[float, float]]] = []
        for i, start in enumerate(parts):
            end = parts[i + 1] if i + 1 < len(parts) else num_points
            rings.append(points[start:end])
        shapes.append(rings)

    return shapes


def read_dbf_records(dbf_path: Path) -> list[dict[str, str]]:
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

    records: list[dict[str, str]] = []
    pos = header_len
    for _ in range(record_count):
        record = data[pos: pos + record_len]
        pos += record_len
        if not record or record[:1] == b"*":
            records.append({})
            continue
        cursor = 1
        values: dict[str, str] = {}
        for name, _ft, length in fields:
            raw = record[cursor: cursor + length]
            cursor += length
            values[name] = raw.decode("latin1", errors="replace").strip()
        records.append(values)
    return records


# ── rendering ────────────────────────────────────────────────────────────


def project(lon_lat: tuple[float, float], width: int, height: int) -> tuple[int, int]:
    lon, lat = lon_lat
    x = (lon + 180.0) / 360.0 * (width - 1)
    y = (90.0 - lat) / 180.0 * (height - 1)
    return int(round(x)), int(round(y))


def timezone_color(
    record: dict[str, str],
    zone_index_map: dict[str, int] | None = None,
    total_zones: int = 40,
) -> tuple[int, int, int, int]:
    zone_value = record.get("zone") or record.get("name") or "0"
    if zone_index_map and zone_value in zone_index_map:
        idx = zone_index_map[zone_value]
    else:
        try:
            zone = float(zone_value)
        except ValueError:
            zone = 0
        lo, hi = -12.0, 14.0
        frac = (zone - lo) / (hi - lo)
        idx = round(frac * (total_zones - 1))

    r, g, b = offset_color(idx, total_zones)
    return (r, g, b, COLOR_ALPHA)


def render_overlay(
    rings_by_shape: list[list[list[tuple[float, float]]]],
    width: int,
    height: int,
    output_png: Path,
    shape_records: list[dict[str, str]] | None = None,
    zone_index_map: dict[str, int] | None = None,
    total_zones: int = 40,
) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    halo_width = max(2, width // HALO_FACTOR)
    line_width = max(1, width // LINE_FACTOR)

    # Pass 1: black halo
    for shape_index, rings in enumerate(rings_by_shape):
        record = shape_records[shape_index] if shape_records and shape_index < len(shape_records) else {}
        for ring in rings:
            points = [project(point, width, height) for point in ring]
            if len(points) >= 2:
                draw.line(points, fill=HALO_COLOR, width=halo_width, joint=JOINT)

    # Pass 2: coloured core
    for shape_index, rings in enumerate(rings_by_shape):
        record = shape_records[shape_index] if shape_records and shape_index < len(shape_records) else {}
        color = timezone_color(record, zone_index_map, total_zones) if record else FALLBACK_COLOR
        for ring in rings:
            points = [project(point, width, height) for point in ring]
            if len(points) >= 2:
                draw.line(points, fill=color, width=line_width, joint=JOINT)

    image.save(output_png, optimize=True)


def write_kmz(output_kmz: Path, png_path: Path) -> None:
    output_kmz.parent.mkdir(parents=True, exist_ok=True)
    kml = make_kml(png_path.name)
    with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml", kml)
        archive.write(png_path, f"files/{png_path.name}")


def parse_resolution(value: str) -> tuple[int, int, str]:
    label, dims = value.split(":", 1) if ":" in value else (value, value)
    width_s, height_s = dims.lower().split("x", 1)
    return int(width_s), int(height_s), label


# ── CLI ──────────────────────────────────────────────────────────────────


def main() -> None:
    cfg = get_config()["paths"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", default=NATURAL_EARTH_URL)
    parser.add_argument("--workdir", type=Path, default=Path(cfg["workdir"]))
    parser.add_argument("--outdir", type=Path, default=Path(cfg["overlay_outdir"]))
    parser.add_argument("--resolution", action="append", default=None,
                        help="Label and size, e.g. 4k:4096x2048")
    args = parser.parse_args()
    resolutions = args.resolution or [cfg["default_resolution"]]

    zip_path = args.workdir / "ne_10m_time_zones.zip"
    extract_dir = args.workdir / "ne_10m_time_zones"
    download(args.source_url, zip_path)
    shp_path = extract(zip_path, extract_dir)
    rings_by_shape = read_polygon_rings(shp_path)
    shape_records = read_dbf_records(shp_path.with_suffix(".dbf"))
    unique_zones = read_dbf_zone_values(shp_path.with_suffix(".dbf"))
    zone_index_map = {z: i for i, z in enumerate(unique_zones)} if unique_zones else None
    total_zones = len(unique_zones) if unique_zones else 40

    for spec in resolutions:
        width, height, label = parse_resolution(spec)
        png_path = args.outdir / f"timezone_borders_raster_{label}.png"
        kmz_path = args.outdir / f"earth_timezones_raster_{label}.kmz"
        render_overlay(rings_by_shape, width, height, png_path,
                       shape_records=shape_records, zone_index_map=zone_index_map,
                       total_zones=total_zones)
        write_kmz(kmz_path, png_path)
        print(f"wrote {kmz_path} ({kmz_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
