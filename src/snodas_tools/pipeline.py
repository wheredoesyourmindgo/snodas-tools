"""
Running the whole workflow from a config: download -> convert -> statistics -> (upload) -> (cleanup).
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
import logging
from pathlib import Path
import shutil

from tqdm import tqdm

from . import store
from .config import Config
from .convert import EXTENSIONS, convert
from .download import DownloadResult, download
from .filenames import day_dir, parse_snodas_filename
from .products import Product
from .stats import Basin, BasinStats, Units, basin_stats
from .upload import upload_files

log = logging.getLogger(__name__)


def find_raster(day: date, data_dir: Path, masked: bool, product: Product, source: str | None) -> Path | None:
    """Find the converted grid for a product and day (the clipped copy for `source`, or the full grid)."""
    folder = day_dir(data_dir, day, masked)
    if not folder.exists():
        return None
    wanted_suffixes = {f"_{source}{ext}" if source else ext for ext in EXTENSIONS.values()}
    for path in sorted(folder.iterdir()):
        try:
            info = parse_snodas_filename(path)
        except ValueError:
            continue
        if info.suffix in wanted_suffixes and info.product == product:
            return path
    return None


def compute_stats(
    days: list[date],
    data_dir: Path,
    basins: list[Basin],
    products: list[Product],
    units: Units,
    masked: bool = True,
    progress: bool = True,
    workers: int = 1,
) -> list[BasinStats]:
    """
    Compute statistics for every basin, product and day that has converted data. `workers` > 1 computes them in
    separate processes.
    """
    tasks = []
    for day in days:
        for product in products:
            for basin in basins:
                raster = find_raster(day, data_dir, masked, product, basin.source)
                if raster is None:
                    log.info("%s %s: no converted grid for basin '%s'", day, product.key, basin.name)
                    continue
                tasks.append((raster, basin, product, day, units))

    bar = tqdm(total=len(tasks), desc="Statistics", unit="stat", disable=None if progress else True)
    results = []
    if workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for future in as_completed([pool.submit(basin_stats, *task) for task in tasks]):
                results.append(future.result())
                bar.update()
    else:
        for task in tasks:
            results.append(basin_stats(*task))
            bar.update()
    bar.close()
    return sorted(results, key=lambda r: (r.day, r.product, r.basin))


def day_is_converted(cfg: Config, day: date) -> bool:
    """True when every product's outputs (each clip region, plus the full grid if kept) exist for a day."""
    sources = [c.name for c in cfg.clips] + ([None] if cfg.keep_full_extent or not cfg.clips else [])
    return all(find_raster(day, cfg.data_dir, cfg.masked, p, s) is not None for p in cfg.products for s in sources)


@dataclass
class RunSummary:
    """What a run did."""

    downloads: list[DownloadResult] = field(default_factory=list)
    converted: list[Path] = field(default_factory=list)
    stats: list[BasinStats] = field(default_factory=list)
    tables: list[Path] = field(default_factory=list)
    uploaded: list[str] = field(default_factory=list)

    @property
    def failed_downloads(self) -> list[DownloadResult]:
        return [d for d in self.downloads if d.status == "error"]


def run(cfg: Config, days: list[date], progress: bool = True, overwrite: bool = False) -> RunSummary:
    """
    Run the full workflow for `days` using the settings in `cfg`.

    Days that are already fully converted aren't downloaded again (SNODAS data doesn't change after it's published)
    unless `overwrite` is set; their statistics are still recomputed.
    """
    summary = RunSummary()
    to_fetch = days if overwrite else [d for d in days if not day_is_converted(cfg, d)]
    done = sorted(set(days) - set(to_fetch))
    summary.downloads = [DownloadResult(d, "exists") for d in done]
    summary.downloads += download(to_fetch, cfg.data_dir, cfg.masked, overwrite=overwrite, workers=cfg.workers, progress=progress)
    summary.downloads.sort(key=lambda r: r.day)
    summary.converted = convert(
        days,
        cfg.data_dir,
        masked=cfg.masked,
        products=cfg.products,
        fmt=cfg.format,
        regions=cfg.clips,
        keep_raw=cfg.keep_raw,
        keep_full_extent=cfg.keep_full_extent,
        overwrite=overwrite,
        progress=progress,
        workers=cfg.convert_workers,
    )
    if cfg.basins:
        summary.stats = compute_stats(
            days, cfg.data_dir, cfg.basins, cfg.stat_products, cfg.units, cfg.masked, progress, cfg.stats_workers
        )
        if summary.stats:
            units = {p.key: cfg.units.labels(p) for p in cfg.stat_products}
            summary.tables = store.save(summary.stats, cfg.output_dir, units, cfg.export_formats)

    if cfg.upload:
        up = cfg.upload
        if up.stats and summary.tables:
            summary.uploaded += upload_files(
                summary.tables, cfg.output_dir, up.bucket, f"{up.prefix}/stats", up.public, endpoint_url=up.endpoint_url, region=up.region
            )
        if up.rasters and summary.converted:
            summary.uploaded += upload_files(
                summary.converted, cfg.data_dir, up.bucket, f"{up.prefix}/grids", up.public, endpoint_url=up.endpoint_url, region=up.region
            )

    if cfg.cleanup_after_run:
        if summary.failed_downloads:
            log.warning("Skipping cleanup because some downloads failed")
        else:
            for day in days:
                folder = day_dir(cfg.data_dir, day, cfg.masked)
                if folder.exists():
                    shutil.rmtree(folder)
                # remove the now-empty DD, MM and YYYY folders
                for parent in (folder.parent, folder.parent.parent, folder.parent.parent.parent):
                    try:
                        parent.rmdir()
                    except OSError:
                        break
    return summary
