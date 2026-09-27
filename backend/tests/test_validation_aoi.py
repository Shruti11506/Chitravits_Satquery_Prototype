"""Basic AOI validation (task brief section 10, 18)."""
from app.validation import aoi_validator
from app.validation.errors import AOI_OUTSIDE_IMAGE, INVALID_AOI
from app.validation.schemas import RasterFacts

VALID_POLYGON = {"type": "Polygon", "coordinates": [[[77.5, 13.0], [77.6, 13.0], [77.6, 13.1], [77.5, 13.1], [77.5, 13.0]]]}
# A bowtie -- crosses itself, not a valid simple polygon.
SELF_INTERSECTING = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}
EMPTY_POLYGON = {"type": "Polygon", "coordinates": []}
OUT_OF_RANGE_COORDS = {"type": "Polygon", "coordinates": [[[200, 13.0], [201, 13.0], [201, 14.0], [200, 14.0], [200, 13.0]]]}

IMAGE_BOUNDS = (77.5, 13.0, 77.6, 13.1)  # west, south, east, north -- matches VALID_POLYGON
FAR_AWAY_BOUNDS = (10.0, 10.0, 10.1, 10.1)


def test_valid_polygon_parses():
    geom, issue = aoi_validator.parse_aoi(VALID_POLYGON)
    assert issue is None
    assert geom is not None and geom.is_valid


def test_self_intersecting_polygon_is_invalid():
    geom, issue = aoi_validator.parse_aoi(SELF_INTERSECTING)
    assert geom is None
    assert issue.code == INVALID_AOI


def test_empty_geometry_is_invalid():
    geom, issue = aoi_validator.parse_aoi(EMPTY_POLYGON)
    assert geom is None
    assert issue.code == INVALID_AOI


def test_out_of_range_coordinates_are_invalid():
    geom, issue = aoi_validator.parse_aoi(OUT_OF_RANGE_COORDS)
    assert geom is None
    assert issue.code == INVALID_AOI


def test_malformed_geometry_type_is_invalid():
    geom, issue = aoi_validator.parse_aoi({"type": "NotAThing", "coordinates": [1, 2]})
    assert geom is None
    assert issue.code == INVALID_AOI


def test_aoi_intersecting_image_bounds_passes():
    geom, _ = aoi_validator.parse_aoi(VALID_POLYGON)
    facts = RasterFacts(bounds=IMAGE_BOUNDS)
    assert aoi_validator.intersection_issues(geom, [("scene", facts)]) == []


def test_aoi_outside_image_bounds_is_rejected():
    geom, _ = aoi_validator.parse_aoi(VALID_POLYGON)
    facts = RasterFacts(bounds=FAR_AWAY_BOUNDS)
    issues = aoi_validator.intersection_issues(geom, [("scene", facts)])
    assert [i.code for i in issues] == [AOI_OUTSIDE_IMAGE]


def test_image_with_no_bounds_is_skipped_not_rejected():
    """An image the AOI check has nothing to compare against (e.g. a JPEG a
    non-geospatial workflow allowed) is silently skipped here --
    geospatial_validator is what rejects it, separately, when relevant."""
    geom, _ = aoi_validator.parse_aoi(VALID_POLYGON)
    facts = RasterFacts(bounds=None)
    assert aoi_validator.intersection_issues(geom, [("scene", facts)]) == []
