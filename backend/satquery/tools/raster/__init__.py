"""Raster support for deterministic tools: band resolution, I/O, statistics."""

from satquery.tools.raster.bands import BandResolver, MissingBandError
from satquery.tools.raster.io import (
    RasterMeta,
    meta_of,
    open_raster,
    pixel_area_m2,
    read_band,
    write_raster,
)
from satquery.tools.raster.stats import mask_area, raster_stats

__all__ = [
    "BandResolver",
    "MissingBandError",
    "RasterMeta",
    "meta_of",
    "open_raster",
    "read_band",
    "write_raster",
    "pixel_area_m2",
    "raster_stats",
    "mask_area",
]
