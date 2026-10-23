"""
Loading area-of-interest shapes and measuring them.

Areas and buffers are computed in a Lambert azimuthal equal-area projection centered on each shape, so they are
accurate anywhere SNODAS covers (no state plane or UTM zone has to be chosen).
"""

from functools import lru_cache
from pathlib import Path

import geopandas as gpd
from pyproj import CRS

WGS84 = "EPSG:4326"


def _vector_path(path: str | Path) -> str:
    """
    Accept plain paths as well as 'archive.zip!inner/path.shp' (a file inside a zip), which GDAL reads as zip://.
    """
    text = str(path)
    if ".zip!" in text and not text.startswith(("zip://", "/vsizip/")):
        return "zip://" + text
    return text


def load_shapes(paths: str | Path | list[str | Path]) -> gpd.GeoDataFrame:
    """
    Load one or more vector files (GeoJSON, shapefile, GeoPackage, zipped shapefile, ...) and dissolve them into a
    single geometry in WGS84 (EPSG:4326).
    """
    if isinstance(paths, (str, Path)):
        paths = [paths]
    if not paths:
        raise ValueError("At least one shape file is required.")
    frames = []
    for path in paths:
        source = _vector_path(path)
        if not source.startswith("zip://") and not Path(source).exists():
            raise FileNotFoundError(f"Shape file not found: {path}")
        gdf = gpd.read_file(source)
        if gdf.empty:
            raise ValueError(f"Shape file has no features: {path}")
        if gdf.crs is None:
            raise ValueError(f"Shape file has no coordinate reference system (CRS): {path}")
        frames.append(gdf.to_crs(WGS84))
    merged = gpd.GeoDataFrame(geometry=[g.geometry.union_all() for g in frames], crs=WGS84)
    return gpd.GeoDataFrame(geometry=[merged.geometry.union_all()], crs=WGS84)


def equal_area_crs(gdf: gpd.GeoDataFrame) -> CRS:
    """A Lambert azimuthal equal-area CRS centered on the shape (units: meters)."""
    centroid = gdf.to_crs(WGS84).geometry.union_all().centroid
    return CRS.from_proj4(f"+proj=laea +lat_0={centroid.y:.6f} +lon_0={centroid.x:.6f} +datum=WGS84 +units=m +no_defs")


def area_m2(gdf: gpd.GeoDataFrame) -> float:
    """Total area of the shape in square meters."""
    return float(gdf.to_crs(equal_area_crs(gdf)).geometry.area.sum())


def buffer(gdf: gpd.GeoDataFrame, meters: float) -> gpd.GeoDataFrame:
    """Grow (or, with a negative distance, shrink) the shape by a distance in meters."""
    if not meters:
        return gdf
    laea = equal_area_crs(gdf)
    return gpd.GeoDataFrame(geometry=gdf.to_crs(laea).buffer(meters), crs=laea).to_crs(WGS84)


@lru_cache(maxsize=64)
def _load_cached(key: tuple[str, ...]) -> gpd.GeoDataFrame:
    return load_shapes(list(key))


def load_shapes_cached(paths: list[str | Path]) -> gpd.GeoDataFrame:
    """`load_shapes` with caching, for when the same shapes are used for many dates."""
    return _load_cached(tuple(str(p) for p in paths)).copy()
