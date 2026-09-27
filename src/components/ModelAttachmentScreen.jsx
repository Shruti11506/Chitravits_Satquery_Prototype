import React, { useState, useRef, useEffect } from 'react';
import { 
  Cpu, Upload, FolderUp, CheckCircle2, ShieldCheck, Zap,
  Play, Settings, FileCode, Check, Trash2, ArrowLeft,
  FileCheck, Sparkles, HardDrive, RefreshCw, AlertCircle,
  Layers, Sliders, Info, Eye, Boxes, ChevronDown, ChevronUp
} from 'lucide-react';
import { 
  getStoredModels, saveStoredModels, getActiveModelId, 
  setActiveModelId, parseFolderFiles, runModelInference, formatBytes,
  buildEnsembleModel
} from '../lib/modelsStorage';

export function ModelAttachmentScreen({ onGoBack, onSelectModel, activeModelId }) {
  const [models, setModels] = useState([]);
  const [currentActiveId, setCurrentActiveId] = useState(activeModelId || null);
  const [selectedModel, setSelectedModel] = useState(null);
  const [selectedModelIds, setSelectedModelIds] = useState([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [isTesting, setIsTesting] = useState(false);
  const [toastMessage, setToastMessage] = useState(null);
  const [showCheckpoints, setShowCheckpoints] = useState(false);

  const folderInputRef = useRef(null);
  const filesInputRef = useRef(null);

  // Load models on mount
  useEffect(() => {
    const loaded = getStoredModels();
    setModels(loaded);
    const active = activeModelId || getActiveModelId();
    setCurrentActiveId(active);
    if (active && typeof active === 'string' && active.startsWith('multi:')) {
      const ids = active.replace('multi:', '').split(',').filter(Boolean);
      setSelectedModelIds(ids);
    } else if (active) {
      setSelectedModelIds([active]);
    } else {
      setSelectedModelIds(loaded.map(m => m.id));
    }
    const initialSelected = loaded.find(m => m.id === active) || loaded[0] || null;
    setSelectedModel(initialSelected);
  }, [activeModelId]);

  const showToast = (msg) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const handleActivateModel = (modelId) => {
    setCurrentActiveId(modelId);
    setActiveModelId(modelId);
    setSelectedModelIds([modelId]);
    const model = models.find(m => m.id === modelId);
    onSelectModel?.(model);
    showToast(`"${model?.name}" is now active and will answer questions in chat.`);
  };

  const handleDeactivateModel = () => {
    setCurrentActiveId(null);
    setActiveModelId(null);
    onSelectModel?.(null);
    showToast('Custom model deactivated. Default SatQuery reasoning engine active.');
  };

  const handleDeactivateSingleModel = (modelId) => {
    if (!currentActiveId) return;
    if (currentActiveId === modelId) {
      handleDeactivateModel();
      return;
    }
    if (typeof currentActiveId === 'string' && currentActiveId.startsWith('multi:')) {
      const ids = currentActiveId.replace('multi:', '').split(',').filter(Boolean);
      const remainingIds = ids.filter(id => id !== modelId);
      if (remainingIds.length === 0) {
        handleDeactivateModel();
      } else if (remainingIds.length === 1) {
        handleActivateModel(remainingIds[0]);
      } else {
        const remainingModels = models.filter(m => remainingIds.includes(m.id));
        const ensemble = buildEnsembleModel(remainingModels);
        setCurrentActiveId(ensemble.id);
        setActiveModelId(ensemble.id);
        onSelectModel?.(ensemble);
        showToast(`Model removed from active queries. ${remainingModels.length} model(s) still active.`);
      }
    }
  };

  const isAllSelected = models.length > 0 && models.every(m => selectedModelIds.includes(m.id));

  const handleToggleSelectAll = () => {
    if (isAllSelected) {
      setSelectedModelIds([]);
    } else {
      setSelectedModelIds(models.map(m => m.id));
    }
  };

  const handleToggleSelectModel = (modelId) => {
    setSelectedModelIds(prev => 
      prev.includes(modelId) ? prev.filter(id => id !== modelId) : [...prev, modelId]
    );
  };

  const handleActivateSelectedForQueries = () => {
    if (selectedModelIds.length === 0) {
      showToast('Please tick at least one model on the left to activate for queries.');
      return;
    }
    const chosenModels = models.filter(m => selectedModelIds.includes(m.id));

    if (chosenModels.length === 1) {
      handleActivateModel(chosenModels[0].id);
      setSelectedModel(chosenModels[0]);
    } else {
      const ensemble = buildEnsembleModel(chosenModels);
      setCurrentActiveId(ensemble.id);
      setActiveModelId(ensemble.id);
      onSelectModel?.(ensemble);
      if (chosenModels.length > 0) {
        setSelectedModel(chosenModels[0]);
      }
      showToast(`${chosenModels.length} models attached as external model attachment! Active for queries on the right.`);
    }
  };

  const isModelActive = (modelId) => {
    if (!currentActiveId) return false;
    if (currentActiveId === modelId) return true;
    if (typeof currentActiveId === 'string' && currentActiveId.startsWith('multi:')) {
      const ids = currentActiveId.replace('multi:', '').split(',').filter(Boolean);
      return ids.includes(modelId);
    }
    return false;
  };

  const areSelectedModelsActive = () => {
    if (!currentActiveId || selectedModelIds.length === 0) return false;
    if (selectedModelIds.length === 1) return currentActiveId === selectedModelIds[0];
    if (typeof currentActiveId === 'string' && currentActiveId.startsWith('multi:')) {
      const activeIds = currentActiveId.replace('multi:', '').split(',').filter(Boolean);
      return selectedModelIds.length === activeIds.length && selectedModelIds.every(id => activeIds.includes(id));
    }
    return false;
  };

  // Traverse dropped directory items recursively
  const traverseDirectory = async (item) => {
    const files = [];
    if (item.isFile) {
      const file = await new Promise((resolve, reject) => item.file(resolve, reject));
      files.push(file);
    } else if (item.isDirectory) {
      const dirReader = item.createReader();
      const readEntries = async () => {
        const entries = await new Promise((resolve, reject) => dirReader.readEntries(resolve, reject));
        if (entries.length > 0) {
          for (const entry of entries) {
            const nested = await traverseDirectory(entry);
            files.push(...nested);
          }
          await readEntries(); // read entries until empty (browser batching)
        }
      };
      await readEntries();
    }
    return files;
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    setIsProcessing(true);
    try {
      const items = e.dataTransfer.items;
      let allFiles = [];

      if (items && items.length > 0) {
        for (let i = 0; i < items.length; i++) {
          const item = items[i].webkitGetAsEntry ? items[i].webkitGetAsEntry() : null;
          if (item) {
            const filesFromEntry = await traverseDirectory(item);
            allFiles.push(...filesFromEntry);
          }
        }
      }

      // Fallback to dataTransfer.files
      if (allFiles.length === 0 && e.dataTransfer.files) {
        allFiles = Array.from(e.dataTransfer.files);
      }

      if (allFiles.length > 0) {
        processUploadedFiles(allFiles);
      } else {
        showToast('No valid files or directory detected in drag-and-drop.');
      }
    } catch (err) {
      console.error('[SatQuery] Error processing dropped folder:', err);
      showToast('Error reading folder contents. Try using the folder picker.');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleFolderSelect = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      processUploadedFiles(Array.from(e.target.files));
    }
  };

  const handleFilesSelect = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      processUploadedFiles(Array.from(e.target.files));
    }
  };

  const processUploadedFiles = (files) => {
    setIsProcessing(true);
    setTimeout(() => {
      const newModel = parseFolderFiles(files);
      const updated = [newModel, ...models];
      setModels(updated);
      saveStoredModels(updated);
      setSelectedModel(newModel);
      handleActivateModel(newModel.id);
      setIsProcessing(false);
      showToast(`Model "${newModel.name}" attached successfully with ${newModel.files.length} files!`);
    }, 600);
  };

  const handleDeleteModel = (modelId, e) => {
    e?.stopPropagation();
    const updated = models.filter(m => m.id !== modelId);
    setModels(updated);
    saveStoredModels(updated);
    if (currentActiveId === modelId) {
      const fallback = updated[0]?.id || null;
      setCurrentActiveId(fallback);
      setActiveModelId(fallback);
      onSelectModel?.(updated[0] || null);
    }
    if (selectedModel?.id === modelId) {
      setSelectedModel(updated[0] || null);
    }
    showToast('Model removed from attached library.');
  };

  const handleDeleteSelectedModels = () => {
    if (selectedModelIds.length === 0) return;
    const count = selectedModelIds.length;
    const updated = models.filter(m => !selectedModelIds.includes(m.id));
    setModels(updated);
    saveStoredModels(updated);
    setSelectedModelIds([]);
    if (selectedModelIds.includes(currentActiveId)) {
      const fallback = updated[0]?.id || null;
      setCurrentActiveId(fallback);
      setActiveModelId(fallback);
      onSelectModel?.(updated[0] || null);
    }
    if (selectedModel && selectedModelIds.includes(selectedModel.id)) {
      setSelectedModel(updated[0] || null);
    }
    showToast(`${count} model${count > 1 ? 's' : ''} removed from attached library.`);
  };

  const handleUpdateModelSettings = (field, value) => {
    if (!selectedModel) return;
    const updatedModel = { ...selectedModel, [field]: value };
    setSelectedModel(updatedModel);
    const updated = models.map(m => m.id === selectedModel.id ? updatedModel : m);
    setModels(updated);
    saveStoredModels(updated);
    if (currentActiveId === selectedModel.id) {
      onSelectModel?.(updatedModel);
    }
  };

  const handleRunTest = () => {
    if (!selectedModel) return;
    setIsTesting(true);
    setTimeout(() => {
      const res = runModelInference(selectedModel, 'Detect structural centroids, evaluate NDWI water coverage, and count features in active scene.');
      setTestResult(res);
      setIsTesting(false);
    }, 700);
  };

  const activeModels = models.filter(m => isModelActive(m.id));

  return (
    <div className="model-attachment-screen">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="model-toast animate-fadeIn">
          <CheckCircle2 size={16} className="text-primary" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Screen Header */}
      <div className="model-screen-header">
        <div className="header-left">
          <div className="header-title-wrap">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="screen-title">Attach Custom AI Model</h2>
              <span className="badge-pill badge-pill-cyan">Edge Geospatial Inference</span>
            </div>
            <p className="screen-subtitle">
              Drag & drop a local model directory (PyTorch <code>.pt/.pth</code>, ONNX, or SafeTensors) to participate in answering queries.
            </p>
          </div>
        </div>

        <div className="header-right">
          {currentActiveId ? (
            <div className="active-status-card">
              <div className="status-indicator-dot online"></div>
              <div className="text-xs">
                <span className="text-muted block">Active in Chat:</span>
                <strong className="text-primary">
                  {models.find(m => m.id === currentActiveId)?.name || 'Custom Model'}
                </strong>
              </div>
              <button 
                onClick={handleDeactivateModel} 
                className="btn btn-xs btn-secondary ml-2"
                title="Deactivate and use default reasoning engine"
              >
                Deactivate
              </button>
            </div>
          ) : (
            <div className="inactive-status-card">
              <div className="status-indicator-dot"></div>
              <span className="text-xs text-muted">No custom model active (Default AI reasoning)</span>
            </div>
          )}
        </div>
      </div>

      <div className="model-screen-grid">
        {/* Left Column: Drag & Drop Dropzone + Attached Models Library */}
        <div className="model-left-col">
          {/* Modern Folder Dropzone */}
          <div 
            className={`model-dropzone ${isDragging ? 'dragging' : ''} ${isProcessing ? 'processing' : ''}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <div className="dropzone-ambient-glow"></div>
            
            {isProcessing ? (
              <div className="dropzone-content py-6">
                <RefreshCw size={36} className="text-cyan-400 animate-spin mb-3" />
                <h4 className="text-base font-semibold">Inspecting Model Architecture...</h4>
                <p className="text-xs text-muted">Extracting weights metadata, config YAML, and labels dictionary.</p>
              </div>
            ) : (
              <div className="dropzone-content">
                <div className="dropzone-icon-circle">
                  <FolderUp size={32} className="text-cyan-400" />
                </div>
                <h3 className="dropzone-heading">Drag & Drop Model Folder Here</h3>
                <p className="dropzone-desc">
                  Drop an entire model directory or weights folder. SatQuery automatically detects checkpoint weights, precision, config JSON, and class labels.
                </p>

                <div className="dropzone-formats">
                  <span className="format-tag">.pt / .pth (PyTorch)</span>
                  <span className="format-tag">.onnx</span>
                  <span className="format-tag">.safetensors</span>
                  <span className="format-tag">config.json</span>
                  <span className="format-tag">dataset.yaml</span>
                </div>

                <div className="dropzone-actions">
                  <button 
                    onClick={() => folderInputRef.current?.click()} 
                    className="btn btn-primary"
                    title="Select a directory of model files"
                  >
                    <FolderUp size={16} />
                    <span>Browse Folder</span>
                  </button>
                  <button 
                    onClick={() => filesInputRef.current?.click()} 
                    className="btn btn-secondary"
                    title="Select individual model weight files"
                  >
                    <Upload size={16} />
                    <span>Select Weights File</span>
                  </button>
                </div>

                {/* Hidden File Inputs */}
                <input 
                  type="file" 
                  ref={folderInputRef}
                  onChange={handleFolderSelect}
                  // @ts-ignore
                  webkitdirectory="" 
                  directory="" 
                  multiple 
                  style={{ display: 'none' }} 
                />
                <input 
                  type="file" 
                  ref={filesInputRef}
                  onChange={handleFilesSelect}
                  multiple 
                  accept=".pt,.pth,.onnx,.safetensors,.bin,.json,.yaml,.yml,.txt"
                  style={{ display: 'none' }} 
                />
              </div>
            )}
          </div>

          {/* Model Library / Attached Models List */}
          <div className="model-library-section">
            <div className="library-header">
              <div className="flex items-center gap-2">
                <Boxes size={18} className="text-blue-400" />
                <h3 className="section-title">Attached Models Library</h3>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className="text-muted">{models.length} Total</span>
                <span className="text-primary font-semibold">• {activeModels.length} Active</span>
              </div>
            </div>

            {/* Select All & Activate Toolbar */}
            <div className="library-actions-bar">
              <label 
                className="batch-select-label"
                onClick={(e) => e.stopPropagation()}
              >
                <input 
                  type="checkbox"
                  checked={isAllSelected}
                  onChange={handleToggleSelectAll}
                  className="batch-checkbox"
                  disabled={models.length === 0}
                />
                <span className="batch-select-text">
                  Select All <span className="batch-count">({selectedModelIds.length}/{models.length})</span>
                </span>
              </label>

              <div className="flex items-center gap-2 flex-wrap">
                {selectedModelIds.length > 0 && (
                  <button
                    type="button"
                    onClick={handleDeleteSelectedModels}
                    className="btn-delete-selected"
                    title="Delete all selected models from attachments"
                  >
                    <Trash2 size={14} />
                    <span>Delete Selected ({selectedModelIds.length})</span>
                  </button>
                )}

                <button
                  type="button"
                  onClick={handleActivateSelectedForQueries}
                  disabled={selectedModelIds.length === 0}
                  className="btn-active-for-queries"
                  title="Attach selected models as active for chat queries (moves them to the right)"
                >
                  <Zap size={14} />
                  <span>Active for Queries ({selectedModelIds.length})</span>
                </button>
              </div>
            </div>

            {/* Single list of models below Select All option */}
            <div className="model-card-list">
              {models.length === 0 ? (
                <div className="model-column-empty">
                  <AlertCircle size={26} className="text-muted" />
                  <p className="empty-title">No Models Attached</p>
                  <p className="empty-desc">Drop a model weights folder above to attach it to your library.</p>
                </div>
              ) : (
                models.map((model) => {
                  const isActive = isModelActive(model.id);
                  const isTicked = selectedModelIds.includes(model.id);
                  const isDetailSelected = selectedModel?.id === model.id;

                  return (
                    <div 
                      key={model.id}
                      onClick={() => setSelectedModel(model)}
                      className={`model-list-card ${isDetailSelected ? 'selected' : ''} ${isActive ? 'active-model' : ''} ${isTicked ? 'ticked' : ''}`}
                    >
                      <div className="card-top">
                        <label 
                          className="model-card-check-wrap"
                          htmlFor={`chk-${model.id}`}
                          onClick={(e) => e.stopPropagation()}
                          title={isTicked ? "Untick model" : "Tick model for activation"}
                        >
                          <input
                            type="checkbox"
                            checked={isTicked}
                            onChange={() => handleToggleSelectModel(model.id)}
                            className="model-card-checkbox"
                            id={`chk-${model.id}`}
                          />
                        </label>
                        <div className="model-icon-badge">
                          <Cpu size={22} className="text-primary" />
                        </div>
                        <div className="model-meta">
                          <div className="flex items-center gap-2">
                            <h4 className="model-name">{model.name}</h4>
                            {isActive && (
                              <span className="badge-active-live">
                                <span className="live-dot"></span> Active in Chat
                              </span>
                            )}
                          </div>
                          <p className="model-task">{model.task} • {model.architecture}</p>
                        </div>
                      </div>

                      <div className="card-bottom">
                        <div className="specs-row">
                          <span className="spec-tag">Format: <strong>{model.format}</strong></span>
                          <span className="spec-tag">Size: <strong>{model.size}</strong></span>
                          <span className="spec-tag">Precision: <strong>{model.precision}</strong></span>
                        </div>

                        <div className="actions-row">
                          {isActive ? null : (
                            <button 
                              type="button"
                              onClick={(e) => { e.stopPropagation(); handleActivateModel(model.id); }}
                              className="btn btn-sm btn-secondary"
                              title="Make this model active for queries"
                            >
                              Set Active
                            </button>
                          )}

                          <button 
                            type="button"
                            onClick={(e) => handleDeleteModel(model.id, e)}
                            className="btn-delete-card"
                            title={`Delete "${model.name}" from attachments`}
                          >
                            <Trash2 size={14} />
                            <span>Delete</span>
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>

        {/* Right Column: Active Models for Queries (where YOLO was) + Model Inspector & Real-time Test Preview */}
        <div className="model-right-col">
          {/* Activated Models for Queries Section */}
          <div className="active-queries-panel">
            <div className="active-queries-header">
              <div className="flex items-center gap-2">
                <Zap size={18} className="text-primary" />
                <h3 className="section-title">Active for Queries</h3>
                <span className="active-count-badge">{activeModels.length} Active</span>
              </div>

              {activeModels.length > 0 && (
                <button 
                  onClick={handleDeactivateModel}
                  className="btn btn-xs btn-secondary text-red-400 hover:text-red-300"
                  title="Deactivate all models and return to default SatQuery reasoning engine"
                >
                  Deactivate All
                </button>
              )}
            </div>

            {activeModels.length === 0 ? (
              <div className="active-queries-empty">
                <AlertCircle size={26} className="text-amber-400 mb-2" />
                <p className="empty-title">No Models Active for Queries</p>
                <p className="empty-desc">
                  Tick models on the left using the checkboxes and click <strong>"Active for Queries"</strong> to attach them to your chat queries.
                </p>
              </div>
            ) : (
              <div className="active-models-list">
                {activeModels.map(model => {
                  const isInspecting = selectedModel?.id === model.id;
                  return (
                    <div 
                      key={model.id}
                      onClick={() => setSelectedModel(model)}
                      className={`active-model-item ${isInspecting ? 'active-item-selected' : ''}`}
                      title="Click to inspect and tune parameters below"
                    >
                      <div className="active-item-left">
                        <div className="active-pulse-indicator"></div>
                        <div className="active-item-content">
                          <div className="flex items-center gap-2 mb-2 flex-wrap">
                            <h4 className="active-item-name">{model.name}</h4>
                            <span className="badge-active-live">
                              <span className="live-dot"></span> Active in Chat
                            </span>
                            {isInspecting && (
                              <span className="inspecting-pill">Inspecting Configuration</span>
                            )}
                          </div>
                          
                          <div className="active-meta-pills">
                            <span className="meta-pill">{model.task}</span>
                            <span className="meta-pill font-mono">{model.format}</span>
                            <span className="meta-pill font-mono">{model.size}</span>
                            <span className="meta-pill font-mono">{model.architecture}</span>
                          </div>
                        </div>
                      </div>

                      <div className="active-item-actions">
                        <button 
                          type="button"
                          onClick={(e) => { e.stopPropagation(); handleDeactivateSingleModel(model.id); }}
                          className="btn btn-xs btn-deactivate"
                          title="Remove this model from active queries"
                        >
                          Deactivate
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
          {selectedModel ? (
            <div className="model-detail-panel">
              <div className="panel-header">
                <div>
                  <span className="text-xs uppercase tracking-wider text-muted font-mono">Model Configuration</span>
                  <h3 className="panel-title">{selectedModel.name}</h3>
                  <p className="panel-desc">{selectedModel.description}</p>
                </div>

                <div className="flex items-center gap-2">
                  {isModelActive(selectedModel.id) ? (
                    <button 
                      onClick={handleDeactivateModel}
                      className="btn btn-sm btn-active-luminous"
                    >
                      <CheckCircle2 size={14} />
                      <span>Active for Queries</span>
                    </button>
                  ) : (
                    <button 
                      onClick={() => handleActivateModel(selectedModel.id)}
                      className="btn btn-sm btn-primary"
                    >
                      <Zap size={14} />
                      <span>Activate in Chat</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Specs Grid */}
              <div className="specs-grid">
                <div className="spec-card">
                  <span className="spec-label">Architecture</span>
                  <strong className="spec-value" title={selectedModel.architecture}>{selectedModel.architecture}</strong>
                </div>
                <div className="spec-card">
                  <span className="spec-label">Format</span>
                  <strong className="spec-value" title={selectedModel.format}>{selectedModel.format}</strong>
                </div>
                <div className="spec-card">
                  <span className="spec-label">Weight Size</span>
                  <strong className="spec-value" title={selectedModel.size}>{selectedModel.size}</strong>
                </div>
                <div className="spec-card">
                  <span className="spec-label">Parameters</span>
                  <strong className="spec-value" title={selectedModel.parameters || 'N/A'}>{selectedModel.parameters || 'N/A'}</strong>
                </div>
              </div>

              {/* See More: Confidence, Advanced Tuning & Checkpoints Accordion */}
              <div className="checkpoints-accordion-wrap">
                <button 
                  type="button" 
                  onClick={() => setShowCheckpoints(prev => !prev)}
                  className="btn-see-more-checkpoints"
                  title="Click to view or hide confidence thresholds, tuning parameters & checkpoint files"
                >
                  <div className="flex items-center gap-2">
                    <Sliders size={15} className="text-blue-500 dark:text-cyan-400" />
                    <span className="see-more-title">
                      {showCheckpoints 
                        ? 'Hide Confidence Tuning & Checkpoints' 
                        : 'See More (Confidence, Tuning & Checkpoints)'}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted">
                    <span className="font-mono text-xs text-primary font-semibold">
                      {Math.round((selectedModel.confidenceThreshold || 0.5) * 100)}% Conf
                    </span>
                    <span className="text-muted/60">•</span>
                    <span className="font-mono text-xs">{selectedModel.files?.length || 0} Files</span>
                    {showCheckpoints ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                  </div>
                </button>

                {showCheckpoints && (
                  <div className="checkpoints-expanded-panel animate-fadeIn">
                    {/* Tunable Inference & Confidence Parameters */}
                    <div className="detail-section">
                      <h4 className="detail-subheading">
                        <Sliders size={14} className="text-blue-400 inline mr-1.5" />
                        Inference Tuning & Confidence Thresholds
                      </h4>

                      <div className="settings-form-grid">
                        <div className="form-group">
                          <label className="form-label">Target Capability / Task</label>
                          <select 
                            value={selectedModel.task}
                            onChange={(e) => handleUpdateModelSettings('task', e.target.value)}
                            className="form-select-sm"
                          >
                            <option value="Object Detection">Object Detection (Buildings, Ships, Solar Panels)</option>
                            <option value="Semantic Segmentation">Semantic Segmentation (Water Bodies, Canopy, Urban)</option>
                            <option value="Land Cover Classification">Land Cover & Spectral Classification (LULC)</option>
                            <option value="SAR Marine Target Detection">SAR Marine Target & Vessel Detection</option>
                          </select>
                        </div>

                        <div className="form-group">
                          <label className="form-label">Acceleration Device</label>
                          <select 
                            value={selectedModel.device}
                            onChange={(e) => handleUpdateModelSettings('device', e.target.value)}
                            className="form-select-sm"
                          >
                            <option value="WebGPU (Direct Tensor Core)">WebGPU (Direct Hardware Acceleration)</option>
                            <option value="CUDA Local Daemon">CUDA Local GPU Daemon</option>
                            <option value="WASM CPU Multithreaded">WASM CPU (Universal Fallback)</option>
                          </select>
                        </div>

                        <div className="form-group">
                          <div className="flex justify-between text-xs mb-1">
                            <label className="form-label mb-0">Confidence Threshold</label>
                            <span className="font-mono text-cyan-400 font-semibold">
                              {Math.round((selectedModel.confidenceThreshold || 0.5) * 100)}%
                            </span>
                          </div>
                          <input 
                            type="range"
                            min="0.10"
                            max="0.95"
                            step="0.05"
                            value={selectedModel.confidenceThreshold || 0.5}
                            onChange={(e) => handleUpdateModelSettings('confidenceThreshold', parseFloat(e.target.value))}
                            className="form-slider"
                          />
                        </div>

                        <div className="form-group">
                          <div className="flex justify-between text-xs mb-1">
                            <label className="form-label mb-0">NMS IoU Threshold</label>
                            <span className="font-mono text-cyan-400 font-semibold">
                              {Math.round((selectedModel.nmsThreshold || 0.45) * 100)}%
                            </span>
                          </div>
                          <input 
                            type="range"
                            min="0.10"
                            max="0.90"
                            step="0.05"
                            value={selectedModel.nmsThreshold || 0.45}
                            onChange={(e) => handleUpdateModelSettings('nmsThreshold', parseFloat(e.target.value))}
                            className="form-slider"
                          />
                        </div>
                      </div>

                      <div className="form-group mt-3">
                        <label className="form-label">Model Reasoning Instructions (Appended to Prompts)</label>
                        <textarea 
                          rows={2}
                          value={selectedModel.instructions || ''}
                          onChange={(e) => handleUpdateModelSettings('instructions', e.target.value)}
                          placeholder="E.g. Focus specifically on rooftop geometry and calculate estimated square meters..."
                          className="form-textarea-sm"
                        />
                      </div>
                    </div>

                    {/* Detected Checkpoint Files */}
                    <div className="detail-section pt-3 border-t border-border-subtle">
                      <h4 className="detail-subheading flex items-center justify-between">
                        <span>
                          <HardDrive size={14} className="text-blue-400 inline mr-1.5" />
                          Detected Checkpoint Weights & Config Files ({selectedModel.files?.length || 0})
                        </span>
                        <span className="text-xs text-muted font-normal font-mono">{selectedModel.size}</span>
                      </h4>
                      <div className="files-pill-container mt-2">
                        {(selectedModel.files || []).map((file, idx) => (
                          <div key={idx} className={`file-badge file-${file.type}`}>
                            <FileCode size={13} />
                            <span className="file-name">{file.name}</span>
                            <span className="file-size">{file.size}</span>
                            <span className="file-type-tag">{file.type}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Instant Test Execution */}
              <div className="detail-section test-section">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h4 className="detail-subheading mb-0">
                      <Play size={14} className="text-blue-400 inline mr-1.5" />
                      Live Model Evaluation
                    </h4>
                    <p className="text-xs text-muted">Run zero-shot inference on the active satellite imagery.</p>
                  </div>
                  <button 
                    onClick={handleRunTest} 
                    disabled={isTesting}
                    className="btn btn-sm btn-primary"
                  >
                    {isTesting ? (
                      <>
                        <RefreshCw size={13} className="animate-spin" />
                        <span>Inferencing...</span>
                      </>
                    ) : (
                      <>
                        <Play size={13} />
                        <span>Run Test Inference</span>
                      </>
                    )}
                  </button>
                </div>

                {testResult && (
                  <div className="test-result-box animate-fadeIn">
                    <div className="test-telemetry-bar">
                      <span className="badge-pill badge-pill-cyan">
                        <Check size={11} /> Inference Passed
                      </span>
                      <span className="telemetry-stat">
                        Latency: <strong>{testResult.latencyMs} ms</strong>
                      </span>
                      <span className="telemetry-stat">
                        Device: <strong>{testResult.device}</strong>
                      </span>
                    </div>

                    <p className="test-summary">{testResult.summary}</p>

                    <div className="detections-grid">
                      {testResult.detections?.map((d, i) => (
                        <div key={i} className="detection-item">
                          <span className="detection-label">{d.label}</span>
                          <span className="detection-confidence font-mono">
                            {Math.round(d.confidence * 100)}% Conf
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="empty-selection-panel">
              <Cpu size={48} className="text-muted mb-3 opacity-40" />
              <h3 className="text-base font-semibold">No Model Selected</h3>
              <p className="text-xs text-muted max-w-sm text-center">
                Select an attached model from the library or drag & drop a new model directory to configure parameters.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
