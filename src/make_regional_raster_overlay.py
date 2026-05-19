#!/usr/bin/env python3
"""Build one-image regional Google Earth Mobile timezone overlay KMZs.

This is the strictest compatibility fallback for Google Earth Mobile:
- one doc.kml
- one GroundOverlay
- one PNG image
- no NetworkLink / Region / Lod
- no many-image tile pack, avoiding the mobile max external image limit
"""

from __future__ import annotations

import argparse
import colorsys
import struct
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from make_raster_overlay import NATURAL_EARTH_URL, download, extract, read_polygon_rings

CYAN = (80, 255, 255, 255)
MAGENTA = (255, 60, 255, 255)
CYAN_GLOW = (80, 255, 255, 95)
MAGENTA_GLOW = (255, 60, 255, 95)
SHADOW = (0, 0, 0, 215)


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [float(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be west,south,east,north")
    west, south, east, north = parts
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise argparse.ArgumentTypeError("bbox must satisfy -180 <= west < east <= 180 and -90 <= south < north <= 90")
    return west, south, east, north


def project(point: tuple[float, float], bbox: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int]:
    lon, lat = point
    west, south, east, north = bbox
    x = (lon - west) / (east - west) * (width - 1)
    y = (north - lat) / (north - south) * (height - 1)
    return int(round(x)), int(round(y))


def segment_intersects_bbox(a: tuple[float, float], b: tuple[float, float], bbox: tuple[float, float, float, float]) -> bool:
    west, south, east, north = bbox
    min_lon, max_lon = sorted((a[0], b[0]))
    min_lat, max_lat = sorted((a[1], b[1]))
    return not (max_lon < west or min_lon > east or max_lat < south or min_lat > north)


def read_dbf_records(dbf_path: Path) -> list[dict[str, str]]:
    """Read dBase records for the Natural Earth timezone shapefile.

    This tiny parser keeps the build dependency-free. The shapefile and DBF
    records share order, so the Nth shape gets the Nth metadata record.
    """
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


def timezone_color(record: dict[str, str], scheme: str = "spectrum", zone_bounds: tuple[float, float] | None = None) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """Return core/glow RGBA colors for a timezone.

    Keywords:
      "spectrum" — maps UTC offset to a rainbow hue (blue→cyan→green→yellow→orange→red).
                   Intuitive: the color tells the offset without a label.
      "neon"     — two-color alternation (cyan/magenta), used in v0.1.
    """
    zone_value = record.get("zone") or record.get("name") or "0"
    try:
        zone = float(zone_value)
    except ValueError:
        zone = 0

    if scheme == "spectrum":
        if zone_bounds:
            lo, hi = zone_bounds
        else:
            lo, hi = 5.0, 11.0  # SE Asia default
        if hi == lo:
            frac = 0.5
        else:
            frac = (zone - lo) / (hi - lo)
        frac = max(0.0, min(1.0, frac))

        # Hue goes 240° (blue) → 0° (red), spanning blue→cyan→green→yellow→orange→red
        hue_deg = 240.0 - frac * 240.0
        r, g, b = colorsys.hsv_to_rgb(hue_deg / 360.0, 0.95, 1.0)
        core = (int(r * 255), int(g * 255), int(b * 255), 255)
        glow = (int(r * 255), int(g * 255), int(b * 255), 95)
        return core, glow

    # Fallback: neon alternation (original behaviour)
    half_hour_step = round(float(zone_value) * 2)
    if half_hour_step % 2 == 0:
        return CYAN, CYAN_GLOW
    return MAGENTA, MAGENTA_GLOW


def render_region(
    rings_by_shape: list[list[list[tuple[float, float]]]],
    shape_records: list[dict[str, str]],
    bbox: tuple[float, float, float, float],
    width: int,
    height: int,
    output_png: Path,
    color_scheme: str = "spectrum",
    zone_bounds: tuple[float, float] | None = None,
) -> int:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Thicker than previous yellow linework: visibility matters more than tiny
    # geometry precision on satellite/mobile basemaps.
    halo_width = max(4, width // 1024)
    glow_width = max(3, width // 1365)
    line_width = max(2, width // 2048)
    drawn = 0

    projected_segments: list[
        tuple[tuple[int, int], tuple[int, int], tuple[int, int, int, int], tuple[int, int, int, int]]
    ] = []
    for shape_index, rings in enumerate(rings_by_shape):
        record = shape_records[shape_index] if shape_index < len(shape_records) else {}
        core_color, glow_color = timezone_color(record, scheme=color_scheme, zone_bounds=zone_bounds)
        for ring in rings:
            for a, b in zip(ring, ring[1:]):
                if abs(b[0] - a[0]) > 180:
                    continue
                if not segment_intersects_bbox(a, b, bbox):
                    continue
                projected_segments.append((project(a, bbox, width, height), project(b, bbox, width, height), core_color, glow_color))

    for a, b, _core_color, _glow_color in projected_segments:
        draw.line((a, b), fill=SHADOW, width=halo_width)
        drawn += 1

    for a, b, _core_color, glow_color in projected_segments:
        draw.line((a, b), fill=glow_color, width=glow_width)

    for a, b, core_color, _glow_color in projected_segments:
        draw.line((a, b), fill=core_color, width=line_width)

    image.save(output_png, optimize=True)
    return drawn


def write_kmz(output_kmz: Path, png_path: Path, bbox: tuple[float, float, float, float], name: str, description: str) -> None:
    west, south, east, north = bbox
    kml = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>{escape_xml(name)}</name>
  <description>{escape_xml(description)}</description>
  <GroundOverlay>
    <name>{escape_xml(name)}</name>
    <Icon><href>files/{png_path.name}</href></Icon>
    <LatLonBox>
      <north>{north:.10f}</north>
      <south>{south:.10f}</south>
      <east>{east:.10f}</east>
      <west>{west:.10f}</west>
    </LatLonBox>
  </GroundOverlay>
</Document>
</kml>
'''
    output_kmz.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml", kml)
        archive.write(png_path, f"files/{png_path.name}")


def escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", default=NATURAL_EARTH_URL)
    parser.add_argument("--workdir", type=Path, default=Path("build/natural-earth"))
    parser.add_argument("--outdir", type=Path, default=Path("dist"))
    parser.add_argument("--bbox", type=parse_bbox, default=parse_bbox("90,-15,145,25"), help="west,south,east,north")
    parser.add_argument("--width", type=int, default=8192)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--label", default="se_asia_8k_neon")
    parser.add_argument("--name", default="Earth timezone borders - Southeast Asia spectrum one-image mobile overlay")
    parser.add_argument("--color-scheme", choices=["spectrum", "neon"], default="spectrum", help="Color assignment: 'spectrum' maps zone offset to rainbow hue (blue→red), 'neon' alternates cyan/magenta")
    args = parser.parse_args()

    west, south, east, north = args.bbox
    height = args.height or round(args.width * (north - south) / (east - west))

    zip_path = args.workdir / "ne_10m_time_zones.zip"
    extract_dir = args.workdir / "ne_10m_time_zones"
    download(args.source_url, zip_path)
    shp_path = extract(zip_path, extract_dir)
    rings_by_shape = read_polygon_rings(shp_path)
    shape_records = read_dbf_records(shp_path.with_suffix(".dbf"))

    # Compute zone bounds from the actual data for spectrum color coding
    if args.color_scheme == "spectrum":
        zones_found = []
        for rec in shape_records:
            zv = rec.get("zone") or rec.get("name") or ""
            try:
                zones_found.append(float(zv))
            except ValueError:
                pass
        zone_bounds = (min(zones_found), max(zones_found)) if zones_found else None
    else:
        zone_bounds = None

    png_path = args.outdir / f"timezone_borders_regional_{args.label}.png"
    kmz_path = args.outdir / f"earth_timezones_regional_{args.label}.kmz"
    drawn = render_region(rings_by_shape, shape_records, args.bbox, args.width, height, png_path,
                          color_scheme=args.color_scheme, zone_bounds=zone_bounds)
    if args.color_scheme == "spectrum":
        color_desc = "spectrum color-coded (blue→cyan→green→yellow→orange→red by UTC offset)"
    else:
        color_desc = "alternating neon cyan and magenta"
    description = (
        "Single-image regional raster timezone border overlay for strict Google Earth Mobile compatibility. "
        f"Timezone borders are {color_desc} with a thicker shadow/glow stroke for visibility. "
        f"Bounds: west={west}, south={south}, east={east}, north={north}. "
        f"Image: {args.width}x{height}px. Drawn segments: {drawn}."
    )
    write_kmz(kmz_path, png_path, args.bbox, args.name, description)

    print(f"image: {png_path} ({args.width}x{height}, {png_path.stat().st_size} bytes)")
    print(f"drawn segments: {drawn}")
    print(f"wrote {kmz_path} ({kmz_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
