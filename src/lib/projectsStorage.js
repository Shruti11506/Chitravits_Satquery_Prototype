/**
 * SatQuery AI - Projects Storage & Pointer Manager
 * Manages active project selection pointers.
 * Real project data is persisted in Supabase via FastAPI backend.
 */

const STORAGE_KEY_ACTIVE_PROJECT = 'satquery-active-project-id';

export function getActiveProjectId() {
  try {
    return localStorage.getItem(STORAGE_KEY_ACTIVE_PROJECT) || null;
  } catch {
    return null;
  }
}

export function setActiveProjectId(id) {
  try {
    if (id) {
      localStorage.setItem(STORAGE_KEY_ACTIVE_PROJECT, id);
    } else {
      localStorage.removeItem(STORAGE_KEY_ACTIVE_PROJECT);
    }
  } catch (err) {
    console.error('[SatQuery] Error setting active project id:', err);
  }
}
