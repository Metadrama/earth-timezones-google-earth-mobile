"""
Shared domain logic for the timezone overlay pipeline.

All tunable values live in config.json alongside this file.
Edit config.json to change colors, strokes, dimensions, etc.
"""

from __future__ import annotations

import colorsys
import json
import struct
from pathlib import Path

# ── load config ──────────────────────────────────────────────────────────

_config_path = Path(__file__).parent / "config.json"
with open(_config_path) as _f:
    _C = json.load(_f)

# Flatten common references
_COLORS = _C["colors"]
_STROKES = _C["strokes"]
_KML = _C["kml"]
_LEGEND = _C["legend"]
_PREVIEW = _C["preview"]
_FONTS = _C["fonts"]
_PATHS = _C["paths"]

# ── public constants ─────────────────────────────────────────────────────

NATURAL_EARTH_URL = _PATHS["natural_earth_url"]
HALO_FACTOR = _STROKES["halo_factor"]
LINE_FACTOR = _STROKES["line_factor"]
HALO_COLOR = tuple(_STROKES["halo_color_rgba"])
FALLBACK_COLOR = tuple(_STROKES["fallback_color_rgba"])
JOINT = _STROKES["joint"]

HUE_START = _COLORS["hue_start"]
HUE_END = _COLORS["hue_end"]
HUE_FALLBACK = _COLORS["hue_fallback"]
SAT_VIVID = _COLORS["saturation_vivid"]
SAT_WASHED = _COLORS["saturation_washed"]
VALUE = _COLORS["value"]
COLOR_ALPHA = _COLORS["alpha"]


# ── helpers ──────────────────────────────────────────────────────────────


def read_dbf_zone_values(dbf_path: str | Path) -> list[str]:
    """Read unique sorted zone values from Natural Earth's DBF metadata."""
    data = Path(dbf_path).read_bytes()
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

    zones: set[str] = set()
    pos = header_len
    for _ in range(record_count):
        record = data[pos: pos + record_len]
        pos += record_len
        if not record or record[:1] == b"*":
            continue
        cursor = 1
        values: dict[str, str] = {}
        for name, _ft, length in fields:
            raw = record[cursor: cursor + length]
            cursor += length
            values[name] = raw.decode("latin1", errors="replace").strip()
        z = values.get("zone") or values.get("name")
        if z:
            zones.add(z)

    return sorted(zones, key=float)


def offset_color(idx: int, total: int) -> tuple[int, int, int]:
    """Map a zone index to its assigned RGB color.

    Uses hue range and saturation values from config.json.
    """
    n = total - 1
    hue_deg = HUE_START - (idx / n) * (HUE_START - HUE_END) if n > 0 else HUE_FALLBACK
    sat = SAT_VIVID if idx % 2 == 0 else SAT_WASHED
    r, g, b = colorsys.hsv_to_rgb(hue_deg / 360.0, sat, VALUE)
    return (int(r * 255), int(g * 255), int(b * 255))


def format_offset(val: str) -> str:
    """Format a DBF zone value like '-5.00' → 'UTC-5', '5.75' → 'UTC+5:45'."""
    f = float(val)
    if f == 0:
        return "UTC±0"
    sign = "+" if f > 0 else "-"
    whole = int(abs(f))
    frac = abs(f) - whole
    if frac == 0:
        return f"UTC{sign}{whole}"
    if frac == 0.5:
        return f"UTC{sign}{whole}:30"
    if frac == 0.75:
        return f"UTC{sign}{whole}:45"
    return f"UTC{sign}{whole}"


def resolve_font(size: int, style: str = "bold") -> str:
    """Find the first available font file. Returns path string."""
    fallbacks = _FONTS["bold_fallbacks"] if style == "bold" else _FONTS["regular_fallbacks"]
    for path in fallbacks:
        p = Path(path)
        if p.exists():
            return str(p)
    return fallbacks[0]  # last resort — will fail at runtime if missing


# ── KML template ─────────────────────────────────────────────────────────

def make_kml(png_name: str) -> str:
    """Build the KML string for a GroundOverlay referencing the given PNG."""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>{_KML["document_name"]}</name>
  <description>{_KML["description"]}</description>
  <GroundOverlay>
    <name>{_KML["overlay_name"]}</name>
    <Icon><href>files/{png_name}</href></Icon>
    <LatLonBox>
      <north>90</north>
      <south>-90</south>
      <east>180</east>
      <west>-180</west>
    </LatLonBox>
  </GroundOverlay>
</Document>
</kml>'''


# ── expose full config dict for scripts that want raw access ─────────────

def get_config() -> dict:
    """Return the full config dict for script-level access."""
    return _C
