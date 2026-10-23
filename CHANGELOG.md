# Changelog

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
