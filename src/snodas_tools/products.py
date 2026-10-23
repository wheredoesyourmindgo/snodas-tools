"""
SNODAS product definitions.

Values come from the NSIDC SNODAS user guide (G02158): https://nsidc.org/data/g02158
Raw SNODAS grids are stored as 16-bit integers; dividing by `scale` gives the value in `units`.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    """A SNODAS product that can be converted and summarized."""

    key: str
    code: int
    label: str
    units: str  # units after dividing the raw value by `scale`
    scale: float
    kind: str  # "depth" (a water/snow depth that can be turned into a volume) or "temperature"
    vertical_code: str | None = None  # distinguishes products that share a code (liquid vs. solid precipitation)
    # SNODAS leaves these blank (no data) wherever there is no snowpack, rather than writing 0. For volumes and
    # averages a blank cell means "none", so it's counted as 0.
    blank_means_zero: bool = False


PRODUCTS: dict[str, Product] = {
    p.key: p
    for p in [
        Product("swe", 1034, "Snow water equivalent", "m", 1000, "depth"),
        Product("depth", 1036, "Snow depth", "m", 1000, "depth"),
        Product("temp", 1038, "Snowpack average temperature", "K", 1, "temperature"),
        Product("sublimation_blowing", 1039, "Blowing snow sublimation (24 hr total)", "m", 100000, "depth", None, True),
        Product("melt", 1044, "Snow melt runoff at the base of the snowpack (24 hr total)", "m", 100000, "depth", None, True),
        Product("sublimation", 1050, "Snowpack sublimation (24 hr total)", "m", 100000, "depth", None, True),
        Product("precip_liquid", 1025, "Liquid precipitation (24 hr total)", "m", 10000, "depth", "lL00"),
        Product("precip_solid", 1025, "Solid precipitation (24 hr total)", "m", 10000, "depth", "lL01"),
    ]
}


def get_product(key: str) -> Product:
    """Look up a product by key (e.g. "swe"), raising a helpful error for unknown keys."""
    try:
        return PRODUCTS[key]
    except KeyError:
        raise ValueError(f"Unknown SNODAS product '{key}'. Valid products: {', '.join(PRODUCTS)}") from None


def product_for_file(product_code: int, vertical_code: str | None) -> Product | None:
    """Return the product matching a parsed SNODAS filename, or None if it isn't one we know about."""
    for product in PRODUCTS.values():
        if product.code != product_code:
            continue
        if product.vertical_code is None or (vertical_code or "").startswith(product.vertical_code):
            return product
    return None
