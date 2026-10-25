"""
Loading a snodas-tools TOML config file. See `examples/config.example.toml` for a documented example.

Relative paths in the config are resolved against the config file's folder.
"""

from dataclasses import dataclass, field
from pathlib import Path
import tomllib

from .convert import ClipRegion, EXTENSIONS
from .products import PRODUCTS, Product, get_product
from .stats import Basin, ElevationBands, Units
from .store import EXPORT_FORMATS


class ConfigError(ValueError):
    """A problem with the config file."""


@dataclass
class UploadConfig:
    """Optional upload of results to S3 or an S3-compatible service (DigitalOcean Spaces, MinIO, R2, ...)."""

    bucket: str
    prefix: str = "snodas"
    endpoint_url: str | None = None
    region: str | None = None
    public: bool = False  # make uploaded files publicly readable
    stats: bool = True  # upload the statistics tables
    rasters: bool = False  # upload converted/clipped grids


@dataclass
class Config:
    """A parsed config file."""

    path: Path | None = None
    data_dir: Path = Path("snodas_data")
    masked: bool = True
    timezone: str = "UTC"
    workers: int = 4  # parallel downloads
    convert_workers: int = 1  # files converted at once (separate processes)
    stats_workers: int = 1  # statistics computed at once (separate processes)
    format: str = "netcdf"
    products: list[Product] = field(default_factory=lambda: [PRODUCTS[k] for k in ("swe", "depth", "melt", "temp")])
    keep_raw: bool = True
    keep_full_extent: bool = True
    clips: list[ClipRegion] = field(default_factory=list)
    output_dir: Path = Path("snodas_output")
    units: Units = field(default_factory=Units)
    export_formats: tuple[str, ...] = ("csv",)
    stats_products: list[Product] | None = None  # default: the converted products
    basins: list[Basin] = field(default_factory=list)
    upload: UploadConfig | None = None
    cleanup_after_run: bool = False

    @property
    def stat_products(self) -> list[Product]:
        return self.stats_products if self.stats_products is not None else self.products


def _check_keys(section: str, table: dict, allowed: set[str]) -> None:
    unknown = set(table) - allowed
    if unknown:
        raise ConfigError(f"Unknown setting(s) in [{section}]: {', '.join(sorted(unknown))}")


def _paths(base: Path, value, where: str) -> list[Path]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{where}: 'shapes' must be a path or a list of paths")
    resolved = []
    for item in value:
        # keep 'archive.zip!inner/file.shp' working: resolve only the part before '!'
        outer, sep, inner = str(item).partition("!")
        path = Path(outer).expanduser()
        resolved.append(Path(f"{(path if path.is_absolute() else base / path).resolve()}{sep}{inner}"))
    return resolved


def _path(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def _products(value, where: str) -> list[Product]:
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{where}: 'products' must be a non-empty list, e.g. [\"swe\", \"depth\"]")
    try:
        return [get_product(v) for v in value]
    except ValueError as exc:
        raise ConfigError(f"{where}: {exc}") from None


def load_config(path: str | Path) -> Config:
    """Read and validate a TOML config file."""
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    return parse_config(raw, base=path.parent.resolve(), path=path)


def parse_config(raw: dict, base: Path = Path("."), path: Path | None = None) -> Config:
    """Build a Config from an already-parsed TOML table."""
    _check_keys("top level", raw, {"data", "download", "convert", "stats", "basin", "upload", "cleanup"})
    cfg = Config(path=path)

    data = raw.get("data", {})
    _check_keys("data", data, {"directory", "masked", "timezone"})
    cfg.data_dir = _path(base, data.get("directory", "snodas_data"))
    cfg.masked = bool(data.get("masked", True))
    cfg.timezone = data.get("timezone", "UTC")

    download = raw.get("download", {})
    _check_keys("download", download, {"workers"})
    cfg.workers = int(download.get("workers", 4))

    convert = raw.get("convert", {})
    _check_keys("convert", convert, {"format", "products", "keep_raw", "keep_full_extent", "clip", "workers"})
    cfg.convert_workers = max(1, int(convert.get("workers", 1)))
    cfg.format = convert.get("format", "netcdf")
    if cfg.format not in EXTENSIONS:
        raise ConfigError(f"[convert] format must be one of: {', '.join(EXTENSIONS)}")
    if "products" in convert:
        cfg.products = _products(convert["products"], "[convert]")
    cfg.keep_raw = bool(convert.get("keep_raw", True))
    cfg.keep_full_extent = bool(convert.get("keep_full_extent", True))
    for i, clip in enumerate(convert.get("clip", [])):
        where = f"[[convert.clip]] #{i + 1}"
        _check_keys(where, clip, {"name", "shapes", "buffer_m", "interpolate", "upscale", "format"})
        if "name" not in clip:
            raise ConfigError(f"{where}: 'name' is required")
        fmt = clip.get("format")
        if fmt is not None and fmt not in EXTENSIONS:
            raise ConfigError(f"{where}: format must be one of: {', '.join(EXTENSIONS)}")
        cfg.clips.append(
            ClipRegion(
                name=clip["name"],
                shapes=_paths(base, clip.get("shapes"), where),
                buffer_m=float(clip.get("buffer_m", 0)),
                interpolate=bool(clip.get("interpolate", False)),
                upscale=int(clip.get("upscale", 1)),
                format=fmt,
            )
        )
    names = [c.name for c in cfg.clips]
    if len(names) != len(set(names)):
        raise ConfigError("[[convert.clip]] names must be unique")
    if not cfg.keep_full_extent and not cfg.clips:
        raise ConfigError("[convert] keep_full_extent = false needs at least one [[convert.clip]] region")

    stats = raw.get("stats", {})
    _check_keys("stats", stats, {"output_directory", "units", "temperature_units", "export_formats", "products", "workers"})
    cfg.stats_workers = max(1, int(stats.get("workers", 1)))
    cfg.output_dir = _path(base, stats.get("output_directory", "snodas_output"))
    try:
        cfg.units = Units(stats.get("units", "imperial"), stats.get("temperature_units", "F"))
    except ValueError as exc:
        raise ConfigError(f"[stats] {exc}") from None
    formats = tuple(stats.get("export_formats", ["csv"]))
    if set(formats) - set(EXPORT_FORMATS):
        raise ConfigError(f"[stats] export_formats must be from: {', '.join(EXPORT_FORMATS)}")
    cfg.export_formats = formats
    if "products" in stats:
        cfg.stats_products = _products(stats["products"], "[stats]")
        missing = {p.key for p in cfg.stats_products} - {p.key for p in cfg.products}
        if missing:
            raise ConfigError(f"[stats] products {sorted(missing)} are not in [convert] products")

    for i, basin in enumerate(raw.get("basin", [])):
        where = f"[[basin]] #{i + 1}"
        _check_keys(where, basin, {"name", "shapes", "source", "interpolate", "elevation_bands"})
        if "name" not in basin:
            raise ConfigError(f"{where}: 'name' is required")
        source = basin.get("source")
        if source is not None and source not in names:
            raise ConfigError(f"{where}: source '{source}' is not a [[convert.clip]] name ({', '.join(names) or 'none defined'})")
        if source is None and not cfg.keep_full_extent:
            raise ConfigError(f"{where}: set 'source' to a clip region, since full-extent grids are not kept")
        bands = None
        if "elevation_bands" in basin:
            eb = basin["elevation_bands"]
            _check_keys(f"{where} elevation_bands", eb, {"dem", "step", "units", "min", "max", "dem_nodata"})
            if "dem" not in eb:
                raise ConfigError(f"{where} elevation_bands: 'dem' is required")
            if eb.get("units", "ft") not in ("ft", "m"):
                raise ConfigError(f"{where} elevation_bands: units must be 'ft' or 'm'")
            bands = ElevationBands(
                dem=_path(base, eb["dem"]),
                step=float(eb.get("step", 500)),
                units=eb.get("units", "ft"),
                min=eb.get("min"),
                max=eb.get("max"),
                dem_nodata=eb.get("dem_nodata"),
            )
            if bands.step <= 0:
                raise ConfigError(f"{where} elevation_bands: step must be positive")
        cfg.basins.append(
            Basin(
                name=basin["name"],
                shapes=_paths(base, basin.get("shapes"), where),
                source=source,
                interpolate=bool(basin.get("interpolate", True)),
                elevation_bands=bands,
            )
        )
    basin_names = [b.name for b in cfg.basins]
    if len(basin_names) != len(set(basin_names)):
        raise ConfigError("[[basin]] names must be unique")

    if "upload" in raw:
        up = raw["upload"]
        _check_keys("upload", up, {"bucket", "prefix", "endpoint_url", "region", "public", "stats", "rasters"})
        if "bucket" not in up:
            raise ConfigError("[upload] 'bucket' is required")
        cfg.upload = UploadConfig(**up)

    cleanup = raw.get("cleanup", {})
    _check_keys("cleanup", cleanup, {"after_run"})
    cfg.cleanup_after_run = bool(cleanup.get("after_run", False))
    return cfg
