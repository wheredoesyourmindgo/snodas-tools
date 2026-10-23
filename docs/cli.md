# Command reference

Every `snodas` command and option. This page is generated from the program itself by
`python -m snodas_tools.cli_reference`; don't edit it by hand. For examples, see the [README](../README.md).
Run `snodas COMMAND --help` for the same information in a terminal.

| Command | What it does |
|---|---|
| [`snodas download`](#snodas-download) | download SNODAS data from NSIDC |
| [`snodas convert`](#snodas-convert) | convert downloaded .dat files to NetCDF or GeoTIFF |
| [`snodas stats`](#snodas-stats) | compute basin statistics from converted grids |
| [`snodas run`](#snodas-run) | download, convert and summarize using a config file |
| [`snodas dem`](#snodas-dem) | download a DEM (USGS 3DEP) for elevation bands |
| [`snodas info`](#snodas-info) | summarize a converted grid |
| [`snodas preview`](#snodas-preview) | draw a converted grid in the terminal, as a PNG, or in a window |
| [`snodas chart`](#snodas-chart) | chart a statistics table in the terminal |
| [`snodas products`](#snodas-products) | list the SNODAS products snodas-tools knows about |

## Options for every command

These go before the command name, e.g. `snodas --quiet run ...`.

| Argument or option | Description |
|---|---|
| `-h, --help` | show this help message and exit |
| `--version` | show program's version number and exit |
| `-v, --verbose` | more logging (-vv for debug) |
| `-q, --quiet` | no progress bars |

## snodas download

Download SNODAS data from NSIDC.

| Argument or option | Description |
|---|---|
| `[date]` | a single date, e.g. 2024-04-01 |
| `--start START` | first date of a range |
| `--end END` | last date of a range (default: today) |
| `--recent N` | the last N days, ending today |
| `--timezone TIMEZONE` | timezone for 'today' (default: UTC, or the config's timezone) |
| `-c, --config CONFIG` | TOML config file (see examples/config.example.toml) |
| `-d, --dir DIR` | data folder (default: ./snodas_data, or the config's data.directory) |
| `--unmasked` | use the unmasked (larger, North America) grids |
| `--overwrite` | download again even if the day is already present |
| `--workers WORKERS` | parallel downloads (default: 4) |

## snodas convert

Convert downloaded .dat files to NetCDF or GeoTIFF.

| Argument or option | Description |
|---|---|
| `[date]` | a single date, e.g. 2024-04-01 |
| `--start START` | first date of a range |
| `--end END` | last date of a range (default: today) |
| `--recent N` | the last N days, ending today |
| `--timezone TIMEZONE` | timezone for 'today' (default: UTC, or the config's timezone) |
| `-c, --config CONFIG` | TOML config file (see examples/config.example.toml) |
| `-d, --dir DIR` | data folder (default: ./snodas_data, or the config's data.directory) |
| `--unmasked` | use the unmasked (larger, North America) grids |
| `--format {netcdf,geotiff}` | output format (default: netcdf) |
| `--products PRODUCT [PRODUCT ...]` | only these products, e.g. swe depth (see `snodas products`) |
| `--clip NAME=SHAPE` | also save a copy clipped to SHAPE, named NAME (repeatable) |
| `--delete-raw` | delete the .dat/.txt files after converting |
| `--overwrite` | convert again even if outputs exist |

## snodas stats

Compute basin statistics from converted grids.

| Argument or option | Description |
|---|---|
| `[date]` | a single date, e.g. 2024-04-01 |
| `--start START` | first date of a range |
| `--end END` | last date of a range (default: today) |
| `--recent N` | the last N days, ending today |
| `--timezone TIMEZONE` | timezone for 'today' (default: UTC, or the config's timezone) |
| `-c, --config CONFIG` | TOML config file (see examples/config.example.toml) |
| `-d, --dir DIR` | data folder (default: ./snodas_data, or the config's data.directory) |
| `--unmasked` | use the unmasked (larger, North America) grids |
| `--basin NAME=SHAPE` | a basin to summarize (repeatable) |
| `--products PRODUCT [PRODUCT ...]` | products to summarize (default: swe depth melt temp) |
| `--units {imperial,metric}` | imperial (in, acre-ft) or metric (mm, m^3) |
| `--temperature-units {K,C,F}` | units for snowpack temperature |
| `-o, --output OUTPUT` | folder for the statistics tables (default: ./snodas_output) |
| `--export {csv,parquet,xlsx} [{csv,parquet,xlsx} ...]` | table formats (CSV is always written) |

## snodas run

Download, convert and summarize using a config file.

| Argument or option | Description |
|---|---|
| `[date]` | a single date, e.g. 2024-04-01 |
| `--start START` | first date of a range |
| `--end END` | last date of a range (default: today) |
| `--recent N` | the last N days, ending today |
| `--timezone TIMEZONE` | timezone for 'today' (default: UTC, or the config's timezone) |
| `-c, --config CONFIG` | **Required.** TOML config file |
| `--overwrite` | download and convert again even if already done |

## snodas dem

Download a DEM (USGS 3DEP) for elevation bands.

| Argument or option | Description |
|---|---|
| `shapes [shapes ...]` | basin shape file(s) |
| `-o, --output OUTPUT` | **Required.** GeoTIFF to write |
| `--resolution RESOLUTION` | arc-seconds per cell (default: 3, about 90 m) |
| `--margin MARGIN` | meters to extend around the shapes (default: 2000) |

## snodas info

Summarize a converted grid.

| Argument or option | Description |
|---|---|
| `file` | a .nc or .tif written by `snodas convert` |

## snodas preview

Draw a converted grid in the terminal, as a PNG, or in a window.

| Argument or option | Description |
|---|---|
| `file` | a .nc or .tif written by `snodas convert` |
| `--basin BASIN [BASIN ...]` | zoom to (and, for PNGs, outline) these shapes |
| `--width WIDTH` | terminal columns to use (default: terminal width) |
| `--no-color` | plain ASCII output |
| `--png PNG` | save a PNG map (needs the plot extra) |
| `--show` | open an interactive matplotlib window (needs the plot extra) |

## snodas chart

Chart a statistics table in the terminal.

| Argument or option | Description |
|---|---|
| `table` | a table written by `snodas stats`, e.g. snodas_output/swe_sum.csv |
| `--basin BASIN` | column to chart (default: the first basin) |
| `--start START` | first date to show |
| `--end END` | last date to show |
| `--width WIDTH` | chart columns (default: terminal width) |
| `--height HEIGHT` | chart rows (default: 12) |

## snodas products

List the SNODAS products snodas-tools knows about.

