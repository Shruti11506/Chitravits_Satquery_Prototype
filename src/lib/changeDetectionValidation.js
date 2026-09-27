/**
 * Helpers for change detection intent recognition and dynamic validation popup states.
 */

const CHANGE_DETECTION_INTENT_REGEX =
  /\b(change\s*detection|detect\s*changes?|compare\s*(these|both|images|satellite|scenes?)?|bi-?temporal|multi-?temporal|before\s*and\s*after|differences?)\b/i;

/**
 * Checks if a user's prompt text expresses intent to run change detection.
 */
export function isChangeDetectionIntent(text) {
  if (!text || typeof text !== 'string') return false;
  return CHANGE_DETECTION_INTENT_REGEX.test(text.trim());
}

function formatModality(modality) {
  if (!modality) return 'Unidentified';
  const m = String(modality).toLowerCase();
  if (m === 'rgb') return 'RGB';
  if (m === 'optical') return 'Optical';
  if (m === 'multispectral') return 'Multispectral';
  if (m === 'sar') return 'SAR';
  return modality.charAt(0).toUpperCase() + modality.slice(1);
}

function formatImageDescriptor(image, fallback = 'Image') {
  if (!image) return fallback;
  const parts = [];
  if (image.format) parts.push(image.format.toUpperCase());
  if (image.modality) parts.push(formatModality(image.modality));
  return parts.length > 0 ? parts.join(' • ') : fallback;
}

/**
 * Builds a dynamic `ValidationModalState` from a backend `/validation/change-detection` response.
 */
export function buildModalStateFromValidation(validationResult, options = {}) {
  const firstError = validationResult?.errors?.[0] || {};
  const code = firstError.code || 'INVALID_CHANGE_DETECTION_INPUT';
  const t1 = validationResult?.t1;
  const t2 = validationResult?.t2;

  let title = 'Invalid Input';
  let message = 'These images cannot be used for change detection.';
  let resolution = 'Change detection requires two compatible satellite image types.';
  let details = {
    t1: formatImageDescriptor(t1, 'Image 1 · Reference'),
    t2: formatImageDescriptor(t2, 'Image 2 · Comparison')
  };

  switch (code) {
    case 'IMAGE_TYPE_MISMATCH':
    case 'MODALITY_MISMATCH':
      title = 'Invalid Input';
      message = 'These images have incompatible image types for change detection.';
      details = {
        t1: formatImageDescriptor(t1, 'Image 1: Multispectral / Optical'),
        t2: formatImageDescriptor(t2, 'Image 2: RGB')
      };
      resolution = 'Change detection requires two compatible image types (e.g. Optical + Optical, Multispectral + Multispectral, or SAR + SAR).';
      break;

    case 'UNKNOWN_MODALITY':
      title = 'Invalid Input';
      message = 'Unable to determine the image type required for change detection.';
      details = {
        t1: formatImageDescriptor(t1, 'Image 1: Type unidentified'),
        t2: formatImageDescriptor(t2, 'Image 2: Type unidentified')
      };
      resolution = 'Ensure uploaded satellite images have valid raster metadata and recognizable spectral bands.';
      break;

    case 'BAND_MISMATCH':
      title = 'Invalid Input';
      message = 'The selected images use incompatible spectral or polarization bands.';
      if (firstError.message?.includes('SAR') || t1?.modality === 'sar' || t2?.modality === 'sar') {
        details = {
          t1: `T1: ${firstError.t1 || (t1?.bands?.join('+') || 'Unidentified')}`,
          t2: `T2: ${firstError.t2 || (t2?.bands?.join('+') || 'Unidentified')}`
        };
        resolution = 'SAR change detection requires identical polarization (VV → VV or VH → VH) — never a mix.';
      } else {
        details = {
          t1: `T1: ${firstError.t1 || (t1?.bands?.join('+') || 'Bands mismatch')}`,
          t2: `T2: ${firstError.t2 || (t2?.bands?.join('+') || 'Bands mismatch')}`
        };
        resolution = 'Required spectral bands must exist in both T1 and T2 rasters.';
      }
      break;

    case 'IMAGE_DIMENSION_MISMATCH':
      title = 'Invalid Input';
      message = 'The image dimensions are not compatible for change detection.';
      details = {
        t1: t1?.width && t1?.height ? `T1: ${t1.width} × ${t1.height}` : 'T1: Dimension mismatch',
        t2: t2?.width && t2?.height ? `T2: ${t2.width} × ${t2.height}` : 'T2: Dimension mismatch'
      };
      resolution = 'Pixel-level change detection requires both rasters to have matching pixel dimensions.';
      break;

    case 'ASPECT_RATIO_MISMATCH':
      title = 'Invalid Input';
      message = 'The image aspect ratios are not compatible for change detection.';
      details = {
        t1: t1?.aspect_ratio ? `T1 Aspect Ratio: ${t1.aspect_ratio.toFixed(2)}` : (firstError.t1 || 'T1 ratio'),
        t2: t2?.aspect_ratio ? `T2 Aspect Ratio: ${t2.aspect_ratio.toFixed(2)}` : (firstError.t2 || 'T2 ratio')
      };
      resolution = 'Both scenes must share compatible aspect ratios within tolerance.';
      break;

    case 'CRS_MISMATCH':
      title = 'Invalid Input';
      message = 'The two images use incompatible coordinate reference systems.';
      details = {
        t1: `T1: ${t1?.crs || firstError.t1 || 'Unknown CRS'}`,
        t2: `T2: ${t2?.crs || firstError.t2 || 'Unknown CRS'}`
      };
      resolution = 'Geospatial change detection requires both images to be in the same Coordinate Reference System (CRS).';
      break;

    case 'GEOREFERENCE_MISSING':
    case 'CRS_MISSING':
      title = 'Invalid Input';
      message = 'Geospatial coordinate reference system or bounds are missing.';
      details = {
        t1: t1?.crs ? `T1: ${t1.crs}` : 'T1: Missing georeference / CRS',
        t2: t2?.crs ? `T2: ${t2.crs}` : 'T2: Missing georeference / CRS'
      };
      resolution = 'Geospatial change detection requires georeferenced raster imagery with valid coordinate systems.';
      break;

    case 'FILE_FORMAT_MISMATCH':
      title = 'Invalid Input';
      message = 'T1 and T2 use incompatible raster format families.';
      details = {
        t1: `T1: ${t1?.format || 'Format 1'}`,
        t2: `T2: ${t2?.format || 'Format 2'}`
      };
      resolution = 'Change detection requires both images to belong to the same raster format family.';
      break;

    case 'NOT_DISTINCT_OBSERVATIONS':
      title = 'Invalid Input';
      message = 'T1 and T2 must be two different satellite observations.';
      details = {
        t1: 'Image 1: Same observation',
        t2: 'Image 2: Same observation'
      };
      resolution = 'Please upload two distinct satellite scenes from different acquisition times or sensors.';
      break;

    case 'IMAGE_COUNT_MISMATCH':
      title = 'Invalid Input';
      message = 'Change detection requires two images (T1 reference and T2 comparison).';
      details = {
        t1: 'Image 1: Attached',
        t2: 'Image 2: Missing'
      };
      resolution = 'Please upload or attach both Image 1 and Image 2 to perform change detection.';
      break;

    default:
      if (firstError.message) {
        message = firstError.message;
      }
      break;
  }

  return {
    open: true,
    title,
    message,
    errorCode: code,
    details,
    resolution,
    onReplace: options.onReplace || null
  };
}

/**
 * Builds a dynamic `ValidationModalState` from an `ApiRequestError` (e.g. 422 from POST /analysis).
 */
export function buildModalStateFromError(err, options = {}) {
  const detailsObj = err.details || {};
  const firstError = detailsObj.errors?.[0] || {};
  const code = detailsObj.error_code || firstError.code || err.code || 'INVALID_CHANGE_DETECTION_INPUT';
  const t1 = detailsObj.t1;
  const t2 = detailsObj.t2;

  // Synthesize a validationResult shape and use the common formatter
  const synthValidationResult = {
    valid: false,
    t1,
    t2,
    errors: [
      {
        code,
        message: firstError.message || err.message,
        t1: firstError.t1,
        t2: firstError.t2
      }
    ]
  };

  return buildModalStateFromValidation(synthValidationResult, options);
}
