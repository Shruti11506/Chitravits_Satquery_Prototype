import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import {
  Search, SlidersHorizontal, Plus, ChevronDown, Settings,
  Folder, FolderPlus, Star, MoreHorizontal, LayoutGrid, List,
  Calendar, FileText, Satellite, HardDrive, Image as ImageIcon,
  Waves, Sparkles, Check, Trash2, Edit3, Download, ExternalLink,
  X, AlertCircle, Eye, ArrowLeft, ArrowUpDown, ChevronRight,
  Layers, MapPin, Database, Box, MessageSquare
} from 'lucide-react';
import {
  listImagery,
  getImagery,
  deleteImagery,
  uploadImagery,
  listProjects,
  getProject,
  createProject as apiCreateProject,
  listConversations,
  getAnalysisHistory
} from '../lib/apiClient';
import { getImageryPreviewUrl, isBrowserRenderableImage, validateSatelliteFile } from '../lib/filePreview';
import './LibraryScreen.css';

// Storage keys
const FAVORITES_KEY = 'satquery_library_favorites';
const FOLDERS_MAP_KEY = 'satquery_asset_folders';
const RENAMES_MAP_KEY = 'satquery_asset_renames';

function formatFileSize(bytes) {
  if (!bytes || bytes <= 0) return '0 B';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function formatDate(dateStr) {
  if (!dateStr) return 'Recently';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return 'Recently';
    return d.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    });
  } catch {
    return 'Recently';
  }
}

function formatDateTime(dateStr) {
  if (!dateStr) return 'Recently';
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return 'Recently';
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  } catch {
    return 'Recently';
  }
}

export function LibraryScreen({
  onGoBack,
  onOpenAsset,
  onOpenImageryInWorkspace,
  onStartProjectChat,
  onOpenConversation,
  onNavigateScreen,
  onEnsureConversation,
  onImageryUploaded,
  activeProject
}) {
  // Navigation & Category State
  const [activeCategory, setActiveCategory] = useState('suggested'); // 'suggested' | 'favorites' | 'folders' | 'images' | 'all'
  const [selectedFolder, setSelectedFolder] = useState(null); // when drilled down into a folder

  // Filter & Search State
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [dateFilter, setDateFilter] = useState('all');
  const [projectFilter, setProjectFilter] = useState('all');
  const [viewMode, setViewMode] = useState('grid'); // 'grid' | 'list'
  const [sortBy, setSortBy] = useState('newest'); // 'newest' | 'oldest' | 'name-asc' | 'name-desc' | 'size'

  // Dropdown UI states
  const [isNewMenuOpen, setIsNewMenuOpen] = useState(false);
  const [isTypeMenuOpen, setIsTypeMenuOpen] = useState(false);
  const [isDateMenuOpen, setIsDateMenuOpen] = useState(false);
  const [isProjectMenuOpen, setIsProjectMenuOpen] = useState(false);
  const [isSortMenuOpen, setIsSortMenuOpen] = useState(false);
  const [activeCardMenuId, setActiveCardMenuId] = useState(null);

  // Hidden File Inputs
  const imageInputRef = useRef(null);
  const satelliteInputRef = useRef(null);

  // Data State
  const [isLoading, setIsLoading] = useState(true);
  const [toastMsg, setToastMsg] = useState(null);
  const [rawImagery, setRawImagery] = useState([]);
  const [projectsList, setProjectsList] = useState([]);
  const [conversationsList, setConversationsList] = useState([]);
  const [historyList, setHistoryList] = useState([]);
  const [projectFilesMap, setProjectFilesMap] = useState({});

  // Client-persisted Favorites & Overrides
  const [favorites, setFavorites] = useState(() => {
    try {
      const stored = localStorage.getItem(FAVORITES_KEY);
      return stored ? new Set(JSON.parse(stored)) : new Set();
    } catch {
      return new Set();
    }
  });

  const [assetFolders, setAssetFolders] = useState(() => {
    try {
      const stored = localStorage.getItem(FOLDERS_MAP_KEY);
      return stored ? JSON.parse(stored) : {};
    } catch {
      return {};
    }
  });

  const [assetRenames, setAssetRenames] = useState(() => {
    try {
      const stored = localStorage.getItem(RENAMES_MAP_KEY);
      return stored ? JSON.parse(stored) : {};
    } catch {
      return {};
    }
  });

  // Modals State
  const [selectedAssetForDetail, setSelectedAssetForDetail] = useState(null);
  const [renamingAsset, setRenamingAsset] = useState(null);
  const [renameInput, setRenameInput] = useState('');
  const [movingAsset, setMovingAsset] = useState(null);
  const [selectedMoveFolderId, setSelectedMoveFolderId] = useState('');
  const [deletingAsset, setDeletingAsset] = useState(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isCreateFolderOpen, setIsCreateFolderOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [newFolderDesc, setNewFolderDesc] = useState('');
  const [newFolderIcon, setNewFolderIcon] = useState('📁');
  const [newFolderColor, setNewFolderColor] = useState('#3b82f6');
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);

  // Toast Helper
  const showToast = (message) => {
    setToastMsg(message);
    setTimeout(() => setToastMsg(null), 3500);
  };

  // Close menus on outside click
  useEffect(() => {
    const handleOutsideClick = (e) => {
      if (!e.target.closest('.library-new-dropdown-wrap')) setIsNewMenuOpen(false);
      if (!e.target.closest('.library-type-dropdown-wrap')) setIsTypeMenuOpen(false);
      if (!e.target.closest('.library-date-dropdown-wrap')) setIsDateMenuOpen(false);
      if (!e.target.closest('.library-proj-dropdown-wrap')) setIsProjectMenuOpen(false);
      if (!e.target.closest('.library-sort-dropdown-wrap')) setIsSortMenuOpen(false);
      if (!e.target.closest('.library-card-actions')) setActiveCardMenuId(null);
    };
    window.addEventListener('click', handleOutsideClick);
    return () => window.removeEventListener('click', handleOutsideClick);
  }, []);

  // Fetch all real backend data
  const loadLibraryData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [imageryRes, projectsRes, convsRes, historyRes] = await Promise.all([
        listImagery(1, 100).catch(err => {
          console.warn('[SatQuery Library] listImagery error:', err);
          return { items: [], pagination: { total: 0 } };
        }),
        listProjects().catch(err => {
          console.warn('[SatQuery Library] listProjects error:', err);
          return [];
        }),
        listConversations(100).catch(err => {
          console.warn('[SatQuery Library] listConversations error:', err);
          return [];
        }),
        getAnalysisHistory(50).catch(err => {
          console.warn('[SatQuery Library] getAnalysisHistory error:', err);
          return [];
        })
      ]);

      const imageryItems = imageryRes?.items || [];
      setRawImagery(imageryItems);
      setProjectsList(projectsRes || []);
      setConversationsList(convsRes || []);
      setHistoryList(historyRes || []);

      // If any imagery record has missing previewUrl/url, resolve signed URLs
      const needsUrl = imageryItems.filter(img => !img.url && !img.thumbnail_url);
      if (needsUrl.length > 0) {
        // Resolve URLs in the background without blocking the UI
        Promise.allSettled(
          needsUrl.slice(0, 15).map(async (img) => {
            const detail = await getImagery(img.id);
            return { id: img.id, url: detail.url, thumbnail_url: detail.thumbnail_url };
          })
        ).then(results => {
          const updates = {};
          results.forEach(res => {
            if (res.status === 'fulfilled' && res.value) {
              updates[res.value.id] = res.value;
            }
          });
          if (Object.keys(updates).length > 0) {
            setRawImagery(prev => prev.map(img => updates[img.id] ? { ...img, ...updates[img.id] } : img));
          }
        });
      }

      // Fetch knowledge files for each project
      if (projectsRes && projectsRes.length > 0) {
        const filesMap = {};
        await Promise.allSettled(
          projectsRes.map(async (proj) => {
            try {
              const detail = await getProject(proj.id);
              if (detail?.files && detail.files.length > 0) {
                filesMap[proj.id] = detail.files;
              }
            } catch (err) {
              console.warn(`[SatQuery Library] Failed fetching files for project ${proj.id}:`, err);
            }
          })
        );
        setProjectFilesMap(filesMap);
      }
    } catch (err) {
      console.error('[SatQuery Library] Failed loading library data:', err);
      showToast('Error loading library data.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLibraryData();
  }, [loadLibraryData]);

  // Map project ID to project object
  const projectsById = useMemo(() => {
    const map = {};
    projectsList.forEach(p => { map[p.id] = p; });
    return map;
  }, [projectsList]);

  // Map conversation ID to project ID
  const conversationProjectMap = useMemo(() => {
    const map = {};
    conversationsList.forEach(c => {
      if (c.project_id) map[c.id] = c.project_id;
    });
    return map;
  }, [conversationsList]);

  // Aggregate all items into unified Library Items
  const allLibraryItems = useMemo(() => {
    const items = [];

    // 1. Satellite Imagery & Uploaded Files
    rawImagery.forEach(img => {
      const isSar = (img.sensor && /sar|sentinel-1|radar/i.test(img.sensor)) ||
                    (img.name && /sar|radar|sentinel1/i.test(img.name));
      const isTiff = /\.tiff?$/i.test(img.name || img.original_filename || img.storage_path || '');
      
      let type = 'image';
      let typeLabel = 'Satellite Image';
      if (isSar) {
        type = 'sar';
        typeLabel = 'SAR Image';
      } else if (isTiff) {
        type = 'tiff';
        typeLabel = 'TIFF Image';
      }

      // Resolve Folder / Project association
      const manualFolderId = assetFolders[img.id];
      const convProjId = img.conversation_id ? conversationProjectMap[img.conversation_id] : null;
      const folderId = manualFolderId || convProjId || null;
      const folderName = folderId && projectsById[folderId] ? projectsById[folderId].name : null;

      // Resolved preview URL: prefer thumbnail, else signed url, else filePreview helper
      const previewUrl = img.thumbnail_url || (isBrowserRenderableImage(img) ? img.url : null) || getImageryPreviewUrl(img);

      // Custom rename override if present
      const displayName = assetRenames[img.id] || img.name || img.original_filename || 'Satellite Image';

      items.push({
        id: img.id,
        name: displayName,
        rawName: img.name || img.original_filename,
        type,
        typeLabel,
        previewUrl,
        thumbnailUrl: img.thumbnail_url,
        createdAt: img.created_at,
        fileSize: img.file_size,
        sensor: img.sensor || img.source || (isSar ? 'SAR Radar' : isTiff ? 'Multispectral' : 'Optical RGB'),
        latitude: img.latitude,
        longitude: img.longitude,
        bbox: img.bbox,
        cloudCover: img.cloud_cover,
        folderId,
        folderName,
        conversationId: img.conversation_id,
        storagePath: img.storage_path,
        bucket: img.bucket,
        mimeType: img.mime_type,
        isFavorite: favorites.has(img.id),
        origin: 'imagery',
        raw: img
      });
    });

    // 2. Project Knowledge Files (GeoJSON, Reports, Shapefiles, Models)
    Object.entries(projectFilesMap).forEach(([projId, files]) => {
      const proj = projectsById[projId];
      (files || []).forEach(file => {
        const ext = (file.name.split('.').pop() || '').toLowerCase();
        let type = 'file';
        let typeLabel = `${ext.toUpperCase()} File`;

        if (ext === 'pdf') {
          type = 'report';
          typeLabel = 'Analysis Report';
        } else if (['geojson', 'kml', 'kmz', 'shp'].includes(ext)) {
          type = 'file';
          typeLabel = `${ext.toUpperCase()} Vector`;
        } else if (['glb', 'gltf', 'obj'].includes(ext)) {
          type = 'model';
          typeLabel = '3D Model';
        } else if (['tif', 'tiff'].includes(ext)) {
          type = 'tiff';
          typeLabel = 'TIFF Image';
        } else if (['png', 'jpg', 'jpeg'].includes(ext)) {
          type = 'image';
          typeLabel = 'Image Asset';
        }

        const displayName = assetRenames[file.id] || file.name;

        items.push({
          id: file.id,
          name: displayName,
          rawName: file.name,
          type,
          typeLabel,
          previewUrl: file.url || null,
          createdAt: file.created_at,
          fileSize: file.file_size,
          sensor: null,
          folderId: projId,
          folderName: proj ? proj.name : 'Project Assets',
          mimeType: file.mime_type,
          isFavorite: favorites.has(file.id),
          origin: 'project_file',
          raw: file
        });
      });
    });

    // 3. Saved Analysis Outputs & Reports from Analysis Jobs
    historyList.forEach(hist => {
      if (!hist.job_id) return;
      const isChange = hist.analysis_type?.includes('change');
      const isFusion = hist.analysis_type?.includes('fusion');
      const isWater = hist.analysis_type?.includes('water');

      let type = 'analysis';
      let typeLabel = 'Analysis Output';
      if (isChange) typeLabel = 'Change Detection';
      else if (isFusion) typeLabel = 'Optical + SAR Fusion';
      else if (isWater) typeLabel = 'Water Body Detection';

      const manualFolderId = assetFolders[hist.job_id];
      const convProjId = hist.conversation_id ? conversationProjectMap[hist.conversation_id] : null;
      const folderId = manualFolderId || convProjId || null;
      const folderName = folderId && projectsById[folderId] ? projectsById[folderId].name : hist.imagery_name || 'Satellite Analysis';

      const rawTitle = hist.query ? (hist.query.length > 32 ? hist.query.slice(0, 32) + '…' : hist.query) : 'Analysis Output';
      const displayName = assetRenames[hist.job_id] || rawTitle;

      items.push({
        id: hist.job_id,
        name: displayName,
        rawName: hist.query,
        type,
        typeLabel,
        previewUrl: null, // Will use Analysis vector glyph
        createdAt: hist.created_at,
        folderId,
        folderName,
        conversationId: hist.conversation_id,
        imageryId: hist.imagery_id,
        isFavorite: favorites.has(hist.job_id),
        origin: 'analysis_job',
        raw: hist
      });
    });

    // 4. Saved Chat Sessions
    conversationsList.forEach(conv => {
      const folderId = conv.project_id || assetFolders[conv.id] || null;
      const folderName = folderId && projectsById[folderId] ? projectsById[folderId].name : null;
      const displayName = assetRenames[conv.id] || conv.title || 'Chat Session';

      items.push({
        id: conv.id,
        name: displayName,
        rawName: conv.title,
        type: 'chat',
        typeLabel: 'Chat Session',
        previewUrl: null,
        createdAt: conv.created_at,
        folderId,
        folderName,
        conversationId: conv.id,
        isFavorite: favorites.has(conv.id),
        origin: 'conversation',
        raw: conv
      });
    });

    return items;
  }, [rawImagery, projectFilesMap, historyList, conversationsList, favorites, assetFolders, assetRenames, projectsById, conversationProjectMap]);

  // Compute folder item counts
  const folderCounts = useMemo(() => {
    const counts = {};
    projectsList.forEach(p => { counts[p.id] = 0; });
    allLibraryItems.forEach(item => {
      if (item.folderId && counts[item.folderId] !== undefined) {
        counts[item.folderId]++;
      }
    });
    return counts;
  }, [projectsList, allLibraryItems]);

  // Filter & Search & Sort pipeline
  const filteredItems = useMemo(() => {
    return allLibraryItems.filter(item => {
      // 1. Drilled down folder filter
      if (selectedFolder) {
        if (item.folderId !== selectedFolder.id) return false;
      }

      // 2. Category pill filter
      if (!selectedFolder) {
        if (activeCategory === 'favorites' && !item.isFavorite) return false;
        if (activeCategory === 'images' && !['image', 'tiff', 'sar'].includes(item.type)) return false;
        // 'suggested' shows all recent items
        // 'folders' view is handled at component render level
      }

      // 3. Dropdown Type Filter
      if (typeFilter !== 'all') {
        if (typeFilter === 'tiff' && item.type !== 'tiff') return false;
        if (typeFilter === 'sar' && item.type !== 'sar') return false;
        if (typeFilter === 'image' && item.type !== 'image') return false;
        if (typeFilter === 'analysis' && item.type !== 'analysis') return false;
        if (typeFilter === 'report' && item.type !== 'report') return false;
        if (typeFilter === 'model' && item.type !== 'model') return false;
        if (typeFilter === 'file' && item.type !== 'file') return false;
        if (typeFilter === 'chat' && item.type !== 'chat') return false;
      }

      // 4. Dropdown Date Filter
      if (dateFilter !== 'all' && item.createdAt) {
        const itemDate = new Date(item.createdAt).getTime();
        const now = Date.now();
        const diffDays = (now - itemDate) / (1000 * 3600 * 24);

        if (dateFilter === 'today' && diffDays > 1) return false;
        if (dateFilter === '7days' && diffDays > 7) return false;
        if (dateFilter === '30days' && diffDays > 30) return false;
        if (dateFilter === 'year' && diffDays > 365) return false;
      }

      // 5. Dropdown Project Filter
      if (projectFilter !== 'all') {
        if (item.folderId !== projectFilter) return false;
      }

      // 6. Search query
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase().trim();
        const matchName = item.name.toLowerCase().includes(query);
        const matchType = item.typeLabel.toLowerCase().includes(query);
        const matchProject = item.folderName?.toLowerCase().includes(query);
        const matchSensor = item.sensor?.toLowerCase().includes(query);
        if (!matchName && !matchType && !matchProject && !matchSensor) return false;
      }

      return true;
    }).sort((a, b) => {
      // Sort logic
      if (sortBy === 'newest') {
        return new Date(b.createdAt || 0) - new Date(a.createdAt || 0);
      }
      if (sortBy === 'oldest') {
        return new Date(a.createdAt || 0) - new Date(b.createdAt || 0);
      }
      if (sortBy === 'name-asc') {
        return a.name.localeCompare(b.name);
      }
      if (sortBy === 'name-desc') {
        return b.name.localeCompare(a.name);
      }
      if (sortBy === 'size') {
        return (b.fileSize || 0) - (a.fileSize || 0);
      }
      return 0;
    });
  }, [allLibraryItems, selectedFolder, activeCategory, typeFilter, dateFilter, projectFilter, searchQuery, sortBy]);

  // Favorite / Unfavorite toggle
  const toggleFavorite = (itemId, e) => {
    if (e) e.stopPropagation();
    setFavorites(prev => {
      const next = new Set(prev);
      if (next.has(itemId)) {
        next.delete(itemId);
        showToast('Removed from Favorites');
      } else {
        next.add(itemId);
        showToast('Saved to Favorites');
      }
      try {
        localStorage.setItem(FAVORITES_KEY, JSON.stringify(Array.from(next)));
      } catch (err) {
        console.error('Failed storing favorites:', err);
      }
      return next;
    });
  };

  // Upload Handlers
  const handleImageFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const error = validateSatelliteFile(file);
    if (error) {
      showToast(error);
      return;
    }
    showToast(`Uploading ${file.name}…`);
    try {
      await uploadImagery(file, { name: file.name });
      showToast(`Uploaded ${file.name} successfully!`);
      loadLibraryData();
      if (onImageryUploaded) onImageryUploaded();
    } catch (err) {
      console.error('Upload failed:', err);
      showToast(`Upload failed: ${err.message || 'Unknown error'}`);
    } finally {
      if (imageInputRef.current) imageInputRef.current.value = '';
      setIsNewMenuOpen(false);
    }
  };

  const handleSatelliteFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const error = validateSatelliteFile(file);
    if (error) {
      showToast(error);
      return;
    }
    showToast(`Uploading satellite scene ${file.name}…`);
    try {
      await uploadImagery(file, { name: file.name });
      showToast(`Satellite data ${file.name} processed and registered!`);
      loadLibraryData();
      if (onImageryUploaded) onImageryUploaded();
    } catch (err) {
      console.error('Satellite upload failed:', err);
      showToast(`Satellite upload failed: ${err.message || 'Unknown error'}`);
    } finally {
      if (satelliteInputRef.current) satelliteInputRef.current.value = '';
      setIsNewMenuOpen(false);
    }
  };

  // Folder creation handler
  const handleCreateFolder = async (e) => {
    e.preventDefault();
    if (!newFolderName.trim()) return;
    setIsCreatingFolder(true);
    try {
      const created = await apiCreateProject({
        name: newFolderName.trim(),
        description: newFolderDesc.trim() || null,
        icon: newFolderIcon,
        color: newFolderColor
      });
      showToast(`Folder "${created.name}" created!`);
      setIsCreateFolderOpen(false);
      setNewFolderName('');
      setNewFolderDesc('');
      loadLibraryData();
    } catch (err) {
      console.error('Create folder error:', err);
      showToast(`Failed to create folder: ${err.message || 'Server error'}`);
    } finally {
      setIsCreatingFolder(false);
    }
  };

  // Rename asset handler
  const handleSaveRename = (e) => {
    e.preventDefault();
    if (!renamingAsset || !renameInput.trim()) return;
    const nextMap = { ...assetRenames, [renamingAsset.id]: renameInput.trim() };
    setAssetRenames(nextMap);
    try {
      localStorage.setItem(RENAMES_MAP_KEY, JSON.stringify(nextMap));
      showToast(`Renamed to "${renameInput.trim()}"`);
    } catch (err) {
      console.error('Failed saving rename:', err);
    }
    setRenamingAsset(null);
    setRenameInput('');
  };

  // Move asset handler
  const handleSaveMove = (e) => {
    e.preventDefault();
    if (!movingAsset) return;
    const nextMap = { ...assetFolders, [movingAsset.id]: selectedMoveFolderId || null };
    setAssetFolders(nextMap);
    try {
      localStorage.setItem(FOLDERS_MAP_KEY, JSON.stringify(nextMap));
      const targetFolder = projectsById[selectedMoveFolderId];
      showToast(targetFolder ? `Moved to folder "${targetFolder.name}"` : 'Removed from folder');
    } catch (err) {
      console.error('Failed saving move:', err);
    }
    setMovingAsset(null);
    setSelectedMoveFolderId('');
  };

  // Delete asset handler
  const handleConfirmDelete = async () => {
    if (!deletingAsset) return;
    setIsDeleting(true);
    try {
      if (deletingAsset.origin === 'imagery') {
        await deleteImagery(deletingAsset.id);
      }
      // Also cleanup local state
      setRawImagery(prev => prev.filter(i => i.id !== deletingAsset.id));
      showToast(`Deleted "${deletingAsset.name}"`);
    } catch (err) {
      console.error('Delete failed:', err);
      showToast(`Delete failed: ${err.message || 'Cannot delete item'}`);
    } finally {
      setIsDeleting(false);
      setDeletingAsset(null);
      if (selectedAssetForDetail?.id === deletingAsset?.id) {
        setSelectedAssetForDetail(null);
      }
    }
  };

  // Open asset in Workspace or Appropriate Viewer
  const handleOpenItem = (item) => {
    if (item.origin === 'imagery') {
      if (onOpenImageryInWorkspace) {
        onOpenImageryInWorkspace(item.raw);
      } else if (onNavigateScreen) {
        onNavigateScreen('workspace');
      }
    } else if (item.origin === 'conversation') {
      if (onOpenConversation) {
        onOpenConversation(item.id);
      }
    } else {
      setSelectedAssetForDetail(item);
    }
  };

  // Badges helper
  const renderBadge = (type) => {
    switch (type) {
      case 'tiff':
        return <span className="library-card-badge badge-tiff">TIFF</span>;
      case 'sar':
        return <span className="library-card-badge badge-sar">SAR</span>;
      case 'analysis':
        return <span className="library-card-badge badge-analysis">Analysis</span>;
      case 'image':
        return <span className="library-card-badge badge-image">Image</span>;
      case 'report':
        return <span className="library-card-badge badge-report">Report</span>;
      case 'chat':
        return <span className="library-card-badge badge-chat">Chat</span>;
      case 'model':
        return <span className="library-card-badge badge-model">Model</span>;
      default:
        return <span className="library-card-badge badge-file">File</span>;
    }
  };

  // Placeholder thumbnail helper
  const renderThumbnailContent = (item) => {
    if (item.previewUrl) {
      return (
        <img
          src={item.previewUrl}
          alt={item.name}
          className="library-card-img"
          loading="lazy"
          onError={(e) => {
            e.currentTarget.style.display = 'none';
          }}
        />
      );
    }

    if (item.type === 'tiff') {
      return (
        <div className="library-thumb-placeholder">
          <HardDrive className="library-thumb-icon text-cyan-400" />
          <span className="library-thumb-text">GeoTIFF Raster</span>
        </div>
      );
    }

    if (item.type === 'sar') {
      return (
        <div className="library-thumb-placeholder">
          <Waves className="library-thumb-icon text-purple-400" />
          <span className="library-thumb-text">Synthetic Aperture Radar</span>
        </div>
      );
    }

    if (item.type === 'analysis') {
      return (
        <div className="library-thumb-placeholder">
          <Sparkles className="library-thumb-icon text-emerald-400" />
          <span className="library-thumb-text">AI Analysis Artifact</span>
        </div>
      );
    }

    if (item.type === 'report') {
      return (
        <div className="library-thumb-placeholder">
          <FileText className="library-thumb-icon text-amber-400" />
          <span className="library-thumb-text">Executive Report</span>
        </div>
      );
    }

    if (item.type === 'chat') {
      return (
        <div className="library-thumb-placeholder">
          <MessageSquare className="library-thumb-icon text-indigo-400" />
          <span className="library-thumb-text">Chat Session Artifact</span>
        </div>
      );
    }

    if (item.type === 'model') {
      return (
        <div className="library-thumb-placeholder">
          <Box className="library-thumb-icon text-pink-400" />
          <span className="library-thumb-text">3D Elevation Mesh</span>
        </div>
      );
    }

    return (
      <div className="library-thumb-placeholder">
        <Database className="library-thumb-icon text-teal-400" />
        <span className="library-thumb-text">Spatial Data Asset</span>
      </div>
    );
  };

  return (
    <div className="satquery-library-screen">
      {/* Hidden File Upload Inputs */}
      <input
        ref={imageInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        style={{ display: 'none' }}
        onChange={handleImageFileChange}
      />
      <input
        ref={satelliteInputRef}
        type="file"
        accept=".tif,.tiff,.png,.jpg,.jpeg"
        style={{ display: 'none' }}
        onChange={handleSatelliteFileChange}
      />

      {/* Toast Alert */}
      {toastMsg && (
        <div className="library-toast">
          <Check size={16} className="text-cyan-400" />
          <span>{toastMsg}</span>
        </div>
      )}

      {/* --------------------------------------------------------------------
          1. TOP HEADER (ChatGPT-inspired)
          -------------------------------------------------------------------- */}
      <header className="library-top-header">
        <div className="library-header-left">
          <h1 className="library-title">Library</h1>
          <p className="library-subtitle">
            All your satellite imagery, analysis outputs, files, and project assets in one place.
          </p>
        </div>

        <div className="library-header-right">
          {/* Search Bar */}
          <div className="library-search-wrapper">
            <Search className="library-search-icon" />
            <input
              type="text"
              className="library-search-input"
              placeholder="Search library..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button
                className="library-search-clear"
                onClick={() => setSearchQuery('')}
                title="Clear search"
              >
                <X size={14} />
              </button>
            )}
          </div>

          {/* Filter / Sort Reset Button */}
          <button
            className={`library-icon-btn ${(typeFilter !== 'all' || dateFilter !== 'all' || projectFilter !== 'all') ? 'active' : ''}`}
            title="Reset or adjust filters"
            onClick={() => {
              setTypeFilter('all');
              setDateFilter('all');
              setProjectFilter('all');
              setSearchQuery('');
            }}
          >
            <SlidersHorizontal size={17} />
          </button>

          {/* Primary "New" Button with Dropdown */}
          <div className="library-new-dropdown-wrap">
            <button
              className="library-new-btn"
              onClick={(e) => {
                e.stopPropagation();
                setIsNewMenuOpen(prev => !prev);
              }}
            >
              <span>New</span>
              <ChevronDown size={15} />
            </button>

            {isNewMenuOpen && (
              <div className="library-new-dropdown-menu">
                <button
                  className="library-dropdown-item"
                  onClick={() => {
                    setIsNewMenuOpen(false);
                    if (imageInputRef.current) imageInputRef.current.click();
                  }}
                >
                  <ImageIcon size={16} />
                  <span>Upload image</span>
                </button>

                <button
                  className="library-dropdown-item"
                  onClick={() => {
                    setIsNewMenuOpen(false);
                    if (satelliteInputRef.current) satelliteInputRef.current.click();
                  }}
                >
                  <Satellite size={16} />
                  <span>Upload satellite data</span>
                </button>

                <button
                  className="library-dropdown-item"
                  onClick={() => {
                    setIsNewMenuOpen(false);
                    setIsCreateFolderOpen(true);
                  }}
                >
                  <FolderPlus size={16} />
                  <span>Create folder</span>
                </button>
              </div>
            )}
          </div>

          {/* Settings Icon */}
          <button
            className="library-icon-btn"
            title="Settings & Preferences"
            onClick={() => {
              if (onNavigateScreen) onNavigateScreen('settings');
            }}
          >
            <Settings size={18} />
          </button>
        </div>
      </header>

      {/* --------------------------------------------------------------------
          2. CATEGORY NAVIGATION PILLS (ChatGPT-inspired)
          -------------------------------------------------------------------- */}
      <nav className="library-categories-nav" aria-label="Library categories">
        {[
          { id: 'suggested', label: 'Suggested' },
          { id: 'favorites', label: 'Favorites', count: favorites.size },
          { id: 'folders', label: 'Folders', count: projectsList.length },
          { id: 'images', label: 'Images', count: rawImagery.length },
          { id: 'all', label: 'All', count: allLibraryItems.length }
        ].map(cat => (
          <button
            key={cat.id}
            className={`library-cat-pill ${(activeCategory === cat.id && !selectedFolder) ? 'active' : ''}`}
            onClick={() => {
              setSelectedFolder(null);
              setActiveCategory(cat.id);
            }}
          >
            <span>{cat.label}</span>
            {cat.count !== undefined && cat.count > 0 && (
              <span className="pill-badge">{cat.count}</span>
            )}
          </button>
        ))}
      </nav>

      {/* --------------------------------------------------------------------
          3. SECONDARY CONTROLS BAR: FILTERS & VIEW MODE
          -------------------------------------------------------------------- */}
      <div className="library-filter-bar">
        <div className="library-filters-left">
          {/* Type Filter Dropdown */}
          <div className="library-type-dropdown-wrap relative">
            <button
              className={`library-select-btn ${typeFilter !== 'all' ? 'has-filter' : ''}`}
              onClick={(e) => {
                e.stopPropagation();
                setIsTypeMenuOpen(prev => !prev);
              }}
            >
              <span>{typeFilter === 'all' ? 'All types' : typeFilter.toUpperCase()}</span>
              <ChevronDown size={14} />
            </button>

            {isTypeMenuOpen && (
              <div className="library-new-dropdown-menu" style={{ left: 0, right: 'auto', minWidth: 180 }}>
                {[
                  { id: 'all', label: 'All types' },
                  { id: 'tiff', label: 'TIFF / GeoTIFF' },
                  { id: 'sar', label: 'SAR Radar' },
                  { id: 'image', label: 'Standard Images' },
                  { id: 'analysis', label: 'Analysis Outputs' },
                  { id: 'report', label: 'Reports' },
                  { id: 'model', label: '3D Models' },
                  { id: 'file', label: 'Spatial Files' },
                  { id: 'chat', label: 'Chat Sessions' }
                ].map(t => (
                  <button
                    key={t.id}
                    className="library-dropdown-item"
                    onClick={() => {
                      setTypeFilter(t.id);
                      setIsTypeMenuOpen(false);
                    }}
                  >
                    <span>{t.label}</span>
                    {typeFilter === t.id && <Check size={14} className="ml-auto text-cyan-400" />}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Last Modified Date Filter */}
          <div className="library-date-dropdown-wrap relative">
            <button
              className={`library-select-btn ${dateFilter !== 'all' ? 'has-filter' : ''}`}
              onClick={(e) => {
                e.stopPropagation();
                setIsDateMenuOpen(prev => !prev);
              }}
            >
              <span>
                {dateFilter === 'all' ? 'Last modified' :
                 dateFilter === 'today' ? 'Today' :
                 dateFilter === '7days' ? 'Last 7 days' :
                 dateFilter === '30days' ? 'Last 30 days' : 'Last year'}
              </span>
              <ChevronDown size={14} />
            </button>

            {isDateMenuOpen && (
              <div className="library-new-dropdown-menu" style={{ left: 0, right: 'auto', minWidth: 160 }}>
                {[
                  { id: 'all', label: 'All time' },
                  { id: 'today', label: 'Today' },
                  { id: '7days', label: 'Last 7 days' },
                  { id: '30days', label: 'Last 30 days' },
                  { id: 'year', label: 'Last year' }
                ].map(d => (
                  <button
                    key={d.id}
                    className="library-dropdown-item"
                    onClick={() => {
                      setDateFilter(d.id);
                      setIsDateMenuOpen(false);
                    }}
                  >
                    <span>{d.label}</span>
                    {dateFilter === d.id && <Check size={14} className="ml-auto text-cyan-400" />}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Project Filter Dropdown */}
          <div className="library-proj-dropdown-wrap relative">
            <button
              className={`library-select-btn ${projectFilter !== 'all' ? 'has-filter' : ''}`}
              onClick={(e) => {
                e.stopPropagation();
                setIsProjectMenuOpen(prev => !prev);
              }}
            >
              <span>
                {projectFilter === 'all' ? 'All projects' : (projectsById[projectFilter]?.name || 'Project')}
              </span>
              <ChevronDown size={14} />
            </button>

            {isProjectMenuOpen && (
              <div className="library-new-dropdown-menu" style={{ left: 0, right: 'auto', minWidth: 200, maxHeight: 280, overflowY: 'auto' }}>
                <button
                  className="library-dropdown-item"
                  onClick={() => {
                    setProjectFilter('all');
                    setIsProjectMenuOpen(false);
                  }}
                >
                  <span>All projects</span>
                  {projectFilter === 'all' && <Check size={14} className="ml-auto text-cyan-400" />}
                </button>
                {projectsList.map(proj => (
                  <button
                    key={proj.id}
                    className="library-dropdown-item"
                    onClick={() => {
                      setProjectFilter(proj.id);
                      setIsProjectMenuOpen(false);
                    }}
                  >
                    <span>{proj.name}</span>
                    {projectFilter === proj.id && <Check size={14} className="ml-auto text-cyan-400" />}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* View Toggle & Sort */}
        <div className="library-controls-right">
          <div className="library-view-toggle">
            <button
              className={`library-toggle-btn ${viewMode === 'grid' ? 'active' : ''}`}
              onClick={() => setViewMode('grid')}
              title="Grid view"
            >
              <LayoutGrid size={15} />
            </button>
            <button
              className={`library-toggle-btn ${viewMode === 'list' ? 'active' : ''}`}
              onClick={() => setViewMode('list')}
              title="List view"
            >
              <List size={15} />
            </button>
          </div>

          {/* Sort Dropdown */}
          <div className="library-sort-dropdown-wrap relative">
            <button
              className="library-select-btn"
              onClick={(e) => {
                e.stopPropagation();
                setIsSortMenuOpen(prev => !prev);
              }}
            >
              <span>
                {sortBy === 'newest' ? 'Newest first' :
                 sortBy === 'oldest' ? 'Oldest first' :
                 sortBy === 'name-asc' ? 'Name (A-Z)' :
                 sortBy === 'name-desc' ? 'Name (Z-A)' : 'Largest size'}
              </span>
              <ChevronDown size={14} />
            </button>

            {isSortMenuOpen && (
              <div className="library-new-dropdown-menu" style={{ right: 0, minWidth: 160 }}>
                {[
                  { id: 'newest', label: 'Newest first' },
                  { id: 'oldest', label: 'Oldest first' },
                  { id: 'name-asc', label: 'Name (A-Z)' },
                  { id: 'name-desc', label: 'Name (Z-A)' },
                  { id: 'size', label: 'Largest size' }
                ].map(s => (
                  <button
                    key={s.id}
                    className="library-dropdown-item"
                    onClick={() => {
                      setSortBy(s.id);
                      setIsSortMenuOpen(false);
                    }}
                  >
                    <span>{s.label}</span>
                    {sortBy === s.id && <Check size={14} className="ml-auto text-cyan-400" />}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* --------------------------------------------------------------------
          4. FOLDER DRILL-DOWN BREADCRUMB
          -------------------------------------------------------------------- */}
      {selectedFolder && (
        <div className="library-breadcrumb-banner">
          <div className="library-breadcrumb-left">
            <button
              className="library-breadcrumb-link flex items-center gap-1.5"
              onClick={() => setSelectedFolder(null)}
            >
              <ArrowLeft size={15} />
              <span>Library</span>
            </button>
            <span className="text-slate-600">/</span>
            <span className="library-breadcrumb-current flex items-center gap-1.5">
              <Folder size={16} className="text-cyan-400" />
              {selectedFolder.name}
            </span>
          </div>

          <button
            className="text-xs text-cyan-400 hover:underline bg-transparent border-none cursor-pointer"
            onClick={() => setSelectedFolder(null)}
          >
            Back to all assets
          </button>
        </div>
      )}

      {/* --------------------------------------------------------------------
          5. FOLDERS COMPACT HORIZONTAL CARDS (when not drilled down)
          -------------------------------------------------------------------- */}
      {!selectedFolder && (activeCategory === 'suggested' || activeCategory === 'folders' || activeCategory === 'all') && projectsList.length > 0 && (
        <section className="library-folders-section">
          <div className="library-section-header">
            <h2 className="library-section-title">
              <Folder size={18} className="text-blue-500" />
              <span>Folders</span>
            </h2>
            {activeCategory !== 'folders' && (
              <button
                className="library-view-all-link"
                onClick={() => setActiveCategory('folders')}
              >
                <span>View all</span>
                <ChevronRight size={14} />
              </button>
            )}
          </div>

          <div className="library-folders-grid">
            {projectsList.map(proj => {
              const count = folderCounts[proj.id] || 0;
              return (
                <div
                  key={proj.id}
                  className="library-folder-card"
                  onClick={() => setSelectedFolder(proj)}
                >
                  <div className="library-folder-icon-wrap" style={{ color: proj.color || '#38bdf8' }}>
                    <Folder size={20} className="fill-current" />
                  </div>
                  <div className="library-folder-meta">
                    <span className="library-folder-name" title={proj.name}>{proj.name}</span>
                    <span className="library-folder-count">{count} {count === 1 ? 'item' : 'items'}</span>
                  </div>
                  <button
                    className="library-folder-menu-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedFolder(proj);
                    }}
                    title="Open folder"
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* --------------------------------------------------------------------
          6. CONTENT SECTION: RECENT / ASSETS
          -------------------------------------------------------------------- */}
      <section className="library-content-section">
        <div className="library-section-header">
          <h2 className="library-section-title">
            {selectedFolder
              ? `${selectedFolder.name} Assets`
              : activeCategory === 'favorites'
              ? 'Favorites'
              : activeCategory === 'images'
              ? 'Satellite Imagery'
              : 'Recent'}
          </h2>
          <span className="text-xs text-slate-400">
            {filteredItems.length} {filteredItems.length === 1 ? 'item' : 'items'}
          </span>
        </div>

        {/* Loading Skeletons */}
        {isLoading && (
          <div className="library-grid">
            {[1, 2, 3, 4, 5, 6, 7, 8].map(i => (
              <div key={i} className="library-skeleton-card">
                <div className="skeleton-thumb" />
                <div className="skeleton-body">
                  <div className="skeleton-line w-3-4" />
                  <div className="skeleton-line w-1-2" />
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Empty State */}
        {!isLoading && filteredItems.length === 0 && (
          <div className="library-empty-state">
            <div className="library-empty-icon-wrap">
              <Satellite size={32} />
            </div>
            <h3 className="library-empty-title">Your Library is empty</h3>
            <p className="library-empty-desc">
              Upload satellite imagery, analysis outputs, and project assets to see them here.
            </p>
            <div className="library-empty-actions">
              <button
                className="library-new-btn"
                onClick={() => {
                  if (satelliteInputRef.current) satelliteInputRef.current.click();
                }}
              >
                <Satellite size={16} />
                <span>Upload satellite data</span>
              </button>
              <button
                className="library-icon-btn px-4 w-auto gap-2"
                onClick={() => {
                  if (imageInputRef.current) imageInputRef.current.click();
                }}
              >
                <ImageIcon size={16} />
                <span>Upload image</span>
              </button>
            </div>
          </div>
        )}

        {/* Loaded Grid View */}
        {!isLoading && filteredItems.length > 0 && viewMode === 'grid' && (
          <div className="library-grid">
            {filteredItems.map(item => (
              <div
                key={item.id}
                className="library-card"
                onClick={() => handleOpenItem(item)}
              >
                {/* Thumbnail Container */}
                <div className="library-card-thumb-wrap">
                  {renderBadge(item.type)}

                  {/* Top-Right Favorite & More Action Menu */}
                  <div className="library-card-actions" onClick={(e) => e.stopPropagation()}>
                    <button
                      className={`library-card-action-btn ${item.isFavorite ? 'is-favorite' : ''}`}
                      onClick={(e) => toggleFavorite(item.id, e)}
                      title={item.isFavorite ? 'Remove favorite' : 'Save to favorites'}
                    >
                      <Star size={14} className={item.isFavorite ? 'fill-amber-400 text-amber-400' : ''} />
                    </button>

                    <button
                      className="library-card-action-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        setActiveCardMenuId(prev => prev === item.id ? null : item.id);
                      }}
                      title="More options"
                    >
                      <MoreHorizontal size={14} />
                    </button>

                    {/* Card Context Menu */}
                    {activeCardMenuId === item.id && (
                      <div className="library-new-dropdown-menu" style={{ right: 0, top: 32, minWidth: 170 }}>
                        <button
                          className="library-dropdown-item"
                          onClick={() => {
                            setActiveCardMenuId(null);
                            setSelectedAssetForDetail(item);
                          }}
                        >
                          <Eye size={15} />
                          <span>View details</span>
                        </button>

                        {item.origin === 'imagery' && (
                          <button
                            className="library-dropdown-item"
                            onClick={() => {
                              setActiveCardMenuId(null);
                              handleOpenItem(item);
                            }}
                          >
                            <Sparkles size={15} />
                            <span>Open in Workspace</span>
                          </button>
                        )}

                        <button
                          className="library-dropdown-item"
                          onClick={(e) => {
                            setActiveCardMenuId(null);
                            toggleFavorite(item.id, e);
                          }}
                        >
                          <Star size={15} />
                          <span>{item.isFavorite ? 'Unfavorite' : 'Favorite'}</span>
                        </button>

                        <button
                          className="library-dropdown-item"
                          onClick={() => {
                            setActiveCardMenuId(null);
                            setMovingAsset(item);
                            setSelectedMoveFolderId(item.folderId || '');
                          }}
                        >
                          <Folder size={15} />
                          <span>Move to folder…</span>
                        </button>

                        <button
                          className="library-dropdown-item"
                          onClick={() => {
                            setActiveCardMenuId(null);
                            setRenamingAsset(item);
                            setRenameInput(item.name);
                          }}
                        >
                          <Edit3 size={15} />
                          <span>Rename…</span>
                        </button>

                        {item.previewUrl && (
                          <a
                            href={item.previewUrl}
                            download={item.name}
                            target="_blank"
                            rel="noreferrer"
                            className="library-dropdown-item text-inherit"
                            onClick={() => setActiveCardMenuId(null)}
                          >
                            <Download size={15} />
                            <span>Download</span>
                          </a>
                        )}

                        <button
                          className="library-dropdown-item text-red-400 hover:text-red-300"
                          onClick={() => {
                            setActiveCardMenuId(null);
                            setDeletingAsset(item);
                          }}
                        >
                          <Trash2 size={15} className="text-red-400" />
                          <span>Delete</span>
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Thumbnail Image / Vector Placeholder */}
                  {renderThumbnailContent(item)}
                </div>

                {/* Card Info Body */}
                <div className="library-card-body">
                  <h3 className="library-card-title" title={item.name}>
                    {item.name}
                  </h3>
                  <p className="library-card-type">{item.typeLabel}</p>

                  <div className="library-card-footer">
                    <span className="library-card-date">
                      <Calendar size={12} className="opacity-70" />
                      {formatDate(item.createdAt)}
                    </span>

                    {item.folderName && (
                      <span className="library-card-project" title={item.folderName}>
                        <Folder size={12} className="text-blue-400 shrink-0" />
                        <span className="truncate">{item.folderName}</span>
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Loaded List View */}
        {!isLoading && filteredItems.length > 0 && viewMode === 'list' && (
          <div className="library-list-view">
            <div className="library-list-header">
              <span>Name</span>
              <span>Type</span>
              <span>Folder / Project</span>
              <span>Date</span>
              <span>Size</span>
              <span>Actions</span>
            </div>

            {filteredItems.map(item => (
              <div
                key={item.id}
                className="library-list-row"
                onClick={() => handleOpenItem(item)}
              >
                <div className="library-list-col-name">
                  {item.previewUrl ? (
                    <img src={item.previewUrl} alt={item.name} className="library-list-thumb" />
                  ) : (
                    <div className="library-list-thumb flex items-center justify-center text-cyan-400">
                      <Satellite size={16} />
                    </div>
                  )}
                  <span className="library-list-name-text" title={item.name}>{item.name}</span>
                </div>

                <div>{renderBadge(item.type)}</div>

                <div className="text-slate-400 text-xs truncate">
                  {item.folderName || '—'}
                </div>

                <div className="text-slate-400 text-xs">
                  {formatDate(item.createdAt)}
                </div>

                <div className="text-slate-400 text-xs">
                  {formatFileSize(item.fileSize)}
                </div>

                <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                  <button
                    className={`library-folder-menu-btn ${item.isFavorite ? 'text-amber-400' : ''}`}
                    onClick={(e) => toggleFavorite(item.id, e)}
                    title="Favorite"
                  >
                    <Star size={15} className={item.isFavorite ? 'fill-amber-400' : ''} />
                  </button>
                  <button
                    className="library-folder-menu-btn"
                    onClick={() => setSelectedAssetForDetail(item)}
                    title="View details"
                  >
                    <Eye size={15} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* --------------------------------------------------------------------
          MODAL 1: ASSET DETAILS MODAL
          -------------------------------------------------------------------- */}
      {selectedAssetForDetail && (
        <div className="library-modal-overlay" onClick={() => setSelectedAssetForDetail(null)}>
          <div className="library-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="library-modal-header">
              <div className="flex items-center gap-3">
                {renderBadge(selectedAssetForDetail.type)}
                <h3 className="library-modal-title truncate max-w-md">{selectedAssetForDetail.name}</h3>
              </div>
              <button
                className="library-modal-close-btn"
                onClick={() => setSelectedAssetForDetail(null)}
              >
                <X size={18} />
              </button>
            </div>

            <div className="library-modal-content">
              {/* Preview Box */}
              <div className="w-full aspect-video rounded-xl overflow-hidden bg-slate-950 flex items-center justify-center border border-white/10">
                {selectedAssetForDetail.previewUrl ? (
                  <img
                    src={selectedAssetForDetail.previewUrl}
                    alt={selectedAssetForDetail.name}
                    className="w-full h-full object-contain"
                  />
                ) : (
                  renderThumbnailContent(selectedAssetForDetail)
                )}
              </div>

              {/* Technical Metadata Sheet */}
              <div className="library-meta-grid">
                <div className="library-meta-item">
                  <span className="library-meta-k">Asset Name</span>
                  <span className="library-meta-v">{selectedAssetForDetail.name}</span>
                </div>

                <div className="library-meta-item">
                  <span className="library-meta-k">Type / Format</span>
                  <span className="library-meta-v">{selectedAssetForDetail.typeLabel} ({selectedAssetForDetail.mimeType || 'raster'})</span>
                </div>

                <div className="library-meta-item">
                  <span className="library-meta-k">File Size</span>
                  <span className="library-meta-v">{formatFileSize(selectedAssetForDetail.fileSize)}</span>
                </div>

                <div className="library-meta-item">
                  <span className="library-meta-k">Sensor / Source</span>
                  <span className="library-meta-v">{selectedAssetForDetail.sensor || 'Sentinel-2 MSI / Landsat'}</span>
                </div>

                <div className="library-meta-item">
                  <span className="library-meta-k">Created / Uploaded</span>
                  <span className="library-meta-v">{formatDateTime(selectedAssetForDetail.createdAt)}</span>
                </div>

                <div className="library-meta-item">
                  <span className="library-meta-k">Folder / Project</span>
                  <span className="library-meta-v">{selectedAssetForDetail.folderName || 'None (Unassigned)'}</span>
                </div>

                {selectedAssetForDetail.latitude !== undefined && selectedAssetForDetail.latitude !== null && (
                  <div className="library-meta-item">
                    <span className="library-meta-k">Coordinates</span>
                    <span className="library-meta-v">
                      {selectedAssetForDetail.latitude.toFixed(4)}° N, {selectedAssetForDetail.longitude?.toFixed(4)}° E
                    </span>
                  </div>
                )}

                {selectedAssetForDetail.cloudCover !== undefined && selectedAssetForDetail.cloudCover !== null && (
                  <div className="library-meta-item">
                    <span className="library-meta-k">Cloud Cover</span>
                    <span className="library-meta-v">{selectedAssetForDetail.cloudCover.toFixed(1)}%</span>
                  </div>
                )}

                {selectedAssetForDetail.storagePath && (
                  <div className="library-meta-item col-span-2">
                    <span className="library-meta-k">Storage Path</span>
                    <span className="library-meta-v font-mono text-xs">{selectedAssetForDetail.storagePath}</span>
                  </div>
                )}
              </div>
            </div>

            <div className="library-modal-footer">
              {selectedAssetForDetail.origin === 'imagery' && (
                <button
                  className="library-new-btn gap-2"
                  onClick={() => {
                    handleOpenItem(selectedAssetForDetail);
                    setSelectedAssetForDetail(null);
                  }}
                >
                  <Sparkles size={16} />
                  <span>Open in Workspace</span>
                </button>
              )}

              {selectedAssetForDetail.previewUrl && (
                <a
                  href={selectedAssetForDetail.previewUrl}
                  download={selectedAssetForDetail.name}
                  target="_blank"
                  rel="noreferrer"
                  className="library-select-btn text-inherit"
                >
                  <Download size={14} />
                  <span>Download</span>
                </a>
              )}

              <button
                className="library-select-btn"
                onClick={() => {
                  setRenamingAsset(selectedAssetForDetail);
                  setRenameInput(selectedAssetForDetail.name);
                }}
              >
                <Edit3 size={14} />
                <span>Rename</span>
              </button>

              <button
                className="library-select-btn text-red-400 hover:text-red-300"
                onClick={() => setDeletingAsset(selectedAssetForDetail)}
              >
                <Trash2 size={14} />
                <span>Delete</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* --------------------------------------------------------------------
          MODAL 2: CREATE FOLDER MODAL
          -------------------------------------------------------------------- */}
      {isCreateFolderOpen && (
        <div className="library-modal-overlay" onClick={() => setIsCreateFolderOpen(false)}>
          <div className="library-modal-card" style={{ maxWidth: 440 }} onClick={(e) => e.stopPropagation()}>
            <div className="library-modal-header">
              <h3 className="library-modal-title flex items-center gap-2">
                <FolderPlus size={18} className="text-blue-500" />
                <span>Create New Folder</span>
              </h3>
              <button className="library-modal-close-btn" onClick={() => setIsCreateFolderOpen(false)}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateFolder}>
              <div className="library-modal-content">
                <div className="library-form-group">
                  <label className="library-form-label">Folder Name</label>
                  <input
                    type="text"
                    className="library-form-input"
                    placeholder="e.g. Change Detection, ISRO Phase 1"
                    value={newFolderName}
                    onChange={(e) => setNewFolderName(e.target.value)}
                    autoFocus
                    required
                  />
                </div>

                <div className="library-form-group">
                  <label className="library-form-label">Description (optional)</label>
                  <input
                    type="text"
                    className="library-form-input"
                    placeholder="Workspace purpose or satellite project brief"
                    value={newFolderDesc}
                    onChange={(e) => setNewFolderDesc(e.target.value)}
                  />
                </div>

                <div className="library-form-group">
                  <label className="library-form-label">Folder Color</label>
                  <div className="flex items-center gap-2 mt-1">
                    {['#3b82f6', '#06b6d4', '#10b981', '#8b5cf6', '#ef4444', '#f59e0b'].map(c => (
                      <button
                        type="button"
                        key={c}
                        className={`w-6 h-6 rounded-full border-2 transition-all ${newFolderColor === c ? 'border-white scale-110' : 'border-transparent'}`}
                        style={{ backgroundColor: c }}
                        onClick={() => setNewFolderColor(c)}
                      />
                    ))}
                  </div>
                </div>
              </div>

              <div className="library-modal-footer">
                <button
                  type="button"
                  className="library-select-btn"
                  onClick={() => setIsCreateFolderOpen(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="library-new-btn"
                  disabled={isCreatingFolder || !newFolderName.trim()}
                >
                  {isCreatingFolder ? 'Creating…' : 'Create Folder'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* --------------------------------------------------------------------
          MODAL 3: MOVE ASSET TO FOLDER MODAL
          -------------------------------------------------------------------- */}
      {movingAsset && (
        <div className="library-modal-overlay" onClick={() => setMovingAsset(null)}>
          <div className="library-modal-card" style={{ maxWidth: 440 }} onClick={(e) => e.stopPropagation()}>
            <div className="library-modal-header">
              <h3 className="library-modal-title flex items-center gap-2">
                <Folder size={18} className="text-cyan-400" />
                <span>Move "{movingAsset.name}"</span>
              </h3>
              <button className="library-modal-close-btn" onClick={() => setMovingAsset(null)}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSaveMove}>
              <div className="library-modal-content">
                <p className="text-xs text-slate-400 m-0">
                  Select a destination folder or workspace for this item:
                </p>

                <div className="flex flex-col gap-2 max-h-60 overflow-y-auto">
                  <label
                    className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
                      selectedMoveFolderId === '' ? 'border-cyan-500 bg-cyan-950/20' : 'border-white/5 bg-slate-900/60 hover:border-white/20'
                    }`}
                  >
                    <input
                      type="radio"
                      name="folderSelect"
                      value=""
                      checked={selectedMoveFolderId === ''}
                      onChange={() => setSelectedMoveFolderId('')}
                      className="accent-cyan-400"
                    />
                    <span className="text-sm font-medium text-slate-300">No Folder (Root Library)</span>
                  </label>

                  {projectsList.map(p => (
                    <label
                      key={p.id}
                      className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
                        selectedMoveFolderId === p.id ? 'border-cyan-500 bg-cyan-950/20' : 'border-white/5 bg-slate-900/60 hover:border-white/20'
                      }`}
                    >
                      <input
                        type="radio"
                        name="folderSelect"
                        value={p.id}
                        checked={selectedMoveFolderId === p.id}
                        onChange={() => setSelectedMoveFolderId(p.id)}
                        className="accent-cyan-400"
                      />
                      <Folder size={16} style={{ color: p.color || '#3b82f6' }} />
                      <span className="text-sm font-medium text-white truncate">{p.name}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="library-modal-footer">
                <button type="button" className="library-select-btn" onClick={() => setMovingAsset(null)}>
                  Cancel
                </button>
                <button type="submit" className="library-new-btn">
                  Move Asset
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* --------------------------------------------------------------------
          MODAL 4: RENAME ASSET MODAL
          -------------------------------------------------------------------- */}
      {renamingAsset && (
        <div className="library-modal-overlay" onClick={() => setRenamingAsset(null)}>
          <div className="library-modal-card" style={{ maxWidth: 420 }} onClick={(e) => e.stopPropagation()}>
            <div className="library-modal-header">
              <h3 className="library-modal-title flex items-center gap-2">
                <Edit3 size={18} className="text-cyan-400" />
                <span>Rename Asset</span>
              </h3>
              <button className="library-modal-close-btn" onClick={() => setRenamingAsset(null)}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSaveRename}>
              <div className="library-modal-content">
                <div className="library-form-group">
                  <label className="library-form-label">Asset Title</label>
                  <input
                    type="text"
                    className="library-form-input"
                    value={renameInput}
                    onChange={(e) => setRenameInput(e.target.value)}
                    autoFocus
                    required
                  />
                </div>
              </div>

              <div className="library-modal-footer">
                <button type="button" className="library-select-btn" onClick={() => setRenamingAsset(null)}>
                  Cancel
                </button>
                <button type="submit" className="library-new-btn" disabled={!renameInput.trim()}>
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* --------------------------------------------------------------------
          MODAL 5: DELETE CONFIRMATION MODAL
          -------------------------------------------------------------------- */}
      {deletingAsset && (
        <div className="library-modal-overlay" onClick={() => setDeletingAsset(null)}>
          <div className="library-modal-card" style={{ maxWidth: 440 }} onClick={(e) => e.stopPropagation()}>
            <div className="library-modal-header">
              <h3 className="library-modal-title flex items-center gap-2 text-red-400">
                <AlertCircle size={18} />
                <span>Delete Asset?</span>
              </h3>
              <button className="library-modal-close-btn" onClick={() => setDeletingAsset(null)}>
                <X size={18} />
              </button>
            </div>

            <div className="library-modal-content">
              <p className="text-sm text-slate-300 m-0">
                Are you sure you want to permanently delete <strong>"{deletingAsset.name}"</strong>?
              </p>
              <p className="text-xs text-slate-500 m-0">
                This will remove the file and all associated metadata. This action cannot be undone.
              </p>
            </div>

            <div className="library-modal-footer">
              <button type="button" className="library-select-btn" onClick={() => setDeletingAsset(null)}>
                Cancel
              </button>
              <button
                type="button"
                className="library-new-btn bg-red-600 hover:bg-red-700 shadow-red-900/50"
                onClick={handleConfirmDelete}
                disabled={isDeleting}
              >
                {isDeleting ? 'Deleting…' : 'Delete Permanently'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
