# Changelog

## 0.2.1 (2026-11-24)

- Water years with fewer than 30 days of data are left out of the `snodas chart` water-year views and the peaks table,
  so a sliver of a year isn't counted as a season. The tables usually start on 2003-09-30, which made WY2003 a
  one-day "year" in the chart's comparison range and gave it a zero-snow row in `swe_peaks.csv`. The latest water year
  is always kept (it's still filling in), as is any year highlighted with `--years`.

## 0.2.0 (2026-11-24)

- `snodas chart --view` compares water years (Oct 1 to Sep 30): `water-years` draws the latest year (or `--years`, up
  to four) over the median and range of the other years and reports its percent of median, rank and peak so far;
  `heatmap` draws one row per water year; `months` draws box plots of monthly averages. Days line up by calendar date
  across leap and non-leap years.
- `snodas peaks` writes `swe_peaks.csv`: each basin's peak date, peak average and volume, and melt-out date for every
  water year, with a status (`final`, `in progress`, `incomplete`). `snodas run` rebuilds it after saving statistics;
  a new `[peaks]` config section picks the products and the melt-out threshold (default 1% of the peak).
- `snodas gaps` lists the days in a range (default: the first local day through today) that are converted, downloaded
  but not converted, not downloaded, or never published by NSIDC, as compact date ranges. NSIDC is asked through its
  monthly directory listings, one request per month with missing days (`--offline` skips it). `--download` fetches
  the missing days NSIDC has.
- `snodas chart` can save any view as a PNG (`--png`) or open it in a window (`--show`), and takes `--no-color`.

## 0.1.5 (2026-10-24)

- Parallel processing is back, tested this time: `workers` under `[convert]` and `[stats]` (and `--workers` on
  `snodas convert` / `snodas stats`), default 1. Workers start as fresh processes ("spawn") rather than copies, which
  the netCDF/HDF5 libraries handle reliably, and each task frees its grids (0.1.4), so a worker stays around 1 GB.
  Workers aren't recycled: on Python 3.11, `max_tasks_per_child` can leave the pool waiting forever.
- Tested on a 4-core, 8 GB server, February 2023 (224 grids, 448 statistics): 3 workers took 119 s vs. 323 s serially,
  peaked at 2.6 GB in total, and produced identical grids and byte-identical tables.

## 0.1.4 (2026-10-23)

- Free each grid's memory right after it's converted (and after each day of statistics). Memory used to grow by
  ~100 MB per converted file, because Python's automatic collection counts objects rather than bytes, so a long run
  (e.g. a month of history) could run out of memory and be killed. It now peaks around 1 GB regardless of run length.
  This is also the likely cause of the worker crash behind 0.1.3.

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
