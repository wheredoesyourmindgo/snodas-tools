# Changelog

## 0.1.2 (2026-10-23)

- `workers` settings for `[convert]` and `[stats]` (and `--workers` on `snodas convert` / `snodas stats`) process
  files in parallel. Each worker writes only its own files, and statistics are gathered and sorted before any table
  is written, so results are identical to a serial run.

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
