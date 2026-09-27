import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Plus, Sun, Moon, ArrowLeft } from 'lucide-react';
import { ChitravitsEmblem } from './components/ui/ChitravitsLogo';
import { LandingHero } from './components/LandingHero';
import { Workspace } from './components/Workspace';
import { ImageViewer } from './components/ImageViewer';
import { ChangeDetection } from './components/ChangeDetection';
import { FusionViewer } from './components/FusionViewer';

import { AnalyticsDashboard } from './components/AnalyticsDashboard';
import { ReportScreen } from './components/ReportScreen';
import { ProfileDashboard } from './components/ProfileDashboard';
import { SettingsPage } from './components/SettingsPage';
import { ModelAttachmentScreen } from './components/ModelAttachmentScreen';
import { ProjectsScreen } from './components/ProjectsScreen';
import './components/ModelAndProjects.css';
import { executeThemeTransition } from './lib/themeTransition';
import { ThemeTransitionWave } from './components/ui/ThemeTransitionPattern';
import { GradientBackground } from './components/ui/oceanic-shimmer';
import { SATELLITE_SCENARIOS } from './data/mockData';
import { SidebarProvider, SidebarTrigger, SidebarInset, useSidebar } from './components/ui/sidebar';
import { UserHistorySidebar } from './components/UserHistorySidebar';
import { InitialLoader } from './components/InitialLoader';
import { getActiveModel, setActiveModelId } from './lib/modelsStorage';
import { getActiveProjectId, setActiveProjectId } from './lib/projectsStorage';
import { getImageryPreviewUrl, getImageryGeo, getPreviewNote, makePairAttachment } from './lib/filePreview';
import {
  getImagery,
  submitAnalysis,
  getAnalysisHistory,
  createConversation,
  getConversation,
  generateConversationTitle,
  getProfile,
  getSettings,
  updateSettings,
  applySettingsChanges,
  getProject,
  listProjects
} from './lib/apiClient';

// Legacy pointer: chats created before conversations existed are keyed by imagery.
const LAST_IMAGERY_KEY = 'satquery-last-imagery-id';
// Pointer only (never data) to the open conversation, re-fetched on refresh.
const LAST_CONVERSATION_KEY = 'satquery-last-conversation-id';
// Set only while the profile or settings screen is open, so a refresh reopens it.
const LAST_SCREEN_KEY = 'satquery-last-screen';
const RESTORABLE_SCREENS = ['profile', 'settings'];
// Cached copies of the SAVED theme / sidebar density (GET /settings is the
// source of truth), only so the first frame paints right before it answers.
const THEME_KEY = 'satquery-theme';
const DENSITY_KEY = 'satquery-sidebar-density';

function prefersDarkScheme() {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  } catch {
    return true;
  }
}

function readPointer(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function rememberPointer(key, value) {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch { /* refresh-persistence is a convenience, not required */ }
}

function formatTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

function formatFileSize(bytes) {
  if (!bytes) return null;
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

function attachmentFromImagery(imagery) {
  return {
    name: imagery.original_filename || imagery.name,
    size: formatFileSize(imagery.file_size),
    sensor: imagery.sensor || null,
    previewUrl: getImageryPreviewUrl(imagery),
    geo: getImageryGeo(imagery),
    previewNote: getPreviewNote(imagery),
    acquisitionDate: imagery.acquisition_date || null,
    imageryId: imagery.id
  };
}

// The attachment for an uploaded row: a pair bubble when the row belongs to
// an image pair whose partner is present, otherwise the single attachment.
function attachmentForImageryRow(imagery, allImagery) {
  if (!imagery.pair_id) return attachmentFromImagery(imagery);
  const pair = allImagery
    .filter(i => i.pair_id === imagery.pair_id)
    .sort((a, b) => (a.pair_position || 0) - (b.pair_position || 0));
  if (pair.length !== 2) return attachmentFromImagery(imagery);
  return makePairAttachment(pair.map(attachmentFromImagery), { pairId: imagery.pair_id });
}

// A conversation with nothing uploaded or asked in yet (left by the old eager
// New Chat, or one whose first upload failed).
function isEmptyConversation(detail) {
  return !detail.imagery?.length && !detail.jobs?.length;
}

// Builds the Workspace "scenario" for a conversation from GET /conversations/{id}.
// Uploads render as attachment bubbles and queries as user message + queued
// acknowledgment, interleaved by their real created_at -- nothing is invented.
function buildConversationScenario(detail) {
  const events = [
    ...detail.imagery.map((imagery) => ({ kind: 'imagery', at: imagery.created_at, imagery })),
    ...detail.jobs.map((job) => ({ kind: 'job', at: job.created_at, job }))
  ].sort((a, b) => new Date(a.at) - new Date(b.at));

  const chatHistory = [];
  const shownPairs = new Set();
  // The most recent upload (single image or pair) is the chat's active image
  // context, exactly as it was when the chat was left.
  let latestAttachment = null;
  events.forEach((event) => {
    const ts = formatTime(event.at);
    if (event.kind === 'imagery') {
      const { imagery } = event;
      if (imagery.pair_id && shownPairs.has(imagery.pair_id)) return; // its partner already rendered the pair
      if (imagery.pair_id) shownPairs.add(imagery.pair_id);
      latestAttachment = attachmentForImageryRow(imagery, detail.imagery);
      chatHistory.push({
        id: `img-${imagery.id}`,
        sender: 'user',
        text: '',
        timestamp: ts,
        attachment: latestAttachment
      });
      return;
    }
    const { job } = event;
    const imagery = detail.imagery.find(i => i.id === job.imagery_id);
    chatHistory.push({ id: `usr-${job.id}`, sender: 'user', text: job.query, timestamp: ts });
    chatHistory.push({
      id: `ai-${job.id}`,
      sender: 'ai',
      text: 'Analysis request submitted.',
      status: job.status,
      jobId: job.id,
      timestamp: ts,
      evidenceThumb: getImageryPreviewUrl(imagery)
    });
  });

  const latestImagery = latestAttachment
    ? detail.imagery.find(i => i.id === latestAttachment.imageryId) || null
    : null;
  return {
    id: latestImagery?.id || null,
    conversationId: detail.id,
    title: latestAttachment ? (latestAttachment.isPair ? latestAttachment.name : latestImagery.name) : 'Untitled',
    sensor: latestImagery?.sensor || null,
    resolution: latestImagery ? formatFileSize(latestImagery.file_size) : null,
    opticalImg: latestAttachment?.previewUrl || null,
    uploadedFile: latestAttachment,
    chatHistory
  };
}

// Builds the scenario for a LEGACY chat (made before conversations existed):
// one imagery record plus its analysis_jobs. Every field traces back to a real
// record -- nothing is invented (see CLAUDE.md "no dummy data" scope).
function buildLegacyScenario(imagery, historyItemsForImage = []) {
  const chatHistory = [];
  // Oldest first, matching a natural chat reading order.
  [...historyItemsForImage].reverse().forEach((item) => {
    const ts = formatTime(item.created_at);
    chatHistory.push({
      id: `usr-${item.job_id}`,
      sender: 'user',
      text: item.query,
      timestamp: ts
    });
    chatHistory.push({
      id: `ai-${item.job_id}`,
      sender: 'ai',
      text: 'Analysis request submitted.',
      status: item.status,
      jobId: item.job_id,
      timestamp: ts,
      evidenceThumb: getImageryPreviewUrl(imagery)
    });
  });

  return {
    id: imagery.id,
    conversationId: null,
    isLegacy: true,
    title: imagery.name,
    sensor: imagery.sensor || null,
    resolution: formatFileSize(imagery.file_size),
    opticalImg: getImageryPreviewUrl(imagery),
    uploadedFile: attachmentFromImagery(imagery),
    chatHistory
  };
}

function AppHeader({ theme, toggleTheme, activeScreen, handleNewChat, onGoBack }) {
  const { open } = useSidebar();

  return (
    <header className="minimal-header">
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        {/* Prominent Back Button on Top Left for every window other than landing */}
        {activeScreen !== 'landing' && (
          <button
            id="satquery-header-back-btn"
            className="btn-header-back"
            onClick={onGoBack}
            title="Go back to previous screen"
          >
            <ArrowLeft size={18} />
            <span>Back</span>
          </button>
        )}

        {/* Sidebar Trigger Tab and Brand Logo/Title */}
        {!open && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }} className="animate-in fade-in duration-200">
            <SidebarTrigger
              className="sidebar-tab-trigger-btn"
              title="Open History Sidebar"
            />
            <div 
              className="brand-section" 
              onClick={handleNewChat}
              title="SatQuery AI - New Analysis"
              style={{ cursor: 'pointer', padding: '4px 8px' }}
            >
              <div className="brand-logo-badge" style={{ width: 46, height: 46, padding: 3 }}>
                <ChitravitsEmblem size={38} />
              </div>
              <span className="brand-title" style={{ fontSize: '1.32rem', fontWeight: 700, letterSpacing: '-0.025em' }}>
                Sat<span className="brand-title-accent">Query</span> <span className="brand-title-ai" style={{ fontSize: '0.76rem', padding: '2.5px 8px', marginLeft: 6 }}>AI</span>
              </span>
            </div>
          </div>
        )}

        {/* Clean Screen Title for Context */}
        {activeScreen !== 'landing' && (
          <span style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'capitalize', letterSpacing: '-0.015em' }}>
            / {activeScreen.replace('-', ' ')}
          </span>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <button 
          id="satquery-theme-toggle-btn"
          className="theme-toggle-btn"
          style={{ width: 46, height: 46 }}
          onClick={toggleTheme}
          title={`Switch to ${theme === 'dark' ? 'Light Theme' : 'Dark Theme'}`}
          aria-label="Toggle theme"
        >
          {theme === 'dark' ? <Sun size={22} /> : <Moon size={22} />}
        </button>
      </div>
    </header>
  );
}

function SidebarBackdrop() {
  const { open, setOpen, isMobile } = useSidebar();
  if (!open || !isMobile) return null;
  return (
    <div 
      className="sidebar-backdrop-overlay" 
      onClick={() => setOpen(false)}
      title="Tap to shrink and slide sidebar"
      aria-label="Close sidebar"
    />
  );
}

export function App() {
  // Theme preference ('dark' | 'light' | 'system', saved in user_settings) and
  // the theme actually shown. 'system' follows the OS setting live.
  const [themePreference, setThemePreference] = useState(() => readPointer(THEME_KEY) || localStorage.getItem('satquery-theme') || 'dark');
  const [sidebarDensity, setSidebarDensity] = useState(() => readPointer(DENSITY_KEY) || 'comfortable');
  const [systemPrefersDark, setSystemPrefersDark] = useState(prefersDarkScheme);
  const theme = themePreference === 'system' ? (systemPrefersDark ? 'dark' : 'light') : themePreference;
  // Patterned theme wavefront state (ISRO satellite + NASA Earth animation)
  const [themeWave, setThemeWave] = useState(null);

  // Active Screen state: 'landing', or the profile/settings screen if it was open before a refresh.
  const initialScreenRef = useRef(
    RESTORABLE_SCREENS.includes(readPointer(LAST_SCREEN_KEY)) ? readPointer(LAST_SCREEN_KEY) : 'landing'
  );
  const [activeScreen, setActiveScreen] = useState(initialScreenRef.current);
  // Navigation history stack for step-by-step back navigation
  const [historyStack, setHistoryStack] = useState([]);

  // Attached Custom AI Model state (Folder Drag & Drop)
  const [activeModel, setActiveModel] = useState(() => getActiveModel());
  // ChatGPT-Style Projects state
  const [projects, setProjects] = useState([]);
  const [activeProject, setActiveProject] = useState(null);
  const activeProjectRef = useRef(null);
  // The project id that should be pre-opened when ProjectsScreen mounts
  // (set when user clicks a project card in the sidebar).
  const [initialProjectId, setInitialProjectId] = useState(null);

  useEffect(() => {
    activeProjectRef.current = activeProject;
  }, [activeProject]);

  const handleSelectModel = (model) => {
    setActiveModel(model);
    setActiveModelId(model ? model.id : null);
  };

  const handleOpenProject = (project) => {
    // Track which specific project to open so ProjectsScreen can deep-link
    // into it on mount without a second round-trip or state conflict.
    setInitialProjectId(project ? project.id : null);
    setActiveProject(project);
    setActiveProjectId(project ? project.id : null);
    navigateToScreen('projects');
  };

  const handleStartProjectChat = (project) => {
    setActiveProject(project);
    setActiveProjectId(project.id);
    handleNewChat();
    navigateToScreen('landing');
  };

  const navigateToScreen = (screenId) => {
    if (screenId !== activeScreen) {
      setHistoryStack(prev => [...prev, activeScreen]);
      setActiveScreen(screenId);
    }
  };

  // Navigate to projects listing (from sidebar shortcut — no specific project).
  const navigateToProjectsList = () => {
    setInitialProjectId(null);
    navigateToScreen('projects');
  };

  const handleGoBack = () => {
    if (historyStack.length > 0) {
      const prevScreen = historyStack[historyStack.length - 1];
      setHistoryStack(prev => prev.slice(0, -1));
      setActiveScreen(prevScreen);
    } else {
      setActiveScreen('landing');
    }
  };

  // Legacy mock scenario -- kept ONLY for the pre-existing Change/Fusion/Pipeline/
  // Analytics/Report screens, which are out of scope for the backend-persistence
  // milestone (no AI/raster analysis exists to drive them with real data yet).
  // The primary upload -> query -> history flow below never reads from this.
  const [currentScenario] = useState(SATELLITE_SCENARIOS[0]);

  // Real, backend-driven state for the Workspace screen. Built exclusively
  // from actual imagery/analysis_jobs records -- see buildWorkspaceScenario().
  const [workspaceScenario, setWorkspaceScenario] = useState(null);
  // Bumped whenever a new analysis request is submitted, so the sidebar
  // (which owns its own fetch) knows to refetch GET /api/v1/analysis/history.
  const [historyRefreshToken, setHistoryRefreshToken] = useState(0);
  const bumpHistory = useCallback(() => setHistoryRefreshToken(t => t + 1), []);

  // The open conversation ({ id, title, title_source }), or null for a new,
  // unsaved chat. New Chat never writes to the backend: the record is created
  // lazily by the first upload, just before the file is stored (see
  // ensureConversation). If that upload then fails, the empty row is hidden
  // by GET /conversations and purgeable (backend/scripts/purge_empty_conversations.py).
  // It's titled "New Chat" until the first
  // meaningful query -- an uploaded filename never becomes its title.
  const [activeConversation, setActiveConversation] = useState(null);
  const activeConversationRef = useRef(null);
  const pendingConversationRef = useRef(null);
  // An EMPTY conversation that was reopened (one left behind by the old
  // eager New Chat, restored on refresh) and the ids an upload has since been
  // started into. It's "fresh" -- reusable by the landing upload instead of
  // creating another record -- only while it's in the first and not the
  // second. A Set rather than a flag, so the check doesn't depend on which
  // awaiting caller resumes first.
  const freshConversationIdRef = useRef(null);
  const usedConversationIdsRef = useRef(new Set());
  // Bumped by New Chat to remount LandingHero, clearing its typed query and
  // selected file even when the landing screen is already showing.
  const [landingKey, setLandingKey] = useState(0);

  const openConversation = useCallback((conversation) => {
    const value = conversation
      ? { id: conversation.id, title: conversation.title, title_source: conversation.title_source }
      : null;
    activeConversationRef.current = value;
    pendingConversationRef.current = null;
    setActiveConversation(value);
    rememberPointer(LAST_CONVERSATION_KEY, value?.id);
  }, []);

  // Returns the open conversation's id, creating it on first use (the first
  // upload). Concurrent callers share one in-flight request so a chat never
  // gets two records. The sidebar isn't refreshed here but once the upload
  // lands (onImageryUploaded), so it never shows a conversation with nothing in it.
  const ensureConversation = useCallback(async () => {
    if (activeConversationRef.current) return activeConversationRef.current.id;
    if (!pendingConversationRef.current) {
      const projId = activeProjectRef.current?.id || null;
      const pending = createConversation(projId ? { project_id: projId } : null).then((conversation) => {
        // Not opened if New Chat was clicked meanwhile -- the upload still
        // goes into it, but the user has moved on to a new chat.
        if (pendingConversationRef.current === pending) openConversation(conversation);
        return conversation.id;
      });
      pending.catch(() => {
        if (pendingConversationRef.current === pending) pendingConversationRef.current = null;
      });
      pendingConversationRef.current = pending;
    }
    return pendingConversationRef.current;
  }, [openConversation]);

  const isFreshConversation = useCallback((conversation) =>
    Boolean(conversation)
    && conversation.id === freshConversationIdRef.current
    && !usedConversationIdsRef.current.has(conversation.id), []);

  const markConversationUsed = useCallback((conversationId) => {
    if (conversationId) usedConversationIdsRef.current.add(conversationId);
    return conversationId;
  }, []);

  // Landing-screen upload: the point where a new chat is first persisted.
  // Reuses a creation already in flight, or a reopened empty conversation;
  // otherwise -- after New Chat, or landing reached via Back from a chat --
  // it creates a NEW conversation.
  const startConversation = useCallback(async () => {
    if (pendingConversationRef.current) {
      return markConversationUsed(await pendingConversationRef.current);
    }
    if (isFreshConversation(activeConversationRef.current)) {
      return markConversationUsed(activeConversationRef.current.id);
    }
    openConversation(null);
    return markConversationUsed(await ensureConversation());
  }, [openConversation, ensureConversation, isFreshConversation, markConversationUsed]);

  // Mid-chat upload with no conversation yet (Workspace).
  const ensureConversationForUpload = useCallback(
    async () => markConversationUsed(await ensureConversation()),
    [ensureConversation, markConversationUsed]
  );

  // Called after every successfully submitted query. The title is generated
  // in the background (never blocks the chat) and only while the chat is
  // still "New Chat": the backend titles from the FIRST meaningful stored
  // query and ignores later calls, so follow-ups and renames never overwrite it.
  const handleQuerySubmitted = useCallback((conversationId) => {
    bumpHistory();
    if (!conversationId) return;
    const current = activeConversationRef.current;
    if (current?.id === conversationId && current.title_source !== 'default') return;
    generateConversationTitle(conversationId)
      .then((conversation) => {
        if (activeConversationRef.current?.id === conversation.id) {
          openConversation(conversation);
        }
        if (conversation.title_source !== 'default') bumpHistory();
      })
      .catch((err) => console.error('[SatQuery] Could not generate conversation title:', err));
  }, [bumpHistory, openConversation]);

  // Application initial bootstrap loading state
  const [isInitializing, setIsInitializing] = useState(true);
  const [isExitingLoader, setIsExitingLoader] = useState(false);
  const [initStepText, setInitStepText] = useState('Initializing SatQuery AI...');
  const [initError, setInitError] = useState(null);

  // The single workspace profile (GET /profile) shown in the sidebar footer.
  // null until loaded, or if the backend can't provide it -- never a made-up user.
  const [profileUser, setProfileUser] = useState(null);

  useEffect(() => {
    rememberPointer(LAST_SCREEN_KEY, RESTORABLE_SCREENS.includes(activeScreen) ? activeScreen : null);
  }, [activeScreen]);

  // Settings (GET/PATCH /settings). App owns them so the header's theme toggle,
  // the sidebar density and the Settings screen always agree.
  const [settingsState, setSettingsState] = useState({ status: 'loading', data: null, error: null });
  const settingsRef = useRef(null);
  const settingsSaveSeqRef = useRef(0);

  const showSettings = useCallback((data) => {
    settingsRef.current = data;
    setSettingsState({ status: 'ready', data, error: null });
    setThemePreference(data.preferences.theme);
    setSidebarDensity(data.preferences.sidebar_density);
    // Read the OS setting now rather than trusting the value from page load.
    if (data.preferences.theme === 'system') setSystemPrefersDark(prefersDarkScheme());
  }, []);

  const loadSettings = useCallback(() => {
    setSettingsState((state) => ({ ...state, status: 'loading', error: null }));
    getSettings()
      .then(showSettings)
      .catch((error) => {
        console.error('[SatQuery] Could not load settings:', error);
        settingsRef.current = null;
        setSettingsState({ status: 'error', data: null, error });
      });
  }, [showSettings]);

  // Centralized Application Initialization Sequence
  const initApplication = useCallback(async () => {
    setIsInitializing(true);
    setIsExitingLoader(false);
    setInitError(null);
    console.log('[SatQuery] Initializing application...');

    try {
      // 1. Settings & Profile
      setInitStepText('Connecting to SatQuery...');
      const [settingsRes, profileRes] = await Promise.allSettled([
        getSettings(),
        getProfile()
      ]);

      if (settingsRes.status === 'rejected' && profileRes.status === 'rejected') {
        const err = settingsRes.reason || profileRes.reason;
        console.error('[SatQuery] Application initialization failed:', err);
        setInitError(err?.message || 'Failed to connect to SatQuery backend services.');
        return;
      }

      if (settingsRes.status === 'fulfilled' && settingsRes.value) {
        showSettings(settingsRes.value);
        console.log('[SatQuery] Settings loaded');
      } else if (settingsRes.status === 'rejected') {
        console.warn('[SatQuery] Settings load warning:', settingsRes.reason);
      }

      if (profileRes.status === 'fulfilled' && profileRes.value?.user) {
        setProfileUser(profileRes.value.user);
        console.log('[SatQuery] Profile loaded');
      } else if (profileRes.status === 'rejected') {
        console.warn('[SatQuery] Profile load warning:', profileRes.reason);
      }

      // 2. Projects
      setInitStepText('Syncing projects workspace...');
      try {
        const projList = await listProjects();
        setProjects(projList);
        console.log('[SatQuery] Projects loaded');
        const activeId = getActiveProjectId();
        if (activeId) {
          const proj = await getProject(activeId).catch(() => null);
          if (proj) setActiveProject(proj);
        }
      } catch (err) {
        console.warn('[SatQuery] Projects load warning:', err);
      }

      // 3. Conversations history
      setInitStepText('Syncing conversations...');
      try {
        await listConversations(100);
        console.log('[SatQuery] Conversations loaded');
      } catch (err) {
        console.warn('[SatQuery] Conversations load warning:', err);
      }

      // 4. Session workspace restoration if pointers exist
      setInitStepText('Preparing workspace...');
      const showRestoredWorkspace = () => {
        if (initialScreenRef.current !== 'landing') setHistoryStack(['workspace']);
        else setActiveScreen('workspace');
      };
      let lastConversationId;
      let lastImageryId;
      try {
        lastConversationId = localStorage.getItem(LAST_CONVERSATION_KEY);
        lastImageryId = localStorage.getItem(LAST_IMAGERY_KEY);
      } catch {}

      if (lastConversationId) {
        try {
          const detail = await getConversation(lastConversationId);
          openConversation(detail);
          if (isEmptyConversation(detail)) {
            freshConversationIdRef.current = detail.id;
          } else {
            setWorkspaceScenario(buildConversationScenario(detail));
            showRestoredWorkspace();
          }
        } catch (err) {
          console.error('[SatQuery] Could not restore last conversation:', err);
          rememberPointer(LAST_CONVERSATION_KEY, null);
        }
      } else if (lastImageryId) {
        try {
          const [imagery, history] = await Promise.all([
            getImagery(lastImageryId),
            getAnalysisHistory(200).catch(() => [])
          ]);
          const itemsForImage = history.filter(h => h.imagery_id === lastImageryId);
          setWorkspaceScenario(buildLegacyScenario(imagery, itemsForImage));
          showRestoredWorkspace();
        } catch (err) {
          console.error('[SatQuery] Could not restore last session:', err);
          try { localStorage.removeItem(LAST_IMAGERY_KEY); } catch {}
        }
      }

      console.log('[SatQuery] Application ready');
      setIsExitingLoader(true);
      setTimeout(() => {
        setIsInitializing(false);
        setIsExitingLoader(false);
      }, 300);
    } catch (err) {
      console.error('[SatQuery] Initialization error:', err);
      setInitError(err?.message || 'Failed to initialize application.');
    }
  }, [showSettings, openConversation]);

  useEffect(() => {
    initApplication();
  }, [initApplication]);

  // Optimistic: the change shows at once; the server's answer to the LATEST
  // save wins, and a failed save puts the previous values back.
  const saveSettings = useCallback(async (changes) => {
    const previous = settingsRef.current;
    if (!previous) throw new Error('Settings are not loaded.');
    const seq = ++settingsSaveSeqRef.current;
    showSettings(applySettingsChanges(previous, changes));
    try {
      const saved = await updateSettings(changes);
      if (seq === settingsSaveSeqRef.current) showSettings(saved);
      return saved;
    } catch (err) {
      if (seq === settingsSaveSeqRef.current) showSettings(previous);
      throw err;
    }
  }, [showSettings]);

  // A profile edit (Settings or Profile screen): refresh the sidebar footer and
  // the profile block of the loaded settings.
  const handleProfileSaved = useCallback((user) => {
    setProfileUser(user);
    const current = settingsRef.current;
    if (current) {
      const { display_name, username, avatar_url, bio } = user;
      showSettings({ ...current, profile: { display_name, username, avatar_url, bio } });
    }
  }, [showSettings]);

  // Header sun/moon: triggers high-speed aerospace theme transition wavefront and updates preferences.
  const toggleTheme = (e) => {
    const nextTheme = theme === 'dark' ? 'light' : 'dark';
    executeThemeTransition(nextTheme, e, {
      onThemeUpdate: (t) => {
        setThemePreference(t);
        try { localStorage.setItem('satquery-theme', t); } catch {}
        if (settingsRef.current) {
          saveSettings({ theme: t }).catch((err) => console.error('[SatQuery] Could not save theme:', err));
        }
      },
      onWaveStart: (wave) => setThemeWave(wave),
      onWaveEnd: () => setThemeWave(null)
    });
  };

  // Real upload -> real (optional) query flow. No AI response is ever
  // fabricated: on success the UI shows a neutral "queued" acknowledgment;
  // on any failure it shows the actual error. An upload with no typed query
  // submits nothing -- the chat stays "New Chat" until the user asks.
  const handleStartAnalysis = async (queryPrompt, imageAttachment) => {
    const promptText = queryPrompt?.trim() || '';
    const imageryId = imageAttachment?.imageryId;
    const conversationId = imageAttachment?.conversationId || null;
    const nowTs = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const userMsg = {
      id: `usr-${Date.now()}`,
      sender: 'user',
      text: promptText,
      timestamp: nowTs(),
      attachment: imageAttachment || null
    };

    if (!imageryId) {
      // Either no image was ever attached, or its upload to the backend
      // failed -- either way there is no real imagery_id to submit against.
      setWorkspaceScenario({
        id: null,
        conversationId: null,
        title: imageAttachment?.name || 'Untitled',
        sensor: null,
        resolution: null,
        opticalImg: imageAttachment?.previewUrl || null,
        uploadedFile: imageAttachment || null,
        chatHistory: [
          userMsg,
          {
            id: `ai-${Date.now()}`,
            sender: 'ai',
            text: imageAttachment
              ? 'This image could not be uploaded to the backend, so no analysis request could be submitted. Please try attaching it again.'
              : 'Please attach a satellite image before submitting a query -- an analysis request must reference an uploaded image.',
            isError: true,
            timestamp: nowTs()
          }
        ]
      });
      navigateToScreen('workspace');
      return;
    }

    rememberPointer(LAST_IMAGERY_KEY, null);

    const chatHistory = [userMsg];

    if (promptText) {
      try {
        const job = await submitAnalysis(
          imageryId, 'general_analysis', promptText, conversationId, imageAttachment.comparisonImageryId
        );
        chatHistory.push({
          id: `ai-${Date.now()}`,
          sender: 'ai',
          text: 'Analysis request submitted.',
          status: job.status,
          jobId: job.job_id,
          timestamp: nowTs(),
          evidenceThumb: imageAttachment.previewUrl
        });
        handleQuerySubmitted(conversationId);
      } catch (err) {
        chatHistory.push({
          id: `ai-${Date.now()}`,
          sender: 'ai',
          text: `Failed to submit analysis request: ${err.message || 'unknown error'}`,
          isError: true,
          timestamp: nowTs()
        });
      }
    }

    setWorkspaceScenario({
      id: imageryId,
      conversationId,
      title: imageAttachment.name,
      sensor: null,
      resolution: imageAttachment.size || null,
      opticalImg: imageAttachment.previewUrl,
      uploadedFile: imageAttachment,
      chatHistory
    });
    navigateToScreen('workspace');
  };

  // New Chat only resets frontend state -- it never writes to the backend.
  // The conversation record is created by the first upload (startConversation
  // / ensureConversation), so clicking it any number of times persists nothing.
  const handleNewChat = () => {
    openConversation(null); // also drops any creation still in flight
    freshConversationIdRef.current = null;
    rememberPointer(LAST_IMAGERY_KEY, null);
    setWorkspaceScenario(null);
    setLandingKey(k => k + 1);
    setHistoryStack([]);
    setActiveScreen('landing');
  };

  // Sidebar conversation -> reload its real uploads + queries from the backend.
  const handleSelectConversation = async (conversation) => {
    try {
      const detail = await getConversation(conversation.id);
      openConversation(detail);
      rememberPointer(LAST_IMAGERY_KEY, null);
      if (isEmptyConversation(detail)) {
        // Nothing to show yet: open the upload screen for this conversation.
        freshConversationIdRef.current = detail.id;
        usedConversationIdsRef.current.delete(detail.id);
        navigateToScreen('landing');
        return;
      }
      setWorkspaceScenario(buildConversationScenario(detail));
      navigateToScreen('workspace');
    } catch (err) {
      console.error('[SatQuery] Could not load conversation:', err);
    }
  };

  const handleConversationRenamed = (conversation) => {
    if (activeConversationRef.current?.id === conversation.id) openConversation(conversation);
  };

  const handleConversationDeleted = (conversationId) => {
    if (activeConversationRef.current?.id === conversationId) {
      openConversation(null);
      setWorkspaceScenario(null);
      setHistoryStack([]);
      setActiveScreen('landing');
    }
  };

  // Legacy sidebar item (pre-conversation history) -> reload the real imagery
  // + its real query/ack messages from the backend. Never fabricates a chat.
  const handleSelectHistoryItem = async (historyItem) => {
    try {
      const [imagery, history] = await Promise.all([
        getImagery(historyItem.imagery_id),
        getAnalysisHistory(200)
      ]);
      const itemsForImage = history.filter(h => h.imagery_id === historyItem.imagery_id);
      openConversation(null);
      setWorkspaceScenario(buildLegacyScenario(imagery, itemsForImage));
      rememberPointer(LAST_IMAGERY_KEY, historyItem.imagery_id);
      navigateToScreen('workspace');
    } catch (err) {
      console.error('[SatQuery] Could not load history item:', err);
    }
  };

  return (
    <SidebarProvider defaultOpen={true}>
      {/* SatQuery Satellite Intelligence Initial Workspace Loader */}
      {isInitializing && (
        <InitialLoader
          stepText={initStepText}
          error={initError}
          onRetry={initApplication}
          isExiting={isExitingLoader}
        />
      )}

      {/* High-Tech Aerospace Theme Transition Wavefront */}
      <ThemeTransitionWave wave={themeWave} />

      {/* ChatGPT-Style User History Sidebar */}
      <UserHistorySidebar
        onNewChat={handleNewChat}
        onSelectConversation={handleSelectConversation}
        onSelectHistoryItem={handleSelectHistoryItem}
        onConversationRenamed={handleConversationRenamed}
        onConversationDeleted={handleConversationDeleted}
        onNavigateScreen={(screenId) => {
          // The sidebar Projects shortcut should always show the full list,
          // never jump into a specific project workspace.
          if (screenId === 'projects') navigateToProjectsList();
          else navigateToScreen(screenId);
        }}
        activeScreen={activeScreen}
        activeConversationId={activeConversation?.id || null}
        activeImageryId={workspaceScenario?.isLegacy ? workspaceScenario.id : null}
        refreshToken={historyRefreshToken}
        profileUser={profileUser}
        onOpenProfile={() => navigateToScreen('profile')}
        theme={theme}
        onToggleTheme={toggleTheme}
        activeModel={activeModel}
        projects={projects}
        activeProjectId={activeProject?.id || null}
        onOpenProject={handleOpenProject}
        onOpenSettings={() => navigateToScreen('settings')}
      />

      <SidebarInset className="flex-1 flex flex-col min-w-0 min-h-screen relative overflow-x-hidden bg-transparent">
          {/* Smooth Backdrop for tapping on screen to shrink/close sidebar */}
          <SidebarBackdrop />

          {/* Dynamic Ambient Background: Synchronized 60fps hardware-accelerated cross-fade */}
          <div style={{ position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 0, overflow: 'hidden' }}>
            <div 
              style={{ 
                position: 'absolute', 
                inset: 0, 
                opacity: theme === 'light' ? 1 : 0, 
                transition: 'opacity 0.38s cubic-bezier(0.16, 1, 0.3, 1)',
                willChange: 'opacity'
              }}
            >
              <GradientBackground variant="light-white" className="w-full h-full" />
            </div>
            <div 
              style={{ 
                position: 'absolute', 
                inset: 0, 
                opacity: theme === 'dark' ? 1 : 0, 
                transition: 'opacity 0.38s cubic-bezier(0.16, 1, 0.3, 1)',
                willChange: 'opacity'
              }}
            >
              <GradientBackground variant="dark-blue" className="w-full h-full" />
            </div>
          </div>

          {/* Minimalist Header without duplicate sidebar or duplicate action buttons */}
          <AppHeader 
            theme={theme}
            toggleTheme={toggleTheme}
            activeScreen={activeScreen}
            handleNewChat={handleNewChat}
            onGoBack={handleGoBack}
          />

          {/* Screen Routing with Step-by-Step Back Option */}
          <main style={{ flex: 1, position: 'relative', zIndex: 1 }}>
            {activeScreen === 'landing' && (
              <LandingHero
                key={landingKey}
                onStartAnalysis={handleStartAnalysis}
                onStartConversation={startConversation}
                onImageryUploaded={bumpHistory}
                activeModel={activeModel}
                activeProject={activeProject}
                onNavigateScreen={navigateToScreen}
              />
            )}

            {activeScreen === 'model-attach' && (
              <ModelAttachmentScreen
                onGoBack={handleGoBack}
                onSelectModel={handleSelectModel}
                activeModelId={activeModel?.id}
              />
            )}

            {activeScreen === 'projects' && (
              <ProjectsScreen
                key={initialProjectId ?? 'projects-list'}
                onGoBack={() => {
                  setInitialProjectId(null);
                  handleGoBack();
                }}
                onStartProjectChat={handleStartProjectChat}
                onOpenConversation={handleSelectConversation}
                initialProjectId={initialProjectId}
              />
            )}

            {activeScreen === 'workspace' && workspaceScenario && (
              <Workspace
                scenario={workspaceScenario}
                onNavigateScreen={navigateToScreen}
                onGoBack={handleGoBack}
                onEnsureConversation={ensureConversationForUpload}
                onAnalysisSubmitted={handleQuerySubmitted}
                onImageryUploaded={bumpHistory}
                activeModel={activeModel}
                activeProject={activeProject}
              />
            )}

            {activeScreen === 'profile' && (
              <ProfileDashboard onProfileUpdated={handleProfileSaved} />
            )}

            {activeScreen === 'settings' && (
              <SettingsPage
                settingsState={settingsState}
                onRetry={loadSettings}
                onSave={saveSettings}
                onProfileSaved={handleProfileSaved}
              />
            )}

            {activeScreen === 'viewer' && (
              <div style={{ height: 'calc(100vh - 75px)', padding: 'var(--space-6)' }}>
                <ImageViewer 
                  imageUrl={currentScenario.opticalImg} 
                  scenario={currentScenario}
                  onGoBack={handleGoBack}
                />
              </div>
            )}

            {activeScreen === 'change' && (
              <ChangeDetection scenario={currentScenario} onGoBack={handleGoBack} />
            )}

            {activeScreen === 'fusion' && (
              <FusionViewer scenario={currentScenario} onGoBack={handleGoBack} />
            )}


            {activeScreen === 'analytics' && (
              <AnalyticsDashboard scenario={currentScenario} onGoBack={handleGoBack} />
            )}

            {activeScreen === 'report' && (
              <ReportScreen scenario={currentScenario} onGoBack={handleGoBack} />
            )}
          </main>
      </SidebarInset>
    </SidebarProvider>
  );
}

export default App;
