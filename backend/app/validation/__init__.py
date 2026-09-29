"""Input Validation: the gate between an uploaded image + a requested
workflow, and whatever runs on it next.

    User Input -> Input Validation -> VALID -> Preprocessing / Analysis
                                    -> REJECT -> a structured reason

This package answers exactly one question -- "is this input structurally
and semantically suitable for the requested SatQuery workflow?" -- and
nothing past it. It does not implement, call, or approximate any of:
VLMs, SAR/change-detection/captioning/region-grounding models, NDVI or any
other scientific computation, image registration/resampling/tiling,
LangChain/LangGraph, agentic orchestration, or model-output validation.
Those all live elsewhere (see `app/ml/`, `app/orchestrator/`) and stay
untouched by this package on purpose.

Layout (`service.py` is the one entry point; everything else is a focused,
independently testable check it composes -- see each module's own
docstring):

    service.py               orchestrates the pipeline below
    file_validator.py        format / size (section 2)
    raster_validator.py      opens the file; width/height/bands/dtype/CRS (section 3)
    geospatial_validator.py  CRS/transform/bounds, only when required (section 4)
    sensors.py               which of Sentinel-1/-2, Cartosat, RISAT produced a file (or unsupported/unknown)
    modality_validator.py    optical/multispectral/SAR from bands + sensor evidence; validates modality_hint (section 5)
    band_validator.py        sensor-aware band names + the VV<->VV / VH<->VH rule (section 6)
    change_detection_validator.py  strict, order-stopping T1/T2 pair check (chat / strict profiles)
    workflow_validator.py    the declarative WORKFLOW_REGISTRY + count/role/pairing checks (sections 7, 9)
    aoi_validator.py         AOI geometry validity + image-bounds intersection (section 10)
    limits.py                configurable resource ceilings (section 11)
    schemas.py               request/response/internal shapes
    errors.py                machine-readable error codes

`schemas.py` and `errors.py` live inside this package rather than the
app-wide `app/schemas/`/`core/exceptions.py`, on purpose: this is a
self-contained subsystem meant to be lifted into another service unchanged
(the brief: "The validator should be reusable by future workflows"), and its
response shape (a list of *all* applicable errors, not the first one raised)
doesn't fit `core/exceptions.py`'s one-error-per-request `ApiError` model.

Supabase/Storage integration (turning an already-uploaded `imagery_id` into
the `ImageInput` this package validates) is deliberately kept OUTSIDE this
package, in `app/services/imagery_service.py::build_validation_image` --
see that function's docstring.
"""
