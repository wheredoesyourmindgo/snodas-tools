"""
Quick looks at SNODAS grids and statistics tables: a summary, a color map drawn in the terminal, a terminal chart,
or (with the `plot` extra) a PNG / interactive matplotlib window.
"""

import math
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import xarray as xr

from .convert import ensure_spatial, open_raster
from .geometry import WGS84, load_shapes

# viridis, sampled at 0, 0.25, 0.5, 0.75, 1
_STOPS = np.array([(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)], dtype=float)
_ASCII_RAMP = " .:-=+*#%@"


def describe(da: xr.DataArray) -> dict:
    """Summary facts about a grid."""
    da = ensure_spatial(da)
    values = da.values
    valid = np.isfinite(values)
    west, south, east, north = da.rio.bounds()
    res_x, res_y = da.rio.resolution()
    info = {
        "name": da.name,
        "description": da.attrs.get("long_name", ""),
        "units": da.attrs.get("units", ""),
        "date": da.attrs.get("date", ""),
        "size": f"{da.rio.width} x {da.rio.height} cells",
        "resolution": f"{abs(res_x):.6f} x {abs(res_y):.6f} degrees",
        "bounds": f"W {west:.4f}, S {south:.4f}, E {east:.4f}, N {north:.4f}",
        "crs": str(da.rio.crs),
        "valid cells": f"{int(valid.sum()):,} of {values.size:,}",
    }
    if valid.any():
        info.update(
            {
                "min": float(np.nanmin(values)),
                "mean": float(np.nanmean(values)),
                "max": float(np.nanmax(values)),
            }
        )
    return info


def _color_mode(color: bool | None) -> str:
    """'truecolor', '256' or 'none'."""
    if color is False or os.environ.get("NO_COLOR"):
        return "none"
    if color is None and not sys.stdout.isatty():
        return "none"
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return "truecolor"
    return "256"


def _rgb(t: float) -> tuple[int, int, int]:
    t = min(max(t, 0.0), 1.0) * (len(_STOPS) - 1)
    i = min(int(t), len(_STOPS) - 2)
    rgb = _STOPS[i] + (_STOPS[i + 1] - _STOPS[i]) * (t - i)
    return tuple(int(round(v)) for v in rgb)


def _ansi(rgb: tuple[int, int, int], mode: str, background: bool) -> str:
    layer = 48 if background else 38
    if mode == "truecolor":
        return f"\x1b[{layer};2;{rgb[0]};{rgb[1]};{rgb[2]}m"
    r, g, b = (round(v / 255 * 5) for v in rgb)
    return f"\x1b[{layer};5;{16 + 36 * r + 6 * g + b}m"


def _block_mean(values: np.ndarray, out_rows: int, out_cols: int) -> np.ndarray:
    """Shrink a grid by averaging blocks of cells (ignoring NaN)."""
    rows, cols = values.shape
    r_edges = np.linspace(0, rows, out_rows + 1).astype(int)
    c_edges = np.linspace(0, cols, out_cols + 1).astype(int)
    out = np.full((out_rows, out_cols), np.nan)
    for i in range(out_rows):
        r0, r1 = r_edges[i], max(r_edges[i + 1], r_edges[i] + 1)
        for j in range(out_cols):
            c0, c1 = c_edges[j], max(c_edges[j + 1], c_edges[j] + 1)
            block = values[r0:r1, c0:c1]
            if np.isfinite(block).any():
                out[i, j] = np.nanmean(block)
    return out


def render_terminal(da: xr.DataArray, width: int = 80, color: bool | None = None, vmin=None, vmax=None) -> str:
    """
    Draw a grid as text. With color, each character shows two cells (upper and lower half-blocks); without color,
    an ASCII brightness ramp is used.
    """
    da = ensure_spatial(da)
    values = da.values.astype(float)
    if not np.isfinite(values).any():
        return "(no valid data to draw)"
    rows, cols = values.shape
    width = max(10, min(width, cols))
    # correct for longitude degrees being shorter than latitude degrees away from the equator
    lat_mid = float(da[da.rio.y_dim].mean()) if da.rio.crs and da.rio.crs.is_geographic else 0.0
    aspect = (rows / cols) / max(math.cos(math.radians(lat_mid)), 0.2)
    mode = _color_mode(color)
    pixel_rows = max(2, round(width * aspect)) if mode != "none" else max(1, round(width * aspect / 2))
    pixel_rows += pixel_rows % 2 if mode != "none" else 0
    small = _block_mean(values, pixel_rows, width)

    # robust limits, so a few extreme cells (e.g. glaciers) don't wash out the rest of the map
    lo = float(np.nanpercentile(small, 1)) if vmin is None else vmin
    hi = float(np.nanpercentile(small, 99)) if vmax is None else vmax
    span = (hi - lo) or 1.0
    norm = (small - lo) / span

    lines = []
    if mode == "none":
        for row in norm:
            lines.append("".join(" " if not np.isfinite(v) else _ASCII_RAMP[min(int(v * len(_ASCII_RAMP)), len(_ASCII_RAMP) - 1)] for v in row))
    else:
        reset = "\x1b[0m"
        for top, bottom in zip(norm[0::2], norm[1::2], strict=True):
            chars = []
            for t, b in zip(top, bottom, strict=True):
                if np.isfinite(t) and np.isfinite(b):
                    chars.append(_ansi(_rgb(t), mode, False) + _ansi(_rgb(b), mode, True) + "▀" + reset)
                elif np.isfinite(t):
                    chars.append(_ansi(_rgb(t), mode, False) + "▀" + reset)
                elif np.isfinite(b):
                    chars.append(_ansi(_rgb(b), mode, False) + "▄" + reset)
                else:
                    chars.append(" ")
            lines.append("".join(chars))

    units = da.attrs.get("units", "")
    if mode == "none":
        legend = f"low '{_ASCII_RAMP[1]}' {lo:.3g} ... high '{_ASCII_RAMP[-1]}' {hi:.3g} {units}"
    else:
        bar = "".join(_ansi(_rgb(i / 19), mode, True) + " " for i in range(20)) + "\x1b[0m"
        legend = f"{lo:.3g} {bar} {hi:.3g} {units}"
    title = " ".join(str(x) for x in (da.attrs.get("long_name", da.name), da.attrs.get("date", "")) if x)
    return "\n".join([title, *lines, legend])


def crop_to_shapes(da: xr.DataArray, shapes: list[str | Path], pad_cells: int = 2) -> xr.DataArray:
    """Crop a grid to the bounding box of some shapes (plus a few cells of padding)."""
    west, south, east, north = load_shapes(shapes).total_bounds
    rx, ry = (abs(r) for r in da.rio.resolution())
    return da.rio.clip_box(west - pad_cells * rx, south - pad_cells * ry, east + pad_cells * rx, north + pad_cells * ry, crs=WGS84)


def plot_map(da: xr.DataArray, shapes: list[str | Path] | None = None, png: str | Path | None = None, show: bool = False):
    """Plot a grid with matplotlib, optionally outlining shapes. Saves to `png` and/or opens a window."""
    try:
        import matplotlib  # pylint: disable=import-outside-toplevel

        if not show:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel
    except ImportError:
        raise RuntimeError('Plotting needs matplotlib: pip install "snodas-tools[plot]"') from None

    fig, ax = plt.subplots(figsize=(9, 6))
    # robust=True uses the 2nd-98th percentiles for the color scale, so a few extreme cells don't wash out the map
    da.plot(ax=ax, cmap="viridis", robust=True, cbar_kwargs={"label": f"{da.name} ({da.attrs.get('units', '')})"})
    if shapes:
        load_shapes(shapes).boundary.plot(ax=ax, color="white", linewidth=1)
    ax.set_title(" ".join(str(x) for x in (da.attrs.get("long_name", da.name), da.attrs.get("date", "")) if x))
    lat_mid = float(da[da.rio.y_dim].mean())
    ax.set_aspect(1 / max(math.cos(math.radians(lat_mid)), 0.2))
    fig.tight_layout()
    if png:
        fig.savefig(png, dpi=150)
    if show:
        plt.show()
    plt.close(fig)


def render_chart(series: pd.Series, width: int = 72, height: int = 12, title: str = "", units: str = "") -> str:
    """Draw a time series as a column chart in the terminal."""
    series = series.dropna()
    if series.empty:
        return "(no data to chart)"
    # one column per value when there are fewer values than columns; otherwise average values into columns
    width = max(1, min(width, len(series)))
    buckets = np.array_split(series.to_numpy(dtype=float), width)
    values = np.array([b.mean() for b in buckets])
    lo, hi = min(0.0, values.min()), values.max()
    span = (hi - lo) or 1.0
    levels = (values - lo) / span * height * 8  # eighths of a row
    eighths = " ▁▂▃▄▅▆▇█"
    rows = []
    for row in range(height, 0, -1):
        floor = (row - 1) * 8
        line = "".join(eighths[int(min(max(lv - floor, 0), 8))] for lv in levels)
        rows.append(line)
    label_w = max(len(f"{hi:,.0f}"), len(f"{lo:,.0f}"))
    out = [title] if title else []
    for i, line in enumerate(rows):
        label = f"{hi:,.0f}" if i == 0 else (f"{lo:,.0f}" if i == len(rows) - 1 else "")
        out.append(f"{label:>{label_w}} │{line}")
    first, last = series.index[0], series.index[-1]
    out.append(f"{'':>{label_w}} └{'─' * width}")
    first, last = f"{first:%Y-%m-%d}" if hasattr(first, "strftime") else str(first), f"{last:%Y-%m-%d}" if hasattr(last, "strftime") else str(last)
    out.append(f"{'':>{label_w}}  {first}{' ' * max(1, width - len(first) - len(last))}{last}")
    if units:
        out.append(f"{'':>{label_w}}  units: {units}")
    return "\n".join(out)


def open_any(path: str | Path) -> xr.DataArray:
    """Open a converted grid (NetCDF/GeoTIFF) for previewing."""
    return open_raster(path)
