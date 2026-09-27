import React, { useState, useEffect, useRef } from 'react';
import { 
  Sparkles, Send, Mic, Copy, Check, RefreshCw, Volume2, 
  ChevronDown, ChevronUp, Cpu, ExternalLink, ShieldCheck, 
  ImagePlus, X, Satellite, Layers, MapPin, ArrowLeft, GitCompare,
  FolderKanban
} from 'lucide-react';
import { ImageViewer } from './ImageViewer';
import { uploadImagery, submitAnalysis } from '../lib/apiClient';
import { runModelInference } from '../lib/modelsStorage';
import { getFilePreviewUrl, getImageryGeo, getPreviewNote, hasRealPreview, fileExtensionLabel } from '../lib/filePreview';

const QUICK_SUGGESTIONS = [
  { icon: '📄', label: 'Give me the Report', text: 'Give me the report for this satellite scene' },
  { icon: '🔄', label: 'Compare These Both', text: 'Compare these both with bi-temporal satellite imagery' },
  { icon: '🌊', label: 'Extract Water & NDWI', text: 'Analyze water bodies, calculate surface area, and extract NDWI contour' },
  { icon: '🏢', label: 'SAR Building Count', text: 'Detect building structures using SAR double-bounce radar backscatter' },
  { icon: '🌿', label: 'Canopy Health & NDVI', text: 'Assess vegetation density and canopy moisture stress using NDVI' },
  { icon: '🛰️', label: 'Sensor & CRS Specs', text: 'Show sensor specifications, GSD resolution, and coordinate reference system' }
];

const LAST_IMAGERY_KEY = 'satquery-last-imagery-id';

export function Workspace({ 
  scenario, 
  onNavigateScreen, 
  onGoBack, 
  onAnalysisSubmitted, 
  onEnsureConversation, 
  onImageryUploaded,
  activeModel,
  activeProject
}) {
  const [messages, setMessages] = useState(scenario.chatHistory || []);
  const [inputText, setInputText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [copiedId, setCopiedId] = useState(null);
  const [expandedSummaryId, setExpandedSummaryId] = useState(null);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [activeEvidenceHighlight, setActiveEvidenceHighlight] = useState(null);
  const [pendingAttachment, setPendingAttachment] = useState(null);
  const [activeViewerImage, setActiveViewerImage] = useState(scenario.opticalImg);
  // Real georeference of the image in the viewer (null = none known).
  const [activeViewerGeo, setActiveViewerGeo] = useState(scenario.uploadedFile?.geo || null);
  // Local id of a still-uploading attachment shown in the viewer, so its
  // thumbnail/coordinates can replace the placeholder when the upload lands.
  const viewerAttachmentRef = useRef(null);
  const showInViewer = (url, geo = null, attachmentLocalId = null) => {
    setActiveViewerImage(url);
    setActiveViewerGeo(geo);
    viewerAttachmentRef.current = attachmentLocalId;
  };
  // Real Supabase-backed imagery id the chat's queries run against: the most
  // recent upload in this conversation. It persists across messages so
  // follow-up questions ("now calculate the area") refer to the same image.
  const [backendImageryId, setBackendImageryId] = useState(null);
  // Image 2 when the active context is an image pair (backendImageryId is
  // then Image 1); null for a single image. Queries send both.
  const [backendComparisonImageryId, setBackendComparisonImageryId] = useState(null);
  // Conversation this chat belongs to. null for legacy (pre-conversation)
  // chats, and for a chat whose first upload failed (created on next attach).
  const [conversationId, setConversationId] = useState(scenario.conversationId || null);

  const textareaRef = useRef(null);
  const chatBottomRef = useRef(null);
  const fileInputRef = useRef(null);

  // Sync scenario chat history if scenario changes
  useEffect(() => {
    setMessages(scenario.chatHistory || []);
    if (scenario.uploadedFile?.previewUrl) {
      showInViewer(scenario.uploadedFile.previewUrl, scenario.uploadedFile.geo);
    } else if (scenario.opticalImg) {
      showInViewer(scenario.opticalImg);
    }
    // Carry over the real backend imagery_id if the scene arrived via a real
    // upload (LandingHero) or a restored conversation.
    setBackendImageryId(scenario.uploadedFile?.imageryId || null);
    setBackendComparisonImageryId(scenario.uploadedFile?.comparisonImageryId || null);
    setConversationId(scenario.conversationId || null);
    setPendingAttachment(null);
  }, [scenario]);

  // Give immediate control to the chat box when workspace mounts or scene updates
  useEffect(() => {
    const timer = setTimeout(() => {
      textareaRef.current?.focus();
    }, 150);
    return () => clearTimeout(timer);
  }, []);

  // Smooth auto-scroll to bottom whenever new messages or typing state changes
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  // Sends the query to the real backend (POST /api/v1/analysis) and stores
  // an analysis_jobs row -- no AI model runs, so the response is a neutral
  // "queued" acknowledgment, never a fabricated analysis result.
  const handleSendMessage = (textToSend) => {
    const query = (textToSend !== undefined ? textToSend : inputText).trim();
    if (!query && !pendingAttachment) return;
    if (pendingAttachment?.uploading) return;

    const attachmentPayload = pendingAttachment;

    const userMsg = {
      id: `usr-${Date.now()}`,
      sender: 'user',
      text: query,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      attachment: attachmentPayload || null
    };

    // If user attached an image, update active satellite viewer on the left
    if (attachmentPayload?.previewUrl) {
      showInViewer(attachmentPayload.previewUrl, attachmentPayload.geo);
    }

    setMessages(prev => [...prev, userMsg]);
    setInputText('');
    setPendingAttachment(null);

    // A newly attached (and successfully uploaded) image becomes the chat's
    // active image; otherwise the query targets the current one.
    const imageryIdForAnalysis = attachmentPayload ? attachmentPayload.imageryId || null : backendImageryId;
    const comparisonIdForAnalysis = attachmentPayload ? null : backendComparisonImageryId;
    if (attachmentPayload?.imageryId) {
      setBackendImageryId(attachmentPayload.imageryId);
      setBackendComparisonImageryId(null); // a newly attached single image replaces a pair
    }

    setTimeout(() => {
      textareaRef.current?.focus();
    }, 50);

    // If an attached model is active, run custom model inference to participate in answering
    if (activeModel && query) {
      setIsTyping(true);
      setTimeout(() => {
        const inf = runModelInference(activeModel, query, { opticalImg: activeViewerImage });
        const customModelMsg = {
          id: `ai-model-${Date.now()}`,
          sender: 'ai',
          taskType: `${activeModel.name} (${activeModel.task})`,
          text: `[Attached Custom Model Inference — ${activeModel.name}]\n${inf.summary}`,
          isCustomModel: true,
          modelResult: inf,
          confidence: Math.round((activeModel.confidenceThreshold || 0.5) * 100),
          status: 'completed',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          evidenceThumb: attachmentPayload?.previewUrl || activeViewerImage
        };
        setMessages(prev => [...prev, customModelMsg]);
        setIsTyping(false);
      }, 450);
    }

    if (!imageryIdForAnalysis && !activeModel) {
      // No real Supabase-backed image to reference and no active local model
      const unsavedImageShown = !attachmentPayload && Boolean(activeViewerImage);
      const notice = {
        id: `ai-${Date.now()}`,
        sender: 'ai',
        text: attachmentPayload
          ? 'This image could not be uploaded to the backend, so no analysis request could be submitted. Please try attaching it again.'
          : unsavedImageShown
            ? 'The image shown was never saved to the backend (its upload failed -- check that the backend is running), so no analysis request was submitted. Re-attach the image to try again.'
            : 'Please attach a satellite image before submitting a query, or attach a custom model to run local edge inference.',
        isError: Boolean(attachmentPayload) || unsavedImageShown,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setMessages(prev => [...prev, notice]);
      return;
    }

    // Attaching an image without typing anything just adds it to the chat
    if (!query) return;

    if (imageryIdForAnalysis) {
      setIsTyping(true);
      const conversationForQuery = conversationId;
      submitAnalysis(imageryIdForAnalysis, 'general_analysis', query, conversationForQuery, comparisonIdForAnalysis)
        .then((job) => {
          const ack = {
            id: `ai-${Date.now()}`,
            sender: 'ai',
            text: activeModel ? 'Cloud backend job queued alongside local model inference.' : 'Analysis request submitted.',
            status: job.status,
            jobId: job.job_id,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            evidenceThumb: attachmentPayload?.previewUrl || activeViewerImage
          };
          setMessages(prev => [...prev, ack]);
          onAnalysisSubmitted?.(conversationForQuery);
        })
        .catch((err) => {
          if (!activeModel) {
            const errorMsg = {
              id: `ai-${Date.now()}`,
              sender: 'ai',
              text: `Failed to submit analysis request: ${err.message || 'unknown error'}`,
              isError: true,
              timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            };
            setMessages(prev => [...prev, errorMsg]);
          }
        })
        .finally(() => {
          setIsTyping(false);
          setTimeout(() => {
            textareaRef.current?.focus();
          }, 100);
        });
    }
  };

  // Handle image attachment from within the chat box
  const handleFileAttach = (e) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      const previewUrl = getFilePreviewUrl(file);

      // sensor/crs are left unset -- a plain browser file upload carries no
      // real sensor or CRS metadata, and neither is fabricated (see section
      // 9: do not invent satellite/sensor/coordinate data).
      const localId = `att-${Date.now()}`;
      const filePayload = {
        localId,
        name: file.name,
        size: (file.size / (1024 * 1024)).toFixed(2) + ' MB',
        previewUrl: previewUrl,
        uploading: true
      };

      setPendingAttachment(filePayload);
      showInViewer(previewUrl, null, localId);

      // Give control directly to the chat box!
      setTimeout(() => {
        textareaRef.current?.focus();
      }, 50);

      const settle = (changes) =>
        setPendingAttachment(prev => (prev?.localId === localId ? { ...prev, uploading: false, ...changes } : prev));

      // Real upload to Supabase Storage (bucket: Satquery) via FastAPI, in
      // parallel with the local preview above. It joins this chat's
      // conversation (legacy chats have none) and never renames it. Sending
      // waits until the upload settles so the query targets this image.
      (async () => {
        try {
          let targetConversationId = conversationId;
          if (!targetConversationId && !scenario.isLegacy && onEnsureConversation) {
            targetConversationId = await onEnsureConversation();
            setConversationId(targetConversationId);
          }
          const result = await uploadImagery(file, {
            name: file.name,
            conversationId: targetConversationId || undefined
          });
          console.info('[SatQuery] Image uploaded to Supabase Storage:', result.bucket, result.storage_path);
          const geo = getImageryGeo(result);
          settle({ imageryId: result.id, previewUrl: result.thumbnail_url || previewUrl, geo, previewNote: getPreviewNote(result) });
          if (viewerAttachmentRef.current === localId) {
            showInViewer(result.thumbnail_url || previewUrl, geo, localId);
          }
          onImageryUploaded?.();
          if (scenario.isLegacy) {
            try {
              localStorage.setItem(LAST_IMAGERY_KEY, result.id);
            } catch {
              // localStorage unavailable (private mode, etc.) -- refresh-persistence is a convenience, not required.
            }
          }
        } catch (err) {
          console.error('[SatQuery] Image upload to backend failed:', err);
          settle({ imageryId: null });
        }
      })();
    }
  };

  const handleCopyText = (id, text) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleSpeak = (text) => {
    if ('speechSynthesis' in window) {
      if (isSpeaking) {
        window.speechSynthesis.cancel();
        setIsSpeaking(false);
      } else {
        const cleanText = text.replace(/[*#]/g, '');
        const utterance = new SpeechSynthesisUtterance(cleanText);
        utterance.rate = 1.0;
        utterance.onend = () => setIsSpeaking(false);
        setIsSpeaking(true);
        window.speechSynthesis.speak(utterance);
      }
    }
  };

  return (
    <div className="workspace-layout">
      {/* LEFT COLUMN: Large Satellite Image Viewer */}
      <div className="workspace-left">
        <ImageViewer
          imageUrl={activeViewerImage}
          geo={activeViewerGeo}
          scenario={scenario}
          onInspectElement={(elem) => setActiveEvidenceHighlight(elem)}
          showBBoxesDefault={false}
          showSegmentationDefault={false}
        />
      </div>

      {/* RIGHT COLUMN: Conversational Chat & Reasoning Stream (Gemini / ChatGPT Style) */}
      <div className="workspace-right">
        {/* Workspace Chat Header with Back Option */}
        <div style={{
          padding: 'var(--space-3) var(--space-5)',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--bg-glass-subtle)',
          flexWrap: 'wrap',
          gap: 12
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div className="dropzone-icon-box" style={{ width: 34, height: 34, margin: 0 }}>
              <Sparkles size={16} />
            </div>
            <div>
              <div style={{ fontSize: '0.95rem', fontWeight: 600 }}>SatQuery AI Multi-Turn Agent</div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                Active Scene: {scenario.uploadedFile?.name || scenario.title} ({scenario.sensor || 'Sensor unspecified'})
              </div>
            </div>
          </div>

          {/* Quick Screen Navigation Actions */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button 
              className="btn btn-secondary" 
              style={{ padding: '6px 12px', fontSize: '0.78rem', display: 'inline-flex', alignItems: 'center', gap: 5 }}
              onClick={() => onNavigateScreen('change')}
              title="Compare Before & After Satellite Imagery"
            >
              <GitCompare size={13} />
              <span>Compare</span>
            </button>

            <button 
              className="btn btn-secondary" 
              style={{ padding: '6px 12px', fontSize: '0.78rem', display: 'inline-flex', alignItems: 'center', gap: 5 }}
              onClick={() => onNavigateScreen('report')}
              title="Generate full downloadable scientific PDF report"
            >
              <span>Full Report</span>
              <ExternalLink size={13} />
            </button>
          </div>
        </div>

        {/* Chat History Messages Stream */}
        <div className="chat-stream-container">
          {messages.map((msg) => {
            const isUser = msg.sender === 'user';
            
            if (isUser) {
              return (
                <div key={msg.id} className="chat-bubble-user">
                  {/* Image pair: both real uploads, each clickable into the viewer */}
                  {msg.attachment?.isPair && msg.attachment.images.map((image, index) => (
                    <div key={image.imageryId || index} className="chat-user-attachment" style={{ marginTop: index ? 6 : 0 }}>
                      <div className="chat-user-attachment-thumb-wrap">
                        <img
                          src={image.previewUrl}
                          alt={image.name}
                          className="chat-user-thumb"
                          onClick={() => showInViewer(image.previewUrl, image.geo)}
                          title="Click to view in main satellite panel"
                        />
                        <span className="chat-user-thumb-badge">{fileExtensionLabel(image.name)}</span>
                      </div>
                      <div className="chat-attachment-info">
                        <div className="chat-attachment-meta">
                          <span className="meta-tag">{index === 0 ? 'Image 1 · Reference' : 'Image 2 · Comparison'}</span>
                        </div>
                        <div className="chat-attachment-name" title={image.name}>{image.name}</div>
                        <div className="chat-attachment-meta">
                          {image.size && <span className="meta-tag">{image.size}</span>}
                          <span className="meta-tag" title={image.previewNote || undefined}>
                            {image.previewNote || `Preview ${hasRealPreview(image.previewUrl) ? 'available' : 'unavailable'}`}
                          </span>
                          {image.acquisitionDate && (
                            <span className="meta-tag">Acquired {new Date(image.acquisitionDate).toLocaleDateString()}</span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}

                  {/* Selected/Attached Image Thumbnail & Metadata (ChatGPT/Gemini style) */}
                  {msg.attachment && !msg.attachment.isPair && (
                    <div className="chat-user-attachment">
                      <div className="chat-user-attachment-thumb-wrap">
                        <img 
                          src={msg.attachment.previewUrl || msg.attachment} 
                          alt={msg.attachment.name || "Attached satellite scene"} 
                          className="chat-user-thumb" 
                          onClick={() => showInViewer(msg.attachment.previewUrl || msg.attachment, msg.attachment.geo)}
                          title="Click to view in main satellite panel"
                        />
                        <span className="chat-user-thumb-badge">{fileExtensionLabel(msg.attachment.name)}</span>
                      </div>
                      <div className="chat-attachment-info">
                        <div className="chat-attachment-name">{msg.attachment.name || "Attached file"}</div>
                        <div className="chat-attachment-meta">
                          {msg.attachment.size && <span className="meta-tag">{msg.attachment.size}</span>}
                          {msg.attachment.sensor && <span className="meta-tag">{msg.attachment.sensor}</span>}
                          {msg.attachment.crs && <span className="meta-tag meta-crs">{msg.attachment.crs}</span>}
                          {msg.attachment.previewNote && (
                            <span className="meta-tag" title={msg.attachment.previewNote}>{msg.attachment.previewNote}</span>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* User Question Text */}
                  {msg.text && (
                    <div className="chat-user-text" style={{ marginTop: msg.attachment ? 8 : 0 }}>
                      {msg.text}
                    </div>
                  )}

                  <div className="chat-msg-time" style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textAlign: 'right', marginTop: 4 }}>
                    {msg.timestamp}
                  </div>
                </div>
              );
            }

            // AI Response Card
            const isSummaryExpanded = expandedSummaryId === msg.id;
            return (
              <div key={msg.id} className="chat-bubble-ai">
                {/* Header: Task type, Confidence Gauge, Actions */}
                <div className="ai-response-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div className="isro-live-dot"></div>
                    <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--accent)' }}>
                      {msg.taskType || 'Analysis Request'}
                    </span>
                  </div>

                  {/* Confidence Badge (only when a real score exists) or a neutral status pill */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {msg.confidence != null ? (
                      <span className="badge badge-high" title="Ensemble Calibrated Confidence Score">
                        <ShieldCheck size={13} />
                        <span>{msg.confidence}% Confidence</span>
                      </span>
                    ) : msg.status ? (
                      <span className="badge badge-high" title="Analysis job status" style={{ textTransform: 'capitalize' }}>
                        <ShieldCheck size={13} />
                        <span>{msg.status}</span>
                      </span>
                    ) : null}
                  </div>
                </div>

                {/* AI Markdown / Formatted Text Response */}
                <div style={{ fontSize: '0.92rem', lineHeight: 1.6, whiteSpace: 'pre-line', marginBottom: 'var(--space-3)' }}>
                  {msg.text}
                </div>

                {/* Custom Model Inference Details Card */}
                {msg.isCustomModel && msg.modelResult && (
                  <div className="custom-model-result-card" style={{
                    marginTop: 'var(--space-3)',
                    padding: '12px',
                    borderRadius: 'var(--radius-md)',
                    background: 'var(--bg-secondary)',
                    border: '1px solid var(--border-subtle)'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingBottom: '8px', marginBottom: '8px', borderBottom: '1px solid var(--border-subtle)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <Cpu size={14} style={{ color: '#10b981' }} />
                        <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                          {msg.modelResult.modelName}
                        </span>
                        <span className="badge-pill-xs badge-pill-cyan" style={{ fontSize: '0.68rem', padding: '1px 6px' }}>
                          {msg.modelResult.modelArchitecture || 'Custom Weights'}
                        </span>
                      </div>
                      <span style={{ fontSize: '0.74rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                        {msg.modelResult.latencyMs} ms • {msg.modelResult.device}
                      </span>
                    </div>

                    {msg.modelResult.detections && msg.modelResult.detections.length > 0 && (
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 6, margin: '8px 0' }}>
                        {msg.modelResult.detections.map((det, dIdx) => (
                          <div key={dIdx} style={{ padding: '6px 10px', borderRadius: 'var(--radius-sm)', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border-subtle)', fontSize: '0.75rem' }}>
                            <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{det.label}</div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-muted)', fontSize: '0.7rem', marginTop: 2 }}>
                              <span>Confidence:</span>
                              <strong style={{ color: 'var(--accent)', fontFamily: 'var(--font-mono)' }}>{Math.round(det.confidence * 100)}%</strong>
                            </div>
                            {det.areaKm2 && (
                              <div style={{ fontSize: '0.7rem', color: '#38bdf8' }}>Area: {det.areaKm2}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    {msg.modelResult.metrics && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, paddingTop: 6, borderTop: '1px solid var(--border-subtle)', fontSize: '0.72rem' }}>
                        {Object.entries(msg.modelResult.metrics).map(([k, v]) => (
                          <span key={k} style={{ padding: '2px 8px', borderRadius: 'var(--radius-sm)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-secondary)' }}>
                            {k}: <strong style={{ color: 'var(--text-primary)' }}>{v}</strong>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Direct Action Link if navigation triggered */}
                {msg.actionLink && (
                  <div style={{ marginBottom: 'var(--space-3)' }}>
                    <button
                      className="btn btn-primary"
                      style={{ padding: '7px 16px', fontSize: '0.82rem', display: 'inline-flex', alignItems: 'center', gap: 6 }}
                      onClick={() => onNavigateScreen(msg.actionLink.screen)}
                    >
                      <span>{msg.actionLink.label}</span>
                      <ExternalLink size={13} />
                    </button>
                  </div>
                )}

                {/* Attached Image Thumbnail */}
                {msg.evidenceThumb && (
                  <div style={{ margin: '8px 0' }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 4, letterSpacing: '0.04em' }}>
                      Attached Image
                    </div>
                    <img
                      src={msg.evidenceThumb}
                      alt="Attached satellite image"
                      className="ai-evidence-thumb"
                      onClick={() => setActiveViewerImage(msg.evidenceThumb)}
                      title="Click to view in main satellite panel"
                    />
                  </div>
                )}

                {/* Expandable Execution Summary Accordion */}
                {msg.executionSteps && msg.executionSteps.length > 0 && (
                  <div style={{
                    marginTop: 'var(--space-3)',
                    background: 'var(--bg-secondary)',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--border-subtle)',
                    overflow: 'hidden'
                  }}>
                    <button
                      onClick={() => setExpandedSummaryId(isSummaryExpanded ? null : msg.id)}
                      style={{
                        width: '100%',
                        padding: '8px 12px',
                        background: 'transparent',
                        border: 'none',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        cursor: 'pointer',
                        color: 'var(--text-secondary)',
                        fontSize: '0.78rem',
                        fontWeight: 600,
                        fontFamily: 'var(--font-body)'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <Cpu size={14} style={{ color: 'var(--accent)' }} />
                        <span>Agent Execution Trace ({msg.executionSteps.length} Stages)</span>
                      </div>
                      {isSummaryExpanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                    </button>

                    {isSummaryExpanded && (
                      <div style={{ padding: '8px 12px 12px', borderTop: '1px solid var(--border-subtle)' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                          {msg.executionSteps.map((step, sIdx) => (
                            <div key={sIdx} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', fontSize: '0.75rem', gap: 10 }}>
                              <div>
                                <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{step.step}: </span>
                                <span style={{ color: 'var(--text-secondary)' }}>{step.desc}</span>
                              </div>
                              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-secondary)', whiteSpace: 'nowrap' }}>
                                {step.time}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Footer Action Bar: Copy, Audio TTS, Regenerate */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginTop: 'var(--space-3)',
                  paddingTop: 'var(--space-2)',
                  borderTop: '1px solid var(--border-subtle)'
                }}>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    {msg.modelChain
                      ? `Model: ${msg.modelChain}`
                      : msg.jobId
                        ? `Job: ${msg.jobId.slice(0, 8)}`
                        : ''}
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <button
                      className="btn-icon"
                      onClick={() => handleSpeak(msg.text)}
                      title={isSpeaking ? 'Stop voice readout' : 'Listen to AI analysis'}
                      style={{ color: isSpeaking ? 'var(--accent)' : 'inherit' }}
                    >
                      <Volume2 size={14} />
                    </button>
                    <button
                      className="btn-icon"
                      onClick={() => handleCopyText(msg.id, msg.text)}
                      title="Copy response to clipboard"
                    >
                      {copiedId === msg.id ? <Check size={14} style={{ color: 'var(--color-success)' }} /> : <Copy size={14} />}
                    </button>
                    <button
                      className="btn-icon"
                      onClick={() => handleSendMessage('Re-analyze this scene with higher spectral sensitivity threshold')}
                      title="Regenerate analysis"
                    >
                      <RefreshCw size={14} />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}

          {/* Typing / Agent Execution Indicator */}
          {isTyping && (
            <div className="chat-bubble-ai" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div className="isro-live-dot" style={{ width: 12, height: 12 }}></div>
              <div>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--accent)' }}>
                  Reasoning over multi-spectral tensor layers...
                </div>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                  Executing GDAL_Warp + SAM-EO Zero-shot feature masks
                </div>
              </div>
            </div>
          )}

          <div ref={chatBottomRef} style={{ height: 1 }} />
        </div>

        {/* Bottom Conversational Prompt Bar (Gemini / ChatGPT Style) */}
        <div style={{ padding: 'var(--space-3) var(--space-4)', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-glass)' }}>
          {/* Active Model / Project Status Banner */}
          {(activeModel || activeProject) && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8, padding: '4px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-secondary)', border: '1px solid var(--border-subtle)', fontSize: '0.78rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                {activeModel && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Cpu size={13} style={{ color: '#10b981' }} />
                    <span style={{ color: 'var(--text-muted)' }}>Attached Model:</span>
                    <strong style={{ color: 'var(--text-primary)' }}>{activeModel.name}</strong>
                    <span className="badge-pill-xs badge-pill-emerald" style={{ fontSize: '0.65rem', padding: '1px 5px' }}>Active</span>
                  </div>
                )}
                {activeProject && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: '0.9rem' }}>{activeProject.icon || '📁'}</span>
                    <span style={{ color: 'var(--text-muted)' }}>Project:</span>
                    <strong style={{ color: 'var(--text-primary)' }}>{activeProject.name}</strong>
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                {activeModel && (
                  <button 
                    type="button" 
                    onClick={() => onNavigateScreen('model-attach')} 
                    style={{ background: 'none', border: 'none', color: 'var(--accent)', fontWeight: 600, cursor: 'pointer', fontSize: '0.74rem', textDecoration: 'underline' }}
                  >
                    Configure Model
                  </button>
                )}
                {activeProject && (
                  <button 
                    type="button" 
                    onClick={() => onNavigateScreen('projects')} 
                    style={{ background: 'none', border: 'none', color: 'var(--accent)', fontWeight: 600, cursor: 'pointer', fontSize: '0.74rem', textDecoration: 'underline' }}
                  >
                    View Project
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Quick Suggestion Chips */}
          <div className="chat-suggestion-pills">
            {QUICK_SUGGESTIONS.map((sug, idx) => (
              <button
                key={idx}
                type="button"
                className="chat-pill-btn"
                onClick={() => handleSendMessage(sug.text)}
                disabled={isTyping}
              >
                <span>{sug.icon}</span>
                <span>{sug.label}</span>
              </button>
            ))}
          </div>

          <div className="prompt-bar-wrapper" style={{ marginTop: 8 }}>
            {/* Pending Attachment chip above input (Gemini / ChatGPT style) */}
            {pendingAttachment && (
              <div className="pending-attachment-chip">
                <div className="pending-thumb-wrapper">
                  <img src={pendingAttachment.previewUrl} alt="preview" className="pending-thumb" />
                  <span className="pending-badge">{fileExtensionLabel(pendingAttachment.name)}</span>
                </div>
                <div className="pending-meta">
                  <span className="pending-name">{pendingAttachment.name}</span>
                  <span className="pending-size">{pendingAttachment.size}{pendingAttachment.sensor ? ` • ${pendingAttachment.sensor}` : ''}</span>
                </div>
                <button 
                  type="button" 
                  className="pending-remove-btn"
                  onClick={() => setPendingAttachment(null)}
                  title="Remove attached image"
                >
                  <X size={14} />
                </button>
              </div>
            )}

            <div className="prompt-input-row">
              {/* Hidden file input for mid-chat image attachments */}
              <input 
                type="file" 
                ref={fileInputRef} 
                accept=".tif,.tiff,.geotiff,.png,.jpg,.jpeg" 
                style={{ display: 'none' }}
                onChange={handleFileAttach}
              />

              {/* Attach Image Button */}
              <button 
                type="button"
                className="btn-icon attachment-btn"
                onClick={() => fileInputRef.current?.click()}
                title="Attach Satellite Image (GeoTIFF / PNG / JPEG)"
              >
                <ImagePlus size={18} />
              </button>

              <textarea
                ref={textareaRef}
                className="prompt-textarea"
                rows={1}
                placeholder={pendingAttachment ? "Ask questions about this attached image..." : "Ask about water bodies, urban sprawl, vegetation, or radar signatures..."}
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendMessage();
                  }
                }}
              />

              <button 
                type="button"
                className="btn-icon"
                onClick={() => {
                  setInputText('Calculate total lake surface area and vegetative encroachment');
                  textareaRef.current?.focus();
                }}
                title="Voice query simulation"
              >
                <Mic size={16} />
              </button>

              <button 
                type="button"
                className="btn btn-primary"
                style={{ padding: '8px 16px' }}
                onClick={() => handleSendMessage()}
                disabled={isTyping || pendingAttachment?.uploading || (!inputText.trim() && !pendingAttachment)}
                title={pendingAttachment?.uploading ? 'Uploading image…' : undefined}
              >
                <Send size={15} />
                <span>Send</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Workspace;
