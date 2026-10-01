/**
 * Centralized client for the SatQuery FastAPI backend -- the only place the
 * frontend talks to it. Uploads go to Supabase Storage, queries create real
 * (queued) analysis_jobs rows, and both are grouped under a conversation,
 * which is what the sidebar lists. There is no AI layer yet: nothing here
 * returns or fabricates an analysis answer.
 */

const rawBaseUrl =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() || "http://localhost:8000/api/v1";
const cleanBaseUrl = rawBaseUrl.replace(/\/+$/, "");
const API_BASE_URL = cleanBaseUrl.endsWith("/api/v1") ? cleanBaseUrl : `${cleanBaseUrl}/api/v1`;

export interface ApiError {
  code: string;
  message: string;
  /** Optional structured context beyond one message -- e.g. the
   * change-detection compatibility gate (POST /analysis) attaches the full
   * list of failed checks plus a T1/T2 summary here. Absent for most errors. */
  details?: Record<string, unknown> | null;
}

export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: ApiError | null;
}

export class ApiRequestError extends Error {
  code: string;
  status: number;
  details: Record<string, unknown> | null;

  constructor(status: number, error: ApiError) {
    super(error.message);
    this.name = "ApiRequestError";
    this.code = error.code;
    this.status = status;
    this.details = error.details ?? null;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        // Never set Content-Type for FormData -- the browser must generate the
        // multipart boundary itself, and a manual header here breaks parsing.
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
    });
  } catch {
    // The browser only says "Failed to fetch": name what it couldn't reach.
    // On a fresh clone this means the local backend isn't running (see README).
    throw new ApiRequestError(0, {
      code: "BACKEND_UNREACHABLE",
      message: `Cannot reach the SatQuery backend at ${API_BASE_URL} -- is it running? (see README.md)`,
    });
  }

  const body: ApiResponse<T> = await response.json();

  if (!response.ok || !body.success) {
    throw new ApiRequestError(
      response.status,
      body.error || { code: "UNKNOWN_ERROR", message: "Request failed." }
    );
  }

  return body.data as T;
}

// ---- Health ----------------------------------------------------------

export function getHealth() {
  return request<{ status: string; service: string; version: string }>("/health");
}

export function getSupabaseHealth() {
  return request<{ supabase: string; database: string; storage: string; bucket: string }>(
    "/health/supabase"
  );
}

// ---- Imagery -----------------------------------------------------------

export interface ImageryPayload {
  name: string;
  source?: string;
  sensor?: string;
  acquisition_date?: string;
  storage_path?: string;
  bucket?: string;
  storage_url?: string;
  cloud_cover?: number;
  latitude?: number;
  longitude?: number;
  bbox?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface ImageryUploadResult {
  id: string;
  name: string;
  original_filename: string;
  bucket: string;
  storage_path: string;
  mime_type: string;
  file_size: number;
  status: string;
  /** TIFF/GeoTIFF only: signed URL of the generated PNG preview, and georeference read from the file. */
  thumbnail_url?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  bbox?: Record<string, unknown> | null;
  cloud_cover?: number | null;
  acquisition_date?: string | null;
  /** Image pairs only: shared id, and 1 = Image 1 (reference) / 2 = Image 2 (comparison). */
  pair_id?: string | null;
  pair_position?: 1 | 2 | null;
  /** TIFF only: generated PNG preview (the original stays at storage_path). */
  preview_path?: string | null;
  preview_status?: "ready" | "failed" | null;
  /** TIFF only: what the file is (properties), how the preview was made, preview_error. */
  raster?: Record<string, unknown> | null;
}

export interface ImageryPairUploadResult {
  pair_id: string;
  image_1: ImageryUploadResult;
  image_2: ImageryUploadResult;
}

export interface ImageryRecord extends ImageryPayload {
  id: string;
  conversation_id?: string | null;
  original_filename: string | null;
  mime_type: string | null;
  file_size: number | null;
  /** Freshly-resolved signed (private bucket) or public URL. Re-fetch via getImagery() rather than caching. */
  url: string | null;
  /** Signed URL of the PNG preview generated for a TIFF/GeoTIFF; null when there is none. */
  thumbnail_url?: string | null;
  /** Image pairs only: shared id, and 1 = Image 1 (reference) / 2 = Image 2 (comparison). */
  pair_id?: string | null;
  pair_position?: 1 | 2 | null;
  /** TIFF only: generated PNG preview path; "failed" when none could be made. */
  preview_path?: string | null;
  preview_status?: "ready" | "failed" | null;
  created_at: string;
}

/** Uploads a file to Supabase Storage (bucket: Satquery) via FastAPI and registers its metadata. */
export function uploadImagery(
  file: File,
  meta?: {
    name?: string;
    source?: string;
    sensor?: string;
    acquisition_date?: string;
    metadata?: Record<string, unknown>;
    /** Groups the upload under a conversation. Never changes its title. */
    conversationId?: string;
  }
) {
  const form = new FormData();
  form.append("file", file);
  if (meta?.name) form.append("name", meta.name);
  if (meta?.source) form.append("source", meta.source);
  if (meta?.sensor) form.append("sensor", meta.sensor);
  if (meta?.acquisition_date) form.append("acquisition_date", meta.acquisition_date);
  if (meta?.metadata) form.append("metadata", JSON.stringify(meta.metadata));
  if (meta?.conversationId) form.append("conversation_id", meta.conversationId);

  return request<ImageryUploadResult>("/imagery/upload", {
    method: "POST",
    body: form,
  });
}

/**
 * Uploads an image pair (Image 1 = reference, Image 2 = comparison) in one
 * request. Both files are stored independently; the backend stores both or
 * neither.
 */
export function uploadImageryPair(image1: File, image2: File, meta?: { conversationId?: string }) {
  const form = new FormData();
  form.append("image_1", image1);
  form.append("image_2", image2);
  if (meta?.conversationId) form.append("conversation_id", meta.conversationId);

  return request<ImageryPairUploadResult>("/imagery/pair", {
    method: "POST",
    body: form,
  });
}

export function registerImagery(payload: ImageryPayload) {
  return request<{ id: string; name: string; status: string }>("/imagery", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listImagery(page = 1, pageSize = 20) {
  return request<{
    items: ImageryRecord[];
    pagination: { page: number; page_size: number; total: number };
  }>(`/imagery?page=${page}&page_size=${pageSize}`);
}

export function getImagery(imageryId: string) {
  return request<ImageryRecord>(`/imagery/${imageryId}`);
}

export function deleteImagery(imageryId: string) {
  return request<{ id: string; status: string }>(`/imagery/${imageryId}`, {
    method: "DELETE",
  });
}

// ---- Analysis / Jobs / Results / Evidence -------------------------------

export type AnalysisType =
  | "vqa"
  | "captioning"
  | "scene_description"
  | "change_detection"
  | "change_vqa"
  | "optical_sar_analysis"
  | "region_grounding"
  | "general_analysis";

export interface AnalysisCreateResult {
  job_id: string;
  imagery_id: string;
  /** Image 2 of an image-pair query; null for single-image queries. */
  comparison_imagery_id?: string | null;
  analysis_type: AnalysisType;
  query: string;
  conversation_id: string | null;
  status: string;
}

/** Records an analysis request (analysis_jobs, status "queued"). Performs NO AI inference. */
export function submitAnalysis(
  imageryId: string,
  analysisType: AnalysisType,
  query: string,
  conversationId?: string | null,
  /** Image pairs: imageryId is Image 1, this is Image 2. */
  comparisonImageryId?: string | null
) {
  return request<AnalysisCreateResult>("/analysis", {
    method: "POST",
    body: JSON.stringify({
      imagery_id: imageryId,
      analysis_type: analysisType,
      query,
      conversation_id: conversationId || null,
      ...(comparisonImageryId ? { comparison_imagery_id: comparisonImageryId } : {}),
    }),
  });
}

// Codes analysis_service.py's change-detection compatibility gate can raise
// (see backend/app/validation/errors.py) -- section 15/16 of the codes list.
export const CHANGE_DETECTION_ERROR_CODES = new Set([
  "MODALITY_MISMATCH", "IMAGE_TYPE_MISMATCH", "UNKNOWN_MODALITY", "BAND_MISMATCH",
  "IMAGE_DIMENSION_MISMATCH", "ASPECT_RATIO_MISMATCH", "CRS_MISMATCH", "GEOREFERENCE_MISSING",
  "CRS_MISSING", "FILE_FORMAT_MISMATCH", "NOT_DISTINCT_OBSERVATIONS", "FILE_CORRUPTED",
  "IMAGE_COUNT_MISMATCH", "UNKNOWN_SENSOR", "UNSUPPORTED_SENSOR", "DTYPE_MISMATCH",
  "FILE_TYPE_MISMATCH", "UNSUPPORTED_DTYPE", "INVALID_DIMENSIONS", "UNSUPPORTED_FILE_TYPE", "FILE_TOO_LARGE",
]);

export interface ChangeDetectionImageDetail {
  filename?: string | null;
  format?: string | null;
  modality?: string | null;
  bands?: string[];
  width?: number | null;
  height?: number | null;
  aspect_ratio?: number | null;
  crs?: string | null;
}

export interface ChangeDetectionValidationIssue {
  code: string;
  message: string;
  input?: string | null;
  t1?: string | null;
  t2?: string | null;
}

export interface ChangeDetectionValidationResponse {
  status: "VALID" | "REJECT";
  valid: boolean;
  t1: ChangeDetectionImageDetail | null;
  t2: ChangeDetectionImageDetail | null;
  errors: ChangeDetectionValidationIssue[];
  warnings: ChangeDetectionValidationIssue[];
}

export async function validateChangeDetection(
  t1ImageryId: string,
  t2ImageryId: string,
  requirements?: {
    aspect_ratio_tolerance?: number;
    require_exact_dimensions?: boolean;
    require_matching_format?: boolean;
    require_geospatial?: boolean;
  }
): Promise<ChangeDetectionValidationResponse> {
  return request<ChangeDetectionValidationResponse>("/validation/change-detection", {
    method: "POST",
    body: JSON.stringify({
      t1_imagery_id: t1ImageryId,
      t2_imagery_id: t2ImageryId,
      ...(requirements || {}),
    }),
  });
}

/**
 * When `err` came from the change-detection compatibility gate (a rejected
 * T1/T2 pair -- never a fabricated result, see analysis_service.py), a
 * multi-line "Invalid Input" explanation naming what's wrong with each
 * image; otherwise null, so the caller falls back to its own generic
 * "Failed to submit analysis request: {message}" text. Callers render this
 * through the SAME chat-bubble/isError UI already used for every other
 * submission error -- no new component.
 */
export function formatChangeDetectionError(err: ApiRequestError): string | null {
  if (!CHANGE_DETECTION_ERROR_CODES.has(err.code)) return null;
  const details = err.details as { t1?: ChangeDetectionImageDetail; t2?: ChangeDetectionImageDetail } | null;

  const lines = ["Invalid Input", "", "These images cannot be used together for change detection."];
  const describe = (label: string, image?: ChangeDetectionImageDetail) => {
    if (!image) return;
    const parts = [image.format, image.modality].filter(Boolean).map((p) => String(p).toUpperCase());
    lines.push("", label, parts.length ? parts.join(" • ") : "Could not be read");
  };
  describe("Image 1", details?.t1 ?? undefined);
  describe("Image 2", details?.t2 ?? undefined);
  lines.push("", err.message);
  return lines.join("\n");
}

/** @deprecated use submitAnalysis */
export const createAnalysis = submitAnalysis;

export interface HistoryItem {
  job_id: string;
  imagery_id: string;
  /** Image 2 of an image-pair query; null for single-image queries. */
  comparison_imagery_id?: string | null;
  /** null for requests made before conversations existed (legacy history). */
  conversation_id: string | null;
  imagery_name: string | null;
  query: string;
  analysis_type: AnalysisType;
  status: "queued" | "processing" | "completed" | "failed" | "cancelled";
  created_at: string;
}

/** analysis_jobs joined with imagery, most recent first. Retrieval only -- the sidebar's sole data source. */
export function getAnalysisHistory(limit = 50) {
  return request<HistoryItem[]>(`/analysis/history?limit=${limit}`);
}

// ---- Conversations -----------------------------------------------------------

export type TitleSource = "default" | "auto" | "user";

export interface Conversation {
  id: string;
  /** "New Chat" until the first meaningful query; never an uploaded filename. */
  title: string;
  /** "default" = still "New Chat", "auto" = set once from the first query, "user" = renamed. */
  title_source: TitleSource;
  created_at: string;
  updated_at: string;
}

export interface ConversationJob {
  id: string;
  imagery_id: string | null;
  conversation_id: string | null;
  analysis_type: AnalysisType;
  query: string | null;
  status: HistoryItem["status"];
  created_at: string;
}

export interface ConversationDetail extends Conversation {
  imagery: ImageryRecord[];
  jobs: ConversationJob[];
}

export function createConversation(meta?: { project_id?: string | null } | string | null) {
  const projectId = typeof meta === "string" ? meta : meta?.project_id;
  return request<Conversation>("/conversations", {
    method: "POST",
    ...(projectId ? { body: JSON.stringify({ project_id: projectId }) } : {}),
  });
}

/** Most recently active first -- the sidebar's data source. */
export function listConversations(limit = 100) {
  return request<Conversation[]>(`/conversations?limit=${limit}`);
}

/** The conversation plus its uploads (fresh URLs) and queries, oldest first. */
export function getConversation(conversationId: string) {
  return request<ConversationDetail>(`/conversations/${conversationId}`);
}

/** Manual rename -- the backend marks it user-defined so it is never auto-overwritten. */
export function renameConversation(conversationId: string, title: string) {
  return request<Conversation>(`/conversations/${conversationId}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

/**
 * generateConversationTitle: asks the backend to title the conversation from
 * its first meaningful stored query. Runs at most once per conversation
 * (no-op once titled or renamed), so it is safe to call after any query.
 */
export function generateConversationTitle(conversationId: string) {
  return request<Conversation>(`/conversations/${conversationId}/title`, { method: "POST" });
}

/** Deletes the conversation with its queries and uploaded files. */
export async function deleteConversation(conversationId: string) {
  try {
    return await request<{ id: string; status: string }>(`/conversations/${conversationId}`, {
      method: "DELETE",
    });
  } catch (err: any) {
    if (err?.status === 404 || err?.code === "CONVERSATION_NOT_FOUND" || err?.message?.includes("not found")) {
      return { id: conversationId, status: "already_deleted" };
    }
    throw err;
  }
}

/** Deletes a legacy (pre-conversation) chat: its queries, results and unused images. */
export async function deleteLegacyChat(imageryId: string) {
  try {
    return await request<{ id: string }>(`/conversations/legacy/${imageryId}`, { method: "DELETE" });
  } catch (err: any) {
    // Only the endpoint's own "not found" -- a bare 404 can also mean a backend
    // that predates this route, and that must surface as an error.
    if (err?.code === "CHAT_NOT_FOUND") {
      return { id: imageryId, status: "already_deleted" };
    }
    throw err;
  }
}

export function getAnalysisJob(jobId: string) {
  return request<{
    id: string;
    imagery_id: string;
    analysis_type: AnalysisType;
    query: string | null;
    status: "queued" | "processing" | "completed" | "failed" | "cancelled";
    model_name: string | null;
    result_id: string | null;
    error_message: string | null;
    created_at: string;
  }>(`/jobs/${jobId}`);
}

/** @deprecated use getAnalysisJob */
export const getJob = getAnalysisJob;

export function getResult(resultId: string) {
  return request<{
    id: string;
    job_id: string;
    answer: string | null;
    confidence: number | null;
    model_name: string | null;
    analysis_type: AnalysisType;
    raw_output: Record<string, unknown> | null;
  }>(`/results/${resultId}`);
}

export function getEvidence(resultId: string) {
  return request<
    Array<{
      id: string;
      result_id: string;
      evidence_type: string;
      description: string | null;
      source_reference: string | null;
      bbox: Record<string, unknown> | null;
      confidence: number | null;
    }>
  >(`/results/${resultId}/evidence`);
}

// ---- Profile / analytics ---------------------------------------------------------
// Single-workspace prototype: the backend resolves the profile itself, so no
// call here ever sends a user id. Every number is aggregated from stored rows.

export interface ProfileUser {
  id: string;
  username: string;
  display_name: string;
  headline: string | null;
  bio: string | null;
  plan: string;
  /** Fresh signed URL, or null -> show the initials fallback. */
  avatar_url: string | null;
  timezone: string;
}

export interface ProfileStats {
  total_queries: number;
  scenes_analyzed: number;
  current_streak: number;
  longest_streak: number;
}

export interface ActivityDay {
  date: string;
  query_count: number;
}

export interface ProfileInsights {
  most_used_data_type: string | null;
  most_common_task: string | null;
  total_queries: number;
  scenes_uploaded: number;
  scenes_analyzed: number;
  successful_analyses: number;
  failed_analyses: number;
  pending_analyses: number;
  active_days: number;
  avg_queries_per_active_day: number | null;
}

export interface ProfileDashboard {
  user: ProfileUser;
  stats: ProfileStats;
  /** Every day of the last year (zeros included), oldest first, starting on a Sunday. */
  activity: ActivityDay[];
  activity_start: string;
  activity_end: string;
  insights: ProfileInsights;
  features: Array<{ feature: string; query_count: number }>;
  remote_sensing_usage: Array<{
    data_type: string;
    label: string;
    scenes: number;
    percentage: number;
    query_count: number;
  }>;
  recent_activity: Array<{
    id: string;
    kind: "upload" | "query";
    activity_type: string;
    label: string;
    status: string;
    created_at: string;
  }>;
}

/** Everything the profile page shows, in one request. */
export function getProfileDashboard() {
  return request<ProfileDashboard>("/profile/dashboard");
}

export function getProfile() {
  return request<{ user: ProfileUser; stats: ProfileStats }>("/profile");
}

/** Only the fields present are changed. */
export function updateProfile(changes: {
  display_name?: string;
  username?: string;
  headline?: string;
  bio?: string;
}) {
  return request<ProfileUser>("/profile", { method: "PATCH", body: JSON.stringify(changes) });
}

export function uploadProfileAvatar(file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<ProfileUser>("/profile/avatar", { method: "POST", body: form });
}

export function removeProfileAvatar() {
  return request<ProfileUser>("/profile/avatar", { method: "DELETE" });
}

// ---- Settings --------------------------------------------------------------------
// Stored per profile in user_settings (migration 0005); the backend resolves
// the profile itself. Profile fields are edited with updateProfile().

export type ThemePreference = "dark" | "light" | "system";
export type SidebarDensity = "comfortable" | "compact";
export type DefaultDataType = "optical_rgb" | "multispectral" | "sar" | "optical_sar";
export type DefaultAnalysisTask =
  | "scene_description"
  | "vqa"
  | "change_analysis"
  | "water_body_analysis"
  | "land_cover_analysis";

export interface UserSettings {
  profile: { display_name: string; username: string; avatar_url: string | null; bio: string | null };
  preferences: {
    theme: ThemePreference;
    language: "en";
    sidebar_density: SidebarDensity;
    default_data_type: DefaultDataType;
    default_analysis_task: DefaultAnalysisTask;
  };
  notifications: { analysis_completion: boolean; product_updates: boolean; usage_alerts: boolean };
  privacy: { save_analysis_results: boolean; share_usage_analytics: boolean };
  updated_at: string | null;
}

/** PATCH body: flat column names, only what changed. */
export interface SettingsChanges {
  theme?: ThemePreference;
  language?: "en";
  sidebar_density?: SidebarDensity;
  default_data_type?: DefaultDataType;
  default_analysis_task?: DefaultAnalysisTask;
  notify_analysis_completion?: boolean;
  notify_product_updates?: boolean;
  notify_usage_alerts?: boolean;
  save_analysis_results?: boolean;
  share_usage_analytics?: boolean;
}

export function getSettings() {
  return request<UserSettings>("/settings");
}

export function updateSettings(changes: SettingsChanges) {
  return request<UserSettings>("/settings", { method: "PATCH", body: JSON.stringify(changes) });
}

const SETTINGS_SECTION: Record<keyof SettingsChanges, [keyof UserSettings, string]> = {
  theme: ["preferences", "theme"],
  language: ["preferences", "language"],
  sidebar_density: ["preferences", "sidebar_density"],
  default_data_type: ["preferences", "default_data_type"],
  default_analysis_task: ["preferences", "default_analysis_task"],
  notify_analysis_completion: ["notifications", "analysis_completion"],
  notify_product_updates: ["notifications", "product_updates"],
  notify_usage_alerts: ["notifications", "usage_alerts"],
  save_analysis_results: ["privacy", "save_analysis_results"],
  share_usage_analytics: ["privacy", "share_usage_analytics"],
};

/** The settings as they will look once `changes` are saved (for optimistic UI). */
export function applySettingsChanges(settings: UserSettings, changes: SettingsChanges): UserSettings {
  const next = {
    ...settings,
    preferences: { ...settings.preferences },
    notifications: { ...settings.notifications },
    privacy: { ...settings.privacy },
  };
  (Object.keys(changes) as Array<keyof SettingsChanges>).forEach((key) => {
    const [section, field] = SETTINGS_SECTION[key];
    (next[section] as Record<string, unknown>)[field] = changes[key];
  });
  return next;
}

// ---- Projects -----------------------------------------------------------------

export interface Project {
  id: string;
  name: string;
  description: string | null;
  icon: string | null;
  color: string | null;
  custom_instructions: string | null;
  has_custom_instructions: boolean;
  chat_count: number;
  file_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProjectFile {
  id: string;
  project_id: string;
  name: string;
  mime_type: string | null;
  file_size: number | null;
  created_at: string | null;
  url?: string | null;
}

export interface ProjectChatUpload {
  imagery_id: string;
  conversation_id: string;
  conversation_title?: string | null;
  name: string;
  file_size?: number | null;
  created_at?: string | null;
}

export interface ProjectDetail extends Project {
  conversations: Conversation[];
  files: ProjectFile[];
  chat_uploads: ProjectChatUpload[];
}

export function listProjects() {
  return request<Project[]>("/projects");
}

export function getProject(projectId: string) {
  return request<ProjectDetail>(`/projects/${projectId}`);
}

export function createProject(payload: {
  name: string;
  description?: string | null;
  icon?: string | null;
  color?: string | null;
  custom_instructions?: string | null;
}) {
  return request<Project>("/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateProject(
  projectId: string,
  payload: {
    name?: string | null;
    description?: string | null;
    icon?: string | null;
    color?: string | null;
    custom_instructions?: string | null;
  }
) {
  return request<Project>(`/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteProject(projectId: string) {
  return request<{ id: string; status: string }>(`/projects/${projectId}`, {
    method: "DELETE",
  });
}

export function uploadProjectFile(projectId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<ProjectFile>(`/projects/${projectId}/files`, {
    method: "POST",
    body: form,
  });
}

export function deleteProjectFile(projectId: string, fileId: string) {
  return request<{ id: string; status: string }>(`/projects/${projectId}/files/${fileId}`, {
    method: "DELETE",
  });
}

