"""Band / channel compatibility, incl. the VV<->VV / VH<->VH rule (sections 6, 18)."""
from app.validation import band_validator
from app.validation.errors import BAND_MISMATCH, BAND_MISSING
from app.validation.schemas import RasterFacts


def _facts(descriptions):
    return RasterFacts(format="GeoTIFF", width=10, height=10, band_count=len(descriptions), band_descriptions=descriptions)


def test_detects_named_bands_case_insensitively():
    assert band_validator.detect_named_bands(_facts(["Red", "GREEN", "blue", "NIR"])) == {"red": 1, "green": 2, "blue": 3, "nir": 4}


def test_undescribed_bands_are_not_guessed():
    assert band_validator.detect_named_bands(_facts(["", None, "unknown_tag"])) == {}


def test_red_green_blue_detected_via_colorinterp_when_undescribed():
    facts = RasterFacts(format="GeoTIFF", width=1, height=1, band_count=3, color_interpretation=["red", "green", "blue"])
    assert band_validator.detect_named_bands(facts) == {"red": 1, "green": 2, "blue": 3}


# ---- NDVI: Red + NIR (single image) --------------------------------------------


def test_ndvi_red_and_nir_present_passes():
    issues, _ = band_validator.missing_band_issues(_facts(["red", "nir"]), ["red", "nir"], input_label="x")
    assert issues == []


def test_ndvi_rejects_rgb_only_missing_nir():
    issues, _ = band_validator.missing_band_issues(_facts(["red", "green", "blue"]), ["red", "nir"], input_label="x")
    assert [i.code for i in issues] == [BAND_MISSING]
    assert "nir" in issues[0].message.lower()


# ---- SAR VV / VH single-image analysis -----------------------------------------


def test_sar_vv_present_passes():
    issues, _ = band_validator.missing_band_issues(_facts(["VV"]), ["vv"], input_label="x")
    assert issues == []


def test_sar_vh_only_rejected_for_a_vv_workflow():
    issues, _ = band_validator.missing_band_issues(_facts(["VH"]), ["vv"], input_label="x")
    assert [i.code for i in issues] == [BAND_MISSING]


# ---- Positional (T1/T2) checks: VV -> VV, VH -> VH, no mixing ------------------


def test_vv_change_with_vv_both_times_is_valid():
    images = [("T1", _facts(["VV"])), ("T2", _facts(["VV"]))]
    assert band_validator.positional_band_issues(images, [["vv"], ["vv"]], workflow_label="SAR VV change analysis") == []


def test_vh_change_with_vh_both_times_is_valid():
    images = [("T1", _facts(["VH"])), ("T2", _facts(["VH"]))]
    assert band_validator.positional_band_issues(images, [["vh"], ["vh"]], workflow_label="SAR VH change analysis") == []


def test_mixed_vv_then_vh_is_a_band_mismatch_not_missing():
    images = [("T1", _facts(["VV"])), ("T2", _facts(["VH"]))]
    issues = band_validator.positional_band_issues(images, [["vv"], ["vv"]], workflow_label="SAR VV change analysis")
    assert len(issues) == 1
    assert issues[0].code == BAND_MISMATCH
    assert issues[0].input == "T2"
    assert "VV" in issues[0].message and "VH" in issues[0].message


def test_missing_band_entirely_stays_band_missing_not_mismatch():
    images = [("T1", _facts(["VV"])), ("T2", _facts([]))]  # T2 has no identifiable band at all
    issues = band_validator.positional_band_issues(images, [["vv"], ["vv"]], workflow_label="SAR VV change analysis")
    assert len(issues) == 1
    assert issues[0].code == BAND_MISSING
    assert issues[0].input == "T2"
