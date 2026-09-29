"""Band / Channel Compatibility (task brief section 6).

Band identity comes ONLY from the raster's own band descriptions / band tags
/ colour interpretation -- never from a filename, and never guessed when a
TIFF carries no band names at all (an unnamed band stays "unidentified": a
workflow that requires a specific band then rejects it as BAND_MISSING
rather than assuming which band it might be).

Two kinds of band name, handled differently:

* **Self-describing names** ("red", "NIR", "VV", GDAL's Red/Green/Blue
  colour interpretation, ...) mean the same thing whatever the sensor --
  `GENERIC_BAND_ALIASES`, applied to every image.
* **Sensor-specific band IDs** ("B04", "B8A", ...) mean different things on
  different missions (Sentinel-2 B8 = NIR, Landsat 8 B8 = panchromatic).
  They are interpreted ONLY for Sentinel-2 (`SENSOR_BAND_MAPS`), including a
  positional fallback for unnamed 13 / 12 / 4-band files. For any other
  sensor they stay raw: "B4" is never assumed to be red.
* **Cartosat** is addressed by raster index from `cartosat_bands.py`'s
  config, never by names.
* **Sentinel-1 / RISAT get no band validation** (per scope): self-describing
  polarisation names are still READ (they tell modality), but no workflow
  checks them.

`positional_band_issues` is what enforces "VV -> VV and VH -> VH": for a
multi-image workflow that requires the SAME band at every position (e.g.
SAR change detection), an image that has a *different*, identifiable band
instead of the required one is a BAND_MISMATCH (it IS SAR, just the wrong
polarization) -- an image with no identifiable band at all is BAND_MISSING
(nothing to compare).
"""
from __future__ import annotations

import re

from app.validation import cartosat_bands
from app.validation.errors import BAND_MISMATCH, BAND_MISSING, ValidationIssue
from app.validation.schemas import RasterFacts
from app.validation.sensors import SensorFamily, SensorIdentification

SAR_POLARIZATIONS: tuple[str, ...] = ("vv", "vh", "hh", "hv")  # read for modality only; never validated

# canonical band name -> self-describing tokens (band description / tag
# value, case-insensitive). Sensor-independent by construction: no band IDs.
GENERIC_BAND_ALIASES: dict[str, tuple[str, ...]] = {
    "coastal": ("coastal", "coastal aerosol", "coastal_aerosol"),
    "blue": ("blue", "b"),
    "green": ("green", "g"),
    "red": ("red", "r"),
    "red_edge_1": ("red_edge_1", "red edge 1", "rededge1", "red-edge-1"),
    "red_edge_2": ("red_edge_2", "red edge 2", "rededge2", "red-edge-2"),
    "red_edge_3": ("red_edge_3", "red edge 3", "rededge3", "red-edge-3"),
    "nir": ("nir", "near-infrared", "near infrared", "nearinfrared"),
    "nir_narrow": ("nir_narrow", "narrow nir", "nir narrow", "nir-narrow"),
    "water_vapour": ("water_vapour", "water vapour", "water vapor", "water_vapor"),
    "cirrus": ("cirrus",),
    "swir1": ("swir1", "swir-1", "swir 1", "swir_1"),
    "swir2": ("swir2", "swir-2", "swir 2", "swir_2"),
    "pan": ("pan", "panchromatic"),
    "vv": ("vv",),
    "vh": ("vh",),
    "hh": ("hh",),
    "hv": ("hv",),
}


def _band_id_table(pairs: dict[str, str]) -> dict[str, str]:
    """{"4": "red"} -> accepts "b4", "b04" (and "b8a"/"b08a")."""
    table: dict[str, str] = {}
    for number, canonical in pairs.items():
        table[f"b{number}"] = canonical
        table[f"b{number.zfill(2) if number.isdigit() else '0' + number}"] = canonical
    return table


# Sensor-specific band-ID tables -- Sentinel-2 only. Only an identified
# Sentinel-2 file's descriptions are read through it.
SENSOR_BAND_MAPS: dict[SensorFamily, dict[str, str]] = {
    SensorFamily.SENTINEL_2: _band_id_table({
        "1": "coastal", "2": "blue", "3": "green", "4": "red",
        "5": "red_edge_1", "6": "red_edge_2", "7": "red_edge_3",
        "8": "nir", "8a": "nir_narrow", "9": "water_vapour", "10": "cirrus",
        "11": "swir1", "12": "swir2",
    }),
}

# Sentinel-2 band order for files whose bands carry NO names. Used only when
# the sensor is confirmed Sentinel-2 by evidence other than the filename, and
# the band count matches exactly.
S2_POSITIONAL_ORDER: dict[int, tuple[str, ...]] = {
    13: ("coastal", "blue", "green", "red", "red_edge_1", "red_edge_2", "red_edge_3", "nir", "nir_narrow",
         "water_vapour", "cirrus", "swir1", "swir2"),  # L1C: B1..B8, B8A, B9, B10, B11, B12
    12: ("coastal", "blue", "green", "red", "red_edge_1", "red_edge_2", "red_edge_3", "nir", "nir_narrow",
         "water_vapour", "swir1", "swir2"),  # L2A: same without B10
    4: ("blue", "green", "red", "nir"),  # B2, B3, B4, B8
}

# Required band -> bands that satisfy it (Sentinel-2 B8A is a NIR band too).
BAND_EQUIVALENTS: dict[str, tuple[str, ...]] = {"nir": ("nir", "nir_narrow")}

_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset(SAR_POLARIZATIONS),
    frozenset({"coastal", "blue", "green", "red", "red_edge_1", "red_edge_2", "red_edge_3", "nir", "nir_narrow",
               "water_vapour", "cirrus", "swir1", "swir2", "pan"}),
)

_COLOR_INTERP_ALIAS = {"red": "red", "green": "green", "blue": "blue"}

# Longest alias first, so "red edge 1" is never read as "red".
_GENERIC_WORD_ALIASES = sorted(
    ((alias, canonical) for canonical, aliases in GENERIC_BAND_ALIASES.items() for alias in aliases if len(alias) >= 2),
    key=lambda pair: len(pair[0]), reverse=True,
)


def _sensor_table(sensor: SensorIdentification | None) -> dict[str, str]:
    if sensor is None or not sensor.is_supported or sensor.family is None:
        return {}
    return dict(SENSOR_BAND_MAPS.get(sensor.family, {}))


def is_sentinel2(sensor: SensorIdentification | None) -> bool:
    return sensor is not None and sensor.is_supported and sensor.family == SensorFamily.SENTINEL_2


def _s2_positional(facts: RasterFacts, sensor: SensorIdentification | None) -> dict[str, int] | None:
    if not is_sentinel2(sensor) or sensor.source == "filename":
        return None
    if any(facts.band_descriptions):
        return None
    order = S2_POSITIONAL_ORDER.get(facts.band_count or 0)
    return {name: index for index, name in enumerate(order, start=1)} if order else None


def _match_band_token(text: str, sensor_table: dict[str, str]) -> str | None:
    token = (text or "").strip().lower()
    if not token:
        return None
    # 1. exact: a sensor band ID, then a self-describing name
    if token in sensor_table:
        return sensor_table[token]
    for canonical, aliases in GENERIC_BAND_ALIASES.items():
        if token in aliases:
            return canonical
    # 2. inside longer text ("VV polarisation", "Band 4 - Red", "B04 (665 nm)")
    for pol in SAR_POLARIZATIONS:
        if re.search(rf"\b{pol}\b", token):
            return pol
    for alias, canonical in _GENERIC_WORD_ALIASES:
        if re.search(rf"\b{re.escape(alias)}\b", token):
            return canonical
    for band_id in sorted(sensor_table, key=len, reverse=True):
        if re.search(rf"\b{re.escape(band_id)}\b", token):
            return sensor_table[band_id]
    return None


def detect_named_bands(facts: RasterFacts, sensor: SensorIdentification | None) -> dict[str, int]:
    """canonical band name -> 1-based band index. `sensor` is REQUIRED (pass
    None explicitly when there is none) and dispatches:

    * Sentinel-2 -> its band-ID table (+ self-describing names), or the
      positional fallback for an unnamed 13 / 12 / 4-band file;
    * Cartosat -> the index-based config in cartosat_bands.py, nothing else;
    * anything else (S1, RISAT, unknown, unsupported) -> self-describing
      names only (e.g. "VV", "red"); "B4" etc. stay raw.
    Never invents a name for an undescribed band."""
    if cartosat_bands.is_cartosat(sensor):
        return cartosat_bands.detect_bands(sensor, facts)
    positional = _s2_positional(facts, sensor)
    if positional is not None:
        return positional
    sensor_table = _sensor_table(sensor)
    found: dict[str, int] = {}

    # 1. Band descriptions
    for index, description in enumerate(facts.band_descriptions, start=1):
        if not description:
            continue
        canonical = _match_band_token(description, sensor_table)
        if canonical and canonical not in found:
            found[canonical] = index

    # 2. Per-band tags (src.tags(i))
    if facts.band_tags:
        for index, btags in enumerate(facts.band_tags, start=1):
            if not btags or index in found.values():
                continue
            for key in ("POLARIZATION", "POLARISATION", "POL", "NAME", "BAND_NAME", "DESCRIPTION", "BAND"):
                val = btags.get(key) or btags.get(key.lower()) or btags.get(key.capitalize())
                if val:
                    canonical = _match_band_token(str(val), sensor_table)
                    if canonical and canonical not in found:
                        found[canonical] = index
                        break
            if index not in found.values():
                for val in btags.values():
                    canonical = _match_band_token(str(val), sensor_table)
                    if canonical and canonical not in found:
                        found[canonical] = index
                        break

    # 3. Dataset-level tags (e.g. single-band SAR GeoTIFF with POLARIZATION tag)
    if facts.tags and facts.band_count == 1 and 1 not in found.values():
        for key in ("POLARIZATION", "POLARISATION", "POLARIZATION_CHANNELS", "POL", "BAND", "BAND_NAME", "DESCRIPTION"):
            val = facts.tags.get(key) or facts.tags.get(key.lower())
            if val:
                canonical = _match_band_token(str(val), sensor_table)
                if canonical and canonical not in found:
                    found[canonical] = 1
                    break

    # 4. Red/green/blue via GDAL's own colour-interpretation tag (real
    # GeoTIFF RGB rasters usually carry this even with no band names).
    for index, interp in enumerate(facts.color_interpretation, start=1):
        canonical = _COLOR_INTERP_ALIAS.get(str(interp).lower())
        if canonical and canonical not in found and index not in found.values():
            found[canonical] = index

    return found


def band_identification_source(facts: RasterFacts, sensor: SensorIdentification | None) -> str | None:
    """How bands were identified: "cartosat_config", "s2_positional", "names" or None."""
    if not detect_named_bands(facts, sensor):
        return None
    if cartosat_bands.is_cartosat(sensor):
        return "cartosat_config"
    if _s2_positional(facts, sensor) is not None:
        return "s2_positional"
    return "names"


def duplicate_bands(facts: RasterFacts, sensor: SensorIdentification | None) -> list[str]:
    """Canonical bands that more than one raster band claims to be (e.g. two
    bands both described "B04") -- a Sentinel-2 file must not repeat a band."""
    table = _sensor_table(sensor)
    seen: dict[str, int] = {}
    for description in facts.band_descriptions:
        canonical = _match_band_token(description, table) if description else None
        if canonical:
            seen[canonical] = seen.get(canonical, 0) + 1
    return sorted(name for name, count in seen.items() if count > 1)


def unrecognised_band_names(facts: RasterFacts, sensor: SensorIdentification | None = None) -> list[str]:
    """Band descriptions present in the file but not interpreted -- e.g. "B4"
    on an unknown sensor, or RISAT compact-pol "RH". Reported, never guessed."""
    if cartosat_bands.is_cartosat(sensor):
        return [d for d in facts.band_descriptions if d] if not cartosat_bands.layout_matches(sensor, facts) else []
    table = _sensor_table(sensor)
    return [d for d in facts.band_descriptions if d and _match_band_token(d, table) is None]


def ordered_bands(detected: dict[str, int]) -> list[str]:
    """Identified bands in the file's own band order -- what preprocessing
    would receive, so nothing downstream relies on set/dict iteration order."""
    return [name for name, _ in sorted(detected.items(), key=lambda item: item[1])]


def has_band(detected: dict[str, int], band: str) -> bool:
    return any(candidate in detected for candidate in BAND_EQUIVALENTS.get(band, (band,)))


def _family_of(band: str) -> frozenset[str] | None:
    return next((family for family in _FAMILIES if band in family), None)


def _missing_message(band: str, facts: RasterFacts, sensor: SensorIdentification | None) -> str:
    message = f"Required band '{band}' was not found in this image."
    if band == "nir":
        message = "Required band 'nir' (near-infrared) was not found in this image; a NIR band is required."
    if cartosat_bands.is_cartosat(sensor) and not cartosat_bands.layout_matches(sensor, facts):
        return message + " Cartosat product/band layout not recognised."
    raw = unrecognised_band_names(facts, sensor)
    if raw and (sensor is None or not sensor.is_supported):
        return message + (
            f" Band names {raw[:6]} can't be interpreted without a known sensor "
            "(Sentinel-1, Sentinel-2, Cartosat or RISAT)."
        )
    return message


def missing_band_issues(
    facts: RasterFacts, required: list[str], *, input_label: str, sensor: SensorIdentification | None = None
) -> tuple[list[ValidationIssue], dict[str, int]]:
    """BAND_MISSING for each band in `required` this image doesn't have.
    Returns the issues plus the full set of bands the image DOES have, so a
    caller doing cross-image comparison doesn't need to re-detect them."""
    detected = detect_named_bands(facts, sensor)
    issues = [
        ValidationIssue.of(BAND_MISSING, _missing_message(band, facts, sensor), input=input_label)
        for band in required
        if not has_band(detected, band)
    ]
    return issues, detected


def positional_band_issues(
    images: list[tuple[str, RasterFacts]],
    required_bands: list[list[str]],
    *,
    workflow_label: str,
    sensors: list[SensorIdentification | None] | None = None,
) -> list[ValidationIssue]:
    """`required_bands[i]` = the bands image `images[i]` must have. When every
    position requires the exact same single band (the VV<->VV / VH<->VH
    rule), a position missing it gets BAND_MISMATCH -- naming what it has
    instead -- if it has a same-family band, else the plain BAND_MISSING."""
    issues: list[ValidationIssue] = []
    sensors = sensors or [None] * len(images)
    same_band_everywhere = (
        len(required_bands) > 1
        and all(len(req) == 1 for req in required_bands)
        and len({req[0] for req in required_bands}) == 1
    )
    required_single = required_bands[0][0] if same_band_everywhere else None

    for (label, facts), required, sensor in zip(images, required_bands, sensors):
        band_issues, detected = missing_band_issues(facts, required, input_label=label, sensor=sensor)
        if not band_issues:
            continue
        if same_band_everywhere and not has_band(detected, required_single):
            family = _family_of(required_single)
            mismatch = next((b for b in ordered_bands(detected) if family and b in family), None)
            if mismatch:
                issues.append(ValidationIssue.of(
                    BAND_MISMATCH,
                    f"{workflow_label} requires '{required_single.upper()}' input for every image; "
                    f"{label} provides '{mismatch.upper()}' instead.",
                    input=label,
                ))
                continue
        issues.extend(band_issues)
    return issues
