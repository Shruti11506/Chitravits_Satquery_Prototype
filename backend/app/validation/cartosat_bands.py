"""Cartosat band configuration.

Cartosat bands are addressed by RASTER INDEX from this config -- never by
Sentinel-2 style "B4"/"B8" names. The product type (MX / PAN) comes from
the identified sensor's product (the `sensor` / `source` fields, TIFF tags
or filename; see sensors.py); only when that is missing is it inferred from
the band count (4 -> MX, 1 -> PAN), and then recorded as `source="band_count"`.

A band count that doesn't match the product's layout gets NO interpretation,
so band-index workflows (NDVI) fail cleanly rather than guess.
"""
from __future__ import annotations

from app.validation.schemas import RasterFacts
from app.validation.sensors import SensorFamily, SensorIdentification

CARTOSAT_BAND_CONFIG: dict[str, dict] = {
    "MX": {  # multispectral (Cartosat-2 series / Cartosat-3 MX): 4 bands
        "band_count": 4,
        "bands": {1: "blue", 2: "green", 3: "red", 4: "nir"},  # 1-based raster band index
        # nominal ranges (um): blue 0.45-0.52, green 0.52-0.59, red 0.62-0.68, nir 0.77-0.86
    },
    "PAN": {
        "band_count": 1,
        "bands": {1: "pan"},
    },
}
# TODO(team): confirm band order against the product's own META / band-info file
# for the exact Cartosat products we use before relying on it for NDVI.

_PRODUCT_BY_LABEL = {"Cartosat MX": "MX", "Cartosat PAN": "PAN"}
_PRODUCT_BY_BAND_COUNT = {config["band_count"]: product for product, config in CARTOSAT_BAND_CONFIG.items()}


def is_cartosat(sensor: SensorIdentification | None) -> bool:
    return sensor is not None and sensor.is_supported and sensor.family == SensorFamily.CARTOSAT


def product_of(sensor: SensorIdentification, facts: RasterFacts) -> tuple[str | None, str | None]:
    """(product, source): "MX" / "PAN" and which evidence decided it, or (None, None)."""
    product = _PRODUCT_BY_LABEL.get(sensor.product or "")
    if product:
        return product, sensor.source
    inferred = _PRODUCT_BY_BAND_COUNT.get(facts.band_count or 0)
    return (inferred, "band_count") if inferred else (None, None)


def layout_matches(sensor: SensorIdentification, facts: RasterFacts) -> bool:
    product, _ = product_of(sensor, facts)
    return product is not None and facts.band_count == CARTOSAT_BAND_CONFIG[product]["band_count"]


def detect_bands(sensor: SensorIdentification, facts: RasterFacts) -> dict[str, int]:
    """canonical band -> 1-based index from the config, or {} when the
    product or its band layout isn't recognised."""
    if not layout_matches(sensor, facts):
        return {}
    product, _ = product_of(sensor, facts)
    return {name: index for index, name in CARTOSAT_BAND_CONFIG[product]["bands"].items()}
