"""
The `snodas` command line tool. Run `snodas --help` or `snodas <command> --help` for details.
"""

import argparse
import logging
from pathlib import Path
import sys

from . import __version__

log = logging.getLogger("snodas_tools")

EPILOG = "Docs and examples: https://github.com/wheredoesyourmindgo/snodas-tools"


def _add_dates(p: argparse.ArgumentParser, required: bool = True) -> None:
    g = p.add_argument_group("dates (choose one)" if required else "dates (optional)")
    g.add_argument("date", nargs="?", help="a single date, e.g. 2024-04-01")
    g.add_argument("--start", help="first date of a range")
    g.add_argument("--end", help="last date of a range (default: today)")
    g.add_argument("--recent", type=int, metavar="N", help="the last N days, ending today")
    g.add_argument("--timezone", help="timezone for 'today' (default: UTC, or the config's timezone)")


def _add_data(p: argparse.ArgumentParser) -> None:
    p.add_argument("-c", "--config", type=Path, help="TOML config file (see examples/config.example.toml)")
    p.add_argument("-d", "--dir", type=Path, help="data folder (default: ./snodas_data, or the config's data.directory)")
    p.add_argument("--unmasked", action="store_true", help="use the unmasked (larger, North America) grids")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="snodas",
        description="Download, convert, and summarize NOAA SNODAS snow data for any basin in the contiguous US.",
        epilog=EPILOG,
    )
    parser.add_argument("--version", action="version", version=f"snodas-tools {__version__}")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="more logging (-vv for debug)")
    parser.add_argument("-q", "--quiet", action="store_true", help="no progress bars")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("download", help="download SNODAS data from NSIDC", epilog=EPILOG)
    _add_dates(p)
    _add_data(p)
    p.add_argument("--overwrite", action="store_true", help="download again even if the day is already present")
    p.add_argument("--workers", type=int, help="parallel downloads (default: 4)")

    p = sub.add_parser("convert", help="convert downloaded .dat files to NetCDF or GeoTIFF", epilog=EPILOG)
    _add_dates(p)
    _add_data(p)
    p.add_argument("--format", choices=["netcdf", "geotiff"], help="output format (default: netcdf)")
    p.add_argument("--products", nargs="+", metavar="PRODUCT", help="only these products, e.g. swe depth (see `snodas products`)")
    p.add_argument(
        "--clip", action="append", metavar="NAME=SHAPE", default=[], help="also save a copy clipped to SHAPE, named NAME (repeatable)"
    )
    p.add_argument("--delete-raw", action="store_true", help="delete the .dat/.txt files after converting")
    p.add_argument("--workers", type=int, help="files to convert at once (default: 1, or the config's convert.workers)")
    p.add_argument("--overwrite", action="store_true", help="convert again even if outputs exist")

    p = sub.add_parser("stats", help="compute basin statistics from converted grids", epilog=EPILOG)
    _add_dates(p)
    _add_data(p)
    p.add_argument("--basin", action="append", metavar="NAME=SHAPE", default=[], help="a basin to summarize (repeatable)")
    p.add_argument("--products", nargs="+", metavar="PRODUCT", help="products to summarize (default: swe depth melt temp)")
    p.add_argument("--units", choices=["imperial", "metric"], help="imperial (in, acre-ft) or metric (mm, m^3)")
    p.add_argument("--temperature-units", choices=["K", "C", "F"], help="units for snowpack temperature")
    p.add_argument("-o", "--output", type=Path, help="folder for the statistics tables (default: ./snodas_output)")
    p.add_argument("--export", nargs="+", choices=["csv", "parquet", "xlsx"], help="table formats (CSV is always written)")
    p.add_argument("--workers", type=int, help="statistics to compute at once (default: 1, or the config's stats.workers)")

    p = sub.add_parser("run", help="download, convert and summarize using a config file", epilog=EPILOG)
    _add_dates(p)
    p.add_argument("-c", "--config", type=Path, required=True, help="TOML config file")
    p.add_argument("--overwrite", action="store_true", help="download and convert again even if already done")

    p = sub.add_parser("dem", help="download a DEM (USGS 3DEP) for elevation bands", epilog=EPILOG)
    p.add_argument("shapes", nargs="+", type=Path, help="basin shape file(s)")
    p.add_argument("-o", "--output", type=Path, required=True, help="GeoTIFF to write")
    p.add_argument("--resolution", type=float, default=3.0, help="arc-seconds per cell (default: 3, about 90 m)")
    p.add_argument("--margin", type=float, default=2000, help="meters to extend around the shapes (default: 2000)")

    p = sub.add_parser("info", help="summarize a converted grid", epilog=EPILOG)
    p.add_argument("file", type=Path, help="a .nc or .tif written by `snodas convert`")

    p = sub.add_parser("preview", help="draw a converted grid in the terminal, as a PNG, or in a window", epilog=EPILOG)
    p.add_argument("file", type=Path, help="a .nc or .tif written by `snodas convert`")
    p.add_argument("--basin", nargs="+", type=Path, help="zoom to (and, for PNGs, outline) these shapes")
    p.add_argument("--width", type=int, help="terminal columns to use (default: terminal width)")
    p.add_argument("--no-color", action="store_true", help="plain ASCII output")
    p.add_argument("--png", type=Path, help="save a PNG map (needs the plot extra)")
    p.add_argument("--show", action="store_true", help="open an interactive matplotlib window (needs the plot extra)")

    p = sub.add_parser("chart", help="chart a statistics table in the terminal", epilog=EPILOG)
    p.add_argument("table", type=Path, help="a table written by `snodas stats`, e.g. snodas_output/swe_sum.csv")
    p.add_argument("--basin", help="column to chart (default: the first basin)")
    p.add_argument("--start", help="first date to show")
    p.add_argument("--end", help="last date to show")
    p.add_argument("--width", type=int, help="chart columns (default: terminal width)")
    p.add_argument("--height", type=int, default=12, help="chart rows (default: 12)")

    sub.add_parser("products", help="list the SNODAS products snodas-tools knows about", epilog=EPILOG)
    return parser


def _pairs(values: list[str], flag: str) -> list[tuple[str, Path]]:
    pairs = []
    for value in values:
        name, sep, path = value.partition("=")
        if not sep or not name or not path:
            raise ValueError(f"{flag} expects NAME=PATH, got '{value}'")
        pairs.append((name, Path(path)))
    return pairs


def _config(args):
    from .config import Config, load_config  # pylint: disable=import-outside-toplevel

    cfg = load_config(args.config) if getattr(args, "config", None) else Config()
    if getattr(args, "dir", None):
        cfg.data_dir = args.dir
    if getattr(args, "unmasked", False):
        cfg.masked = False
    if getattr(args, "timezone", None):
        cfg.timezone = args.timezone
    return cfg


def _days(args, cfg):
    from .dates import resolve_dates  # pylint: disable=import-outside-toplevel

    return resolve_dates(args.date, args.start, args.end, args.recent, cfg.timezone)


def _terminal_width(default: int = 80) -> int:
    import shutil  # pylint: disable=import-outside-toplevel

    return shutil.get_terminal_size((default, 24)).columns


def cmd_download(args) -> int:
    from .download import download  # pylint: disable=import-outside-toplevel

    cfg = _config(args)
    days = _days(args, cfg)
    results = download(days, cfg.data_dir, cfg.masked, args.overwrite, args.workers or cfg.workers, not args.quiet)
    counts = {s: sum(r.status == s for r in results) for s in ("downloaded", "exists", "missing", "error")}
    print(", ".join(f"{n} {s}" for s, n in counts.items() if n) + f" -> {cfg.data_dir}")
    return 1 if counts["error"] else 0


def cmd_convert(args) -> int:
    from .convert import ClipRegion, convert  # pylint: disable=import-outside-toplevel
    from .products import get_product  # pylint: disable=import-outside-toplevel

    cfg = _config(args)
    days = _days(args, cfg)
    regions = cfg.clips + [ClipRegion(name, [path]) for name, path in _pairs(args.clip, "--clip")]
    products = [get_product(p) for p in args.products] if args.products else (cfg.products if args.config else None)
    written = convert(
        days,
        cfg.data_dir,
        masked=cfg.masked,
        products=products,
        fmt=args.format or cfg.format,
        regions=regions,
        keep_raw=cfg.keep_raw and not args.delete_raw,
        keep_full_extent=cfg.keep_full_extent if args.config else True,
        overwrite=args.overwrite,
        progress=not args.quiet,
        workers=args.workers or cfg.convert_workers,
    )
    print(f"{len(written)} converted file(s) in {cfg.data_dir}")
    return 0


def cmd_stats(args) -> int:
    from . import store  # pylint: disable=import-outside-toplevel
    from .pipeline import compute_stats  # pylint: disable=import-outside-toplevel
    from .products import get_product  # pylint: disable=import-outside-toplevel
    from .stats import Basin, Units  # pylint: disable=import-outside-toplevel

    cfg = _config(args)
    days = _days(args, cfg)
    basins = cfg.basins + [Basin(name, [path]) for name, path in _pairs(args.basin, "--basin")]
    if not basins:
        raise ValueError("No basins: pass --basin NAME=SHAPE or use a config with [[basin]] entries.")
    products = [get_product(p) for p in args.products] if args.products else cfg.stat_products
    units = Units(args.units or cfg.units.system, args.temperature_units or cfg.units.temperature)
    output = args.output or cfg.output_dir
    formats = tuple(args.export) if args.export else cfg.export_formats
    results = compute_stats(days, cfg.data_dir, basins, products, units, cfg.masked, not args.quiet, args.workers or cfg.stats_workers)
    if not results:
        print("No converted grids found for those dates. Run `snodas download` and `snodas convert` first.")
        return 1
    written = store.save(results, output, {p.key: units.labels(p) for p in products}, formats)
    print(f"{len(results)} basin statistics saved to {output} ({len(written)} files)")
    return 0


def cmd_run(args) -> int:
    from .pipeline import run  # pylint: disable=import-outside-toplevel

    cfg = _config(args)
    days = _days(args, cfg)
    summary = run(cfg, days, progress=not args.quiet, overwrite=args.overwrite)
    statuses = [d.status for d in summary.downloads]
    print(
        f"{len(days)} day(s): {statuses.count('downloaded')} downloaded, {statuses.count('exists')} already present, "
        f"{statuses.count('missing')} not published, {statuses.count('error')} failed; "
        f"{len(summary.converted)} grids; {len(summary.stats)} statistics; {len(summary.uploaded)} uploaded"
    )
    return 1 if summary.failed_downloads else 0


def cmd_dem(args) -> int:
    from .dem import download_dem  # pylint: disable=import-outside-toplevel

    path = download_dem(args.shapes, args.output, args.resolution, args.margin)
    print(f"DEM saved to {path}")
    return 0


def cmd_info(args) -> int:
    from .preview import describe, open_any  # pylint: disable=import-outside-toplevel

    for key, value in describe(open_any(args.file)).items():
        if isinstance(value, float):
            value = f"{value:.4g}"
        print(f"{key:>12}: {value}")
    return 0


def cmd_preview(args) -> int:
    from .preview import crop_to_shapes, open_any, plot_map, render_terminal  # pylint: disable=import-outside-toplevel

    da = open_any(args.file)
    if args.basin:
        da = crop_to_shapes(da, args.basin)
    if args.png or args.show:
        plot_map(da, args.basin, args.png, args.show)
        if args.png:
            print(f"Saved {args.png}")
    else:
        print(render_terminal(da, width=args.width or _terminal_width() - 1, color=False if args.no_color else None))
    return 0


def cmd_chart(args) -> int:
    import json  # pylint: disable=import-outside-toplevel

    import pandas as pd  # pylint: disable=import-outside-toplevel

    from .preview import render_chart  # pylint: disable=import-outside-toplevel

    df = pd.read_csv(args.table, parse_dates=["date"]).set_index("date")
    if "basin" in df.columns:
        raise ValueError("Elevation tables have one row per basin; chart a basin table like swe_sum.csv instead.")
    column = args.basin or df.columns[0]
    if column not in df.columns:
        raise ValueError(f"No column '{column}'. Columns: {', '.join(df.columns)}")
    series = df[column].loc[args.start : args.end]
    units_file = args.table.parent / "units.json"
    units = json.loads(units_file.read_text()).get(args.table.stem, "") if units_file.exists() else ""
    width = args.width or _terminal_width() - 12
    print(render_chart(series, width=width, height=args.height, title=f"{args.table.stem}: {column}", units=units))
    return 0


def cmd_products(_args) -> int:
    from .products import PRODUCTS  # pylint: disable=import-outside-toplevel

    print(f"{'product':<20} {'code':>5}  {'units':<5} description")
    for p in PRODUCTS.values():
        print(f"{p.key:<20} {p.code:>5}  {p.units:<5} {p.label}")
    return 0


COMMANDS = {
    "download": cmd_download,
    "convert": cmd_convert,
    "stats": cmd_stats,
    "run": cmd_run,
    "dem": cmd_dem,
    "info": cmd_info,
    "preview": cmd_preview,
    "chart": cmd_chart,
    "products": cmd_products,
}


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `snodas` command."""
    args = _parser().parse_args(argv)
    level = logging.WARNING - 10 * min(args.verbose, 2)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    try:
        return COMMANDS[args.command](args)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        if args.verbose >= 2:
            raise
        print(f"snodas {args.command}: error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
