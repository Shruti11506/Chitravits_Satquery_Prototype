import React, { useState, useEffect, useRef } from 'react';
import {
  Upload, FileUp, Sparkles, ArrowRight, CheckCircle2,
  Satellite, Layers, Database, Compass, X, Search
} from 'lucide-react';
import { ChitravitsEmblem } from './ui/ChitravitsLogo';
import { SUGGESTED_QUERIES } from '../data/mockData';
import { uploadImagery, uploadImageryPair } from '../lib/apiClient';
import {
  getFilePreviewUrl, getImageryGeo, hasRealPreview, validateSatelliteFile,
  makePairAttachment, fileExtensionLabel, MAX_UPLOAD_MB, getPreviewNote
} from '../lib/filePreview';

const PAIR_SLOTS = [
  { position: 1, label: 'Image 1', role: 'Reference Image', prompt: 'Upload First Satellite Image' },
  { position: 2, label: 'Image 2', role: 'Comparison Image', prompt: 'Upload Second Satellite Image' }
];

const TIFF_NAME = /\.tiff?$/i;

function formatMb(bytes) {
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

function revokePreview(slot) {
  if (slot?.previewUrl?.startsWith('blob:')) URL.revokeObjectURL(slot.previewUrl);
}

// One slot of the Image Pair upload: the existing dropzone, at half width.
function PairSlot({ config, slot, disabled, onSelect, onRemove }) {
  const inputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);
  const open = () => { if (!disabled) inputRef.current?.click(); };
  const isTiff = TIFF_NAME.test(slot?.file?.name || '');

  return (
    <div
      className={`upload-dropzone pair-slot ${isDragging ? 'drag-active' : ''} ${slot?.error ? 'pair-slot-invalid' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
      onDragLeave={(e) => { e.preventDefault(); setIsDragging(false); }}
      onDrop={(e) => {
        e.preventDefault();
        setIsDragging(false);
        const file = e.dataTransfer.files?.[0];
        if (file && !disabled) onSelect(file);
      }}
      onClick={open}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".tif,.tiff,.png,.jpg,.jpeg"
        style={{ display: 'none' }}
        data-pair-position={config.position}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onSelect(file);
          e.target.value = ''; // lets the same file be picked again after Remove
        }}
      />
      <div className="pair-slot-label">{config.label} · {config.role}</div>

      {slot?.file ? (
        <>
          {slot.previewUrl && (
            <img className="pair-slot-preview" src={slot.previewUrl} alt={`${config.label} preview`} />
          )}
          <div className="pair-slot-file" title={slot.file.name}>
            <span className="badge badge-geotiff">{fileExtensionLabel(slot.file.name)}</span>
            <span>{slot.file.name}</span>
          </div>
          <div className="pair-slot-meta">
            Original file: {slot.file.name} · {formatMb(slot.file.size)}
          </div>
          {!slot.error && (
            <div className="pair-slot-meta">
              Preview: {hasRealPreview(slot.previewUrl) ? 'available' : isTiff ? 'generated on upload, if the file can be read' : 'unavailable'}
            </div>
          )}
          {slot.error && <div className="pair-slot-error">{slot.error}</div>}
          {slot.status === 'uploading' && <div className="pair-slot-meta">Uploading…</div>}
          <button
            type="button"
            className="btn btn-secondary pair-slot-remove"
            disabled={disabled}
            onClick={(e) => { e.stopPropagation(); onRemove(); }}
            title={`Remove ${config.label}`}
          >
            <X size={14} />
            <span>Remove</span>
          </button>
        </>
      ) : (
        <>
          <div className="dropzone-icon-box">
            <Upload size={24} />
          </div>
          <h3 className="pair-slot-title">{config.prompt}</h3>
          <p className="pair-slot-meta">TIFF / GeoTIFF, PNG or JPEG · up to {MAX_UPLOAD_MB} MB</p>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={disabled}
            onClick={(e) => { e.stopPropagation(); open(); }}
          >
            <FileUp size={16} style={{ color: 'inherit', flexShrink: 0 }} />
            <span>Browse</span>
          </button>
        </>
      )}
    </div>
  );
}

export function LandingHero({ onStartAnalysis, onStartConversation, onImageryUploaded, activeModel, activeProject, onNavigateScreen }) {
  const [prompt, setPrompt] = useState('');
  // 'single' = the original one-image upload, unchanged; 'pair' = Image 1 + Image 2.
  const [uploadMode, setUploadMode] = useState('single');
  // Per slot: { file, previewUrl, error, status: 'selected' | 'invalid' | 'uploading' | 'uploaded' | 'failed' }.
  const [pairImages, setPairImages] = useState({ 1: null, 2: null });
  const [pairError, setPairError] = useState('');
  const [isUploadingPair, setIsUploadingPair] = useState(false);
  // New Chat remounts this screen; an upload still in flight from the old
  // instance must not then navigate the user out of their new chat.
  const isMountedRef = useRef(true);
  useEffect(() => {
    isMountedRef.current = true;
    return () => { isMountedRef.current = false; };
  }, []);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadedFile, setUploadedFile] = useState(null);
  const [isValidating, setIsValidating] = useState(false);

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      processFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileSelect = (e) => {
    if (e.target.files && e.target.files[0]) {
      processFile(e.target.files[0]);
    }
  };

  const processFile = async (file) => {
    setIsValidating(true);
    const previewUrl = getFilePreviewUrl(file);

    // sensor/crs/bands are intentionally left unset -- a plain browser file
    // carries no real sensor or CRS metadata, and none is fabricated (see
    // backend README "no dummy data" scope).
    const filePayload = {
      name: file.name,
      size: (file.size / (1024 * 1024)).toFixed(2) + ' MB',
      type: file.type || 'image/tiff',
      previewUrl: previewUrl
    };

    // Real upload to Supabase Storage (bucket: Satquery) via FastAPI. This is
    // the first persisted action of a new chat, so the conversation record is
    // created here (titled "New Chat" -- the filename never becomes the
    // title). The "Parsing GeoTIFF Metadata..." loading state covers these
    // real network calls. If they fail, imageryId stays null and the chat
    // shows the honest upload error.
    try {
      const conversationId = await onStartConversation();
      const result = await uploadImagery(file, { name: file.name, conversationId });
      console.info('[SatQuery] Image uploaded to Supabase Storage:', result.bucket, result.storage_path);
      filePayload.imageryId = result.id;
      filePayload.conversationId = conversationId;
      // TIFF/GeoTIFF: the backend's rendered thumbnail replaces the placeholder,
      // and real coordinates come along when the file had a CRS.
      if (result.thumbnail_url) filePayload.previewUrl = result.thumbnail_url;
      filePayload.geo = getImageryGeo(result);
      filePayload.previewNote = getPreviewNote(result);
      onImageryUploaded?.();
    } catch (err) {
      console.error('[SatQuery] Image upload to backend failed:', err);
    }

    if (!isMountedRef.current) return;
    setUploadedFile(filePayload);
    setIsValidating(false);
    // User remains on the landing page to enter their query; redirection happens only when Analyze is clicked.
  };

  const selectPairFile = (position, file) => {
    const error = validateSatelliteFile(file);
    setPairImages(prev => {
      revokePreview(prev[position]);
      return {
        ...prev,
        [position]: { file, previewUrl: error ? null : getFilePreviewUrl(file), error, status: error ? 'invalid' : 'selected' }
      };
    });
    setPairError('');
  };

  const removePairFile = (position) => {
    setPairImages(prev => {
      revokePreview(prev[position]);
      return { ...prev, [position]: null };
    });
    setPairError('');
  };

  const setPairStatus = (status) =>
    setPairImages(prev => ({ 1: prev[1] && { ...prev[1], status }, 2: prev[2] && { ...prev[2], status } }));

  // Image Pair: both files go up in ONE request (the backend stores both or
  // neither), then the chat opens exactly like a single upload does. A
  // failure keeps the user here with both files still selected.
  const submitPair = async () => {
    const first = pairImages[1];
    const second = pairImages[2];
    if (!first?.file || !second?.file) {
      setPairError('Please upload both images.');
      return;
    }
    if (first.error || second.error) {
      setPairError('Replace the image marked above before continuing.');
      return;
    }

    setPairError('');
    setIsUploadingPair(true);
    setPairStatus('uploading');
    try {
      const conversationId = await onStartConversation();
      const result = await uploadImageryPair(first.file, second.file, { conversationId });
      console.info('[SatQuery] Image pair uploaded to Supabase Storage:', result.image_1.storage_path, result.image_2.storage_path);
      const toAttachment = (slot, stored) => ({
        name: slot.file.name,
        size: formatMb(slot.file.size),
        type: slot.file.type || 'image/tiff',
        imageryId: stored.id,
        conversationId,
        // TIFF: the backend's rendered thumbnail, or the honest placeholder.
        previewUrl: stored.thumbnail_url || slot.previewUrl,
        geo: getImageryGeo(stored),
        previewNote: getPreviewNote(stored),
        acquisitionDate: stored.acquisition_date || null
      });
      const payload = makePairAttachment(
        [toAttachment(first, result.image_1), toAttachment(second, result.image_2)],
        { pairId: result.pair_id, conversationId }
      );
      onImageryUploaded?.();
      if (!isMountedRef.current) return;
      setPairStatus('uploaded');
      setIsUploadingPair(false);
      onStartAnalysis(prompt, payload);
    } catch (err) {
      console.error('[SatQuery] Image pair upload failed:', err);
      if (!isMountedRef.current) return;
      setPairStatus('failed');
      setIsUploadingPair(false);
      setPairError(`Upload failed: ${err.message || 'unknown error'}. Both images are still selected -- try again.`);
    }
  };

  const handleAnalyze = () => {
    if (uploadMode === 'pair') {
      if (!isUploadingPair) submitPair();
      return;
    }
    if (!prompt.trim() && !uploadedFile) return;
    onStartAnalysis(prompt.trim() || 'Analyze this satellite scene and identify key geospatial features', uploadedFile);
  };

  return (
    <div className="landing-hero">
      {/* Main Hero Headline */}
      <h1 className="hero-tagline">
        Analyze Earth Imagery.<br />
        <span className="highlight-crossfade">
          <span className="highlight-light">Ask in Natural Language.</span>
          <span className="highlight-dark">Ask in Natural Language.</span>
        </span>
      </h1>
      <p style={{ fontSize: '1rem', color: 'var(--text-secondary)', maxWidth: 620, margin: '-4px auto 22px', lineHeight: 1.5, textAlign: 'center' }}>
        Enterprise remote sensing vision-language intelligence for multi-sensor satellite imagery.
      </p>

      {/* Active Project Pill Indicator */}
      {activeProject && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, margin: '-10px 0 20px', flexWrap: 'wrap' }}>
          <div 
            onClick={() => onNavigateScreen?.('projects')}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 14px', borderRadius: 'var(--radius-full)', background: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.3)', cursor: 'pointer', fontSize: '0.78rem' }}
            title="Click to open active project workspace"
          >
            <span>{activeProject.icon || '📁'}</span>
            <span style={{ color: 'var(--text-muted)' }}>Project:</span>
            <strong style={{ color: '#3b82f6' }}>{activeProject.name}</strong>
          </div>
        </div>
      )}

      {/* Upload mode: the existing nav pill style */}
      <div className="nav-tabs-pill upload-mode-toggle" role="tablist" aria-label="Upload mode">
        {[['single', 'Single Image'], ['pair', 'Image Pair']].map(([mode, label]) => (
          <button
            key={mode}
            type="button"
            role="tab"
            aria-selected={uploadMode === mode}
            className={`nav-tab-pill-item pill-highlighted ${uploadMode === mode ? 'active' : ''}`}
            disabled={isValidating || isUploadingPair}
            onClick={() => { setUploadMode(mode); setPairError(''); }}
          >
            {label}
          </button>
        ))}
      </div>

      {uploadMode === 'pair' ? (
        <>
          <div className="pair-dropzones">
            {PAIR_SLOTS.map((config, index) => (
              <React.Fragment key={config.position}>
                {index === 1 && <div className="pair-plus" aria-hidden="true">+</div>}
                <PairSlot
                  config={config}
                  slot={pairImages[config.position]}
                  disabled={isUploadingPair}
                  onSelect={(file) => selectPairFile(config.position, file)}
                  onRemove={() => removePairFile(config.position)}
                />
              </React.Fragment>
            ))}
          </div>
          {isUploadingPair && (
            <p className="pair-status" style={{ color: 'var(--accent)', fontWeight: 600 }}>Uploading both images…</p>
          )}
          {pairError && <p className="pair-error" role="alert">{pairError}</p>}
        </>
      ) : (
      /* Drag & Drop Upload Zone */
      <div
        className={`upload-dropzone ${isDragging ? 'drag-active' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => document.getElementById('satellite-file-input').click()}
      >
        <input 
          id="satellite-file-input" 
          type="file" 
          accept=".tif,.tiff,.geotiff,.png,.jpg,.jpeg" 
          style={{ display: 'none' }}
          onChange={handleFileSelect}
        />

        {isValidating ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
            <div className="isro-live-dot" style={{ width: 14, height: 14 }}></div>
            <p style={{ color: 'var(--accent)', fontWeight: 600 }}>Parsing GeoTIFF Metadata & Georeferencing Bounds...</p>
          </div>
        ) : uploadedFile ? (
          <div 
            style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, padding: '8px 16px' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="dropzone-icon-box" style={{ borderColor: 'var(--color-success)', color: 'var(--color-success)', width: 50, height: 50 }}>
              <CheckCircle2 size={28} />
            </div>
            <div style={{ textAlign: 'center' }}>
              <h3 style={{ fontSize: '1.15rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: 3 }}>
                {uploadedFile.name}
              </h3>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                Size: {uploadedFile.size} • <span style={{ color: '#10b981', fontWeight: 600 }}>Image Selected — type your query below and click Analyze</span>
              </p>
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center' }}>
              <span className="badge badge-geotiff">{uploadedFile.name?.split('.').pop()?.toUpperCase() || 'FILE'}</span>
              {uploadedFile.sensor && <span className="badge badge-optical">{uploadedFile.sensor}</span>}
              {uploadedFile.crs && <span className="badge badge-high">{uploadedFile.crs}</span>}
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ padding: '6px 14px', fontSize: '0.82rem' }}
                onClick={(e) => {
                  e.stopPropagation();
                  document.getElementById('satellite-file-input').click();
                }}
              >
                Change Image
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ padding: '6px 14px', fontSize: '0.82rem', color: '#ef4444' }}
                onClick={(e) => {
                  e.stopPropagation();
                  setUploadedFile(null);
                }}
              >
                Remove
              </button>
            </div>
          </div>
        ) : (
          <div>
            <div className="dropzone-icon-box">
              <Upload size={30} />
            </div>
            <h3 style={{ fontSize: '1.2rem', marginBottom: 4 }}>
              Drag & Drop your Satellite Scene here
            </h3>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: 10 }}>
              Supports GeoTIFF, Multi-spectral TIFF, PNG, or JPEG up to 50 MB
            </p>
            <div style={{ display: 'inline-flex', gap: 10 }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={(e) => { e.stopPropagation(); document.getElementById('satellite-file-input').click(); }}
                title="Browse local files to upload GeoTIFF / TIFF / Satellite imagery"
              >
                <FileUp size={16} style={{ color: 'inherit', flexShrink: 0 }} />
                <span>Browse & Upload GeoTIFF / TIFF</span>
              </button>
            </div>
          </div>
        )}
      </div>
      )}

      {/* Image Attached Indicator & Instruction */}
      {uploadedFile && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          marginBottom: 10,
          padding: '8px 16px',
          borderRadius: 'var(--radius-full)',
          background: 'rgba(16, 185, 129, 0.1)',
          border: '1px solid rgba(16, 185, 129, 0.35)',
          fontSize: '0.84rem',
          color: 'var(--text-primary)',
          maxWidth: '780px',
          width: '100%',
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.05)'
        }}>
          <CheckCircle2 size={16} style={{ color: '#10b981', flexShrink: 0 }} />
          <span style={{ color: 'var(--text-muted)' }}>Attached:</span>
          <strong style={{ color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {uploadedFile.name}
          </strong>
          <span style={{ fontSize: '0.78rem', color: '#10b981', marginLeft: 'auto', fontWeight: 600 }}>
            Enter your prompt below & click Analyze
          </span>
        </div>
      )}

      {/* Prompt Bar Input */}
      <div className="prompt-bar-wrapper" style={{ width: '100%', maxWidth: '780px', marginBottom: 'clamp(10px, 2vh, 20px)' }}>
        <div className="prompt-input-row">
          <Search size={18} style={{ color: 'var(--text-muted)', marginLeft: 8, flexShrink: 0 }} />
          <textarea
            className="prompt-textarea"
            placeholder={uploadedFile ? "Ask your question about this satellite scene (e.g. 'Extract water bodies and assess urban growth')..." : "Ask anything in plain English (e.g. 'Highlight water bodies and calculate urban growth')..."}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleAnalyze();
              }
            }}
          />
          <button 
            className="btn btn-primary"
            onClick={handleAnalyze}
            title="Submit satellite query"
          >
            <span>Analyze</span>
            <ArrowRight size={16} />
          </button>
        </div>
      </div>

      {/* Suggested Query Chips */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 'clamp(6px, 1.2vh, 10px)' }}>
        <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Suggested Inquiries
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center', maxWidth: 840 }}>
          {SUGGESTED_QUERIES.slice(0, 4).map((q, idx) => (
            <button 
              key={idx}
              className="query-chip"
              onClick={() => {
                setPrompt(q);
              }}
            >
              <span>{q}</span>
            </button>
          ))}
        </div>
      </div>

    </div>
  );
}
