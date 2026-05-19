# Credits and Data Provenance

## Natural Earth

Timezone boundaries are from Natural Earth’s `ne_10m_time_zones` dataset.

- Dataset page: <https://www.naturalearthdata.com/downloads/10m-cultural-vectors/timezones/>
- Download: <https://naciscdn.org/naturalearth/10m/cultural/ne_10m_time_zones.zip>
- Terms: <https://www.naturalearthdata.com/about/terms-of-use/>

Natural Earth data is public domain.

## International Mapping Associates and CIA World Factbook

Natural Earth credits the timezone layer as donated by International Mapping Associates, Inc., with timezone source material primarily derived from the CIA World Factbook timezone map and then adjusted to Natural Earth linework.

## Google Earth / KML

The overlay uses standard KML/KMZ concepts:

- `GroundOverlay`
- `Icon`
- `LatLonBox`
- KMZ archive layout with `doc.kml` and asset files

Reference: <https://developers.google.com/kml/documentation/>

## Pillow

The raster images are rendered with Pillow.

- <https://python-pillow.org/>

## Project authorship

This repository packages the generated Google Earth Mobile overlay, scripts, and methodology notes. It was created after vector timezone KML overlays proved unusably slow on Google Earth Mobile.
