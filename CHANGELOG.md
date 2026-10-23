# Changelog

## 0.1.3 (2026-10-23)

- Removed the `workers` settings added in 0.1.2. A worker process was killed partway through a long run on a 4-core,
  8 GB server, for a reason that wasn't pinned down, so parallel processing isn't offered until it's understood and
  tested. Conversion and statistics run one file at a time, as in 0.1.1. (Parallel downloads are unchanged.)

## 0.1.2 (2026-10-23)

- `workers` settings for `[convert]` and `[stats]` to process files in parallel. Removed in 0.1.3.

## 0.1.1 (2026-10-23)

- `convert` reads each file's scale from its SNODAS `.txt` metadata instead of assuming it. Newer files store
  snowpack temperature in tenths of a kelvin, which 0.1.0 read as kelvins (ten times too high).

## 0.1.0 (2026-10-23)

First release.

- `snodas download`: parallel downloads from NSIDC with retries; unpublished days are reported and skipped.
- `snodas convert`: `.dat` grids to compressed NetCDF (CF-scaled int16) or GeoTIFF, with clipped copies per region
  (buffer, interpolation, upscaling).
- `snodas stats`: basin averages and volumes, optionally per elevation band; areas in a basin-centered equal-area
  projection so results are correct anywhere SNODAS covers.
- `snodas run`: the whole workflow from a TOML config, with optional S3 upload and cleanup; skips days already converted.
- `snodas dem`: DEM download from USGS 3DEP for elevation bands.
- `snodas info`, `preview` (terminal, PNG, window) and `chart` for looking at the data.
- Melt and sublimation, which SNODAS leaves blank where there's no snowpack, count blank cells as 0.
