#!/usr/bin/env python3
"""Build low-image-count paneled regional Google Earth Mobile timezone KMZs.

Why this exists:
- one huge GroundOverlay can partially render on mobile because of texture limits
- hundreds of tiles hit Google Earth's external image-count limit
- a small grid of <=2048 px panels avoids both: each texture is mobile-sized,
  while total image references stay low
"""

from __future__ import annotations

import argparse
import math
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from make_raster_overlay import NATURAL_EARTH_URL, download, extract, read_polygon_rings
from make_regional_raster_overlay import CYAN, CYAN_GLOW, MAGENTA, MAGENTA_GLOW, SHADOW, escape_xml, parse_bbox, read_dbf_records, timezone_color

INSIDE = 0
LEFT = 1
RIGHT = 2
BOTTOM = 4
TOP = 8


def outcode(point: tuple[float, float], bbox: tuple[float, float, float, float]) -> int:
    lon, lat = point
    west, south, east, north = bbox
    code = INSIDE
    if lon < west:
        code |= LEFT
    elif lon > east:
        code |= RIGHT
    if lat < south:
        code |= BOTTOM
    elif lat > north:
        code |= TOP
    return code


def clip_segment(
    a: tuple[float, float],
    b: tuple[float, float],
    bbox: tuple[float, float, float, float],
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Cohen-Sutherland clip of lon/lat segment to bbox."""
    west, south, east, north = bbox
    x0, y0 = a
    x1, y1 = b
    c0 = outcode((x0, y0), bbox)
    c1 = outcode((x1, y1), bbox)

    while True:
        if not (c0 | c1):
            return (x0, y0), (x1, y1)
        if c0 & c1:
            return None

        code = c0 or c1
        if code & TOP:
            if y1 == y0:
                return None
            x = x0 + (x1 - x0) * (north - y0) / (y1 - y0)
            y = north
        elif code & BOTTOM:
            if y1 == y0:
                return None
            x = x0 + (x1 - x0) * (south - y0) / (y1 - y0)
            y = south
        elif code & RIGHT:
            if x1 == x0:
                return None
            y = y0 + (y1 - y0) * (east - x0) / (x1 - x0)
            x = east
        else:  # LEFT
            if x1 == x0:
                return None
            y = y0 + (y1 - y0) * (west - x0) / (x1 - x0)
            x = west

        if code == c0:
            x0, y0 = x, y
            c0 = outcode((x0, y0), bbox)
        else:
            x1, y1 = x, y
            c1 = outcode((x1, y1), bbox)


def project(
    point: tuple[float, float],
    bbox: tuple[float, float, float, float],
    width: int,
    height: int,
    scale: int,
) -> tuple[int, int]:
    lon, lat = point
    west, south, east, north = bbox
    x = (lon - west) / (east - west) * (width * scale - 1)
    y = (north - lat) / (north - south) * (height * scale - 1)
    return int(round(x)), int(round(y))


def render_panel(
    rings_by_shape: list[list[list[tuple[float, float]]]],
    shape_records: list[dict[str, str]],
    bbox: tuple[float, float, float, float],
    panel_width: int,
    panel_height: int,
    virtual_width: int,
    output_png: Path,
    supersample: int,
) -> int:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    scale = max(1, supersample)
    image = Image.new("RGBA", (panel_width * scale, panel_height * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    halo_width = max(4, virtual_width // 1024) * scale
    glow_width = max(3, virtual_width // 1365) * scale
    line_width = max(2, virtual_width // 2048) * scale

    projected_segments: list[
        tuple[tuple[int, int], tuple[int, int], tuple[int, int, int, int], tuple[int, int, int, int]]
    ] = []
    for shape_index, rings in enumerate(rings_by_shape):
        record = shape_records[shape_index] if shape_index < len(shape_records) else {}
        core_color, glow_color = timezone_color(record)
        for ring in rings:
            for a, b in zip(ring, ring[1:]):
                if abs(b[0] - a[0]) > 180:
                    continue
                clipped = clip_segment(a, b, bbox)
                if clipped is None:
                    continue
                ca, cb = clipped
                projected_segments.append(
                    (project(ca, bbox, panel_width, panel_height, scale), project(cb, bbox, panel_width, panel_height, scale), core_color, glow_color)
                )

    for a, b, _core_color, _glow_color in projected_segments:
        draw.line((a, b), fill=SHADOW, width=halo_width)

    for a, b, _core_color, glow_color in projected_segments:
        draw.line((a, b), fill=glow_color, width=glow_width)

    for a, b, core_color, _glow_color in projected_segments:
        draw.line((a, b), fill=core_color, width=line_width)

    if scale > 1:
        image = image.resize((panel_width, panel_height), Image.Resampling.LANCZOS)

    if image.getbbox() is None:
        return 0

    image.save(output_png, optimize=True)
    return len(projected_segments)


def panel_bbox(
    base_bbox: tuple[float, float, float, float],
    virtual_width: int,
    virtual_height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
) -> tuple[float, float, float, float]:
    west, south, east, north = base_bbox
    lon_span = east - west
    lat_span = north - south
    p_west = west + lon_span * x0 / virtual_width
    p_east = west + lon_span * x1 / virtual_width
    p_north = north - lat_span * y0 / virtual_height
    p_south = north - lat_span * y1 / virtual_height
    return p_west, p_south, p_east, p_north


def write_kmz(
    output_kmz: Path,
    panels: list[tuple[Path, tuple[float, float, float, float]]],
    name: str,
    description: str,
) -> None:
    overlays = []
    for index, (png_path, bbox) in enumerate(panels, start=1):
        west, south, east, north = bbox
        overlays.append(
            f'''  <GroundOverlay>
    <name>{escape_xml(name)} panel {index}</name>
    <Icon><href>panels/{png_path.name}</href></Icon>
    <LatLonBox>
      <north>{north:.10f}</north>
      <south>{south:.10f}</south>
      <east>{east:.10f}</east>
      <west>{west:.10f}</west>
    </LatLonBox>
  </GroundOverlay>'''
        )

    kml = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>{escape_xml(name)}</name>
  <description>{escape_xml(description)}</description>
{chr(10).join(overlays)}
</Document>
</kml>
'''
    output_kmz.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("doc.kml", kml)
        for png_path, _bbox in panels:
            archive.write(png_path, f"panels/{png_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", default=NATURAL_EARTH_URL)
    parser.add_argument("--workdir", type=Path, default=Path("build/natural-earth"))
    parser.add_argument("--outdir", type=Path, default=Path("dist"))
    parser.add_argument("--bbox", type=parse_bbox, default=parse_bbox("90,-15,145,25"), help="west,south,east,north")
    parser.add_argument("--width", type=int, default=16384, help="Virtual regional raster width before panel split")
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--panel-size", type=int, default=2048, help="Maximum PNG panel side length")
    parser.add_argument("--supersample", type=int, default=2, help="Render scale for antialiasing before downsampling")
    parser.add_argument("--label", default="se_asia_16k_neon_panels")
    parser.add_argument("--name", default="Earth timezone borders - Southeast Asia 16K neon paneled mobile overlay")
    args = parser.parse_args()

    west, south, east, north = args.bbox
    virtual_height = args.height or round(args.width * (north - south) / (east - west))

    zip_path = args.workdir / "ne_10m_time_zones.zip"
    extract_dir = args.workdir / "ne_10m_time_zones"
    download(args.source_url, zip_path)
    shp_path = extract(zip_path, extract_dir)
    rings_by_shape = read_polygon_rings(shp_path)
    shape_records = read_dbf_records(shp_path.with_suffix(".dbf"))

    panel_dir = args.outdir / f"panels_{args.label}"
    panel_dir.mkdir(parents=True, exist_ok=True)

    cols = math.ceil(args.width / args.panel_size)
    rows = math.ceil(virtual_height / args.panel_size)
    panels: list[tuple[Path, tuple[float, float, float, float]]] = []
    total_segments = 0

    for row in range(rows):
        for col in range(cols):
            x0 = col * args.panel_size
            y0 = row * args.panel_size
            x1 = min(args.width, x0 + args.panel_size)
            y1 = min(virtual_height, y0 + args.panel_size)
            p_bbox = panel_bbox(args.bbox, args.width, virtual_height, x0, y0, x1, y1)
            png_path = panel_dir / f"panel_{row:02d}_{col:02d}.png"
            drawn = render_panel(
                rings_by_shape,
                shape_records,
                p_bbox,
                x1 - x0,
                y1 - y0,
                args.width,
                png_path,
                args.supersample,
            )
            if drawn:
                panels.append((png_path, p_bbox))
                total_segments += drawn
            elif png_path.exists():
                png_path.unlink()

    kmz_path = args.outdir / f"earth_timezones_regional_{args.label}.kmz"
    description = (
        "Low-image-count paneled regional raster timezone border overlay for Google Earth Mobile. "
        "Designed after one huge image partially rendered on mobile: panels stay at or below the configured texture size, "
        "while image references stay far below the tiled-pack limit. "
        "Styling uses alternating neon light cyan and neon magenta with thicker shadow/glow strokes. "
        f"Bounds: west={west}, south={south}, east={east}, north={north}. "
        f"Virtual image: {args.width}x{virtual_height}px. Panels: {len(panels)}. Drawn segments: {total_segments}."
    )
    write_kmz(kmz_path, panels, args.name, description)

    print(f"virtual image: {args.width}x{virtual_height}")
    print(f"panel grid: {cols}x{rows}; non-empty panels: {len(panels)}")
    print(f"drawn segments: {total_segments}")
    print(f"wrote {kmz_path} ({kmz_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
