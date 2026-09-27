import React, { useEffect, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {
  AlertCircle,
  BellRing,
  Camera,
  Check,
  ChevronDown,
  Gauge,
  LogOut,
  Mail,
  Megaphone,
  MonitorCog,
  RefreshCw,
  Settings as SettingsIcon,
  ShieldCheck,
  Trash2,
  UserRound
} from 'lucide-react';
import { updateProfile, uploadProfileAvatar, removeProfileAvatar } from '../lib/apiClient';
import './ProfileDashboard.css';
import './SettingsPage.css';

// Settings screen. Everything shown comes from GET /settings (held by App);
// every change is saved through PATCH /settings (preferences, notifications,
// privacy) or the existing /profile endpoints (profile). Nothing here is a
// local-only setting.

const LANGUAGE_OPTIONS = [['en', 'English']];
const DENSITY_OPTIONS = [
  ['comfortable', 'Comfortable'],
  ['compact', 'Compact']
];
const DATA_TYPE_OPTIONS = [
  ['optical_rgb', 'Optical / RGB'],
  ['multispectral', 'Multispectral'],
  ['sar', 'SAR'],
  ['optical_sar', 'Optical + SAR']
];
const TASK_OPTIONS = [
  ['scene_description', 'Scene Description'],
  ['vqa', 'VQA'],
  ['change_analysis', 'Change Analysis'],
  ['water_body_analysis', 'Water Body Analysis'],
  ['land_cover_analysis', 'Land Cover Analysis']
];

const AVATAR_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
const AVATAR_MAX_BYTES = 5 * 1024 * 1024;

function initialsOf(name) {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '?';
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}

// 'idle' | 'saving' | 'saved' | 'error' -- "Saved" fades back to idle.
function useSaveStatus() {
  const [status, setStatus] = useState('idle');
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const track = async (promise) => {
    clearTimeout(timer.current);
    setStatus('saving');
    try {
      const result = await promise;
      setStatus('saved');
      timer.current = setTimeout(() => setStatus('idle'), 2200);
      return result;
    } catch (err) {
      console.error('[SatQuery] Failed to save settings:', err);
      setStatus('error');
      throw err;
    }
  };
  return [status, track];
}

function SaveStatus({ status }) {
  if (status === 'idle') return null;
  return (
    <span className="st-status" data-status={status} role="status" aria-live="polite">
      {status === 'saving' && 'Saving…'}
      {status === 'saved' && <><Check size={13} /> Saved</>}
      {status === 'error' && <><AlertCircle size={13} /> Failed to save changes.</>}
    </span>
  );
}

function CardHead({ icon: Icon, title, subtitle, status }) {
  return (
    <div className="st-card-head">
      <div className="st-card-icon" aria-hidden="true"><Icon size={19} /></div>
      <div className="st-card-titles">
        <h2 className="st-card-title">{title}</h2>
        <p className="st-card-sub">{subtitle}</p>
      </div>
      <SaveStatus status={status} />
    </div>
  );
}

function SelectRow({ id, label, value, options, onChange, disabled }) {
  return (
    <div className="st-row">
      <label className="st-row-label" htmlFor={id}>{label}</label>
      <div className="st-select-wrap">
        <select id={id} className="st-select" value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
          {options.map(([optionValue, optionLabel]) => (
            <option key={optionValue} value={optionValue}>{optionLabel}</option>
          ))}
        </select>
        <ChevronDown size={15} className="st-select-chevron" aria-hidden="true" />
      </div>
    </div>
  );
}

function ToggleRow({ id, icon: Icon, label, description, checked, onChange }) {
  return (
    <div className="st-toggle-row">
      {Icon && <div className="st-toggle-icon" aria-hidden="true"><Icon size={17} /></div>}
      <div className="st-toggle-text">
        <span className="st-toggle-label" id={`${id}-label`}>{label}</span>
        <span className="st-toggle-desc" id={`${id}-desc`}>{description}</span>
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={`${id}-label`}
        aria-describedby={`${id}-desc`}
        className="st-switch"
        onClick={() => onChange(!checked)}
      >
        <span className="st-switch-thumb" />
      </button>
    </div>
  );
}

// ---- Profile ---------------------------------------------------------------------

function ProfileCard({ profile, onProfileSaved }) {
  const [form, setForm] = useState({ display_name: '', username: '', bio: '' });
  const [photoFile, setPhotoFile] = useState(null);
  const [photoPreview, setPhotoPreview] = useState(null);
  const [removePhoto, setRemovePhoto] = useState(false);
  const [error, setError] = useState(null);
  const [status, track] = useSaveStatus();
  const fileInputRef = useRef(null);

  useEffect(() => {
    setForm({ display_name: profile.display_name || '', username: profile.username || '', bio: profile.bio || '' });
  }, [profile.display_name, profile.username, profile.bio]);

  useEffect(() => () => { if (photoPreview) URL.revokeObjectURL(photoPreview); }, [photoPreview]);

  const changes = {};
  Object.entries(form).forEach(([key, value]) => {
    if ((value || '') !== (profile[key] || '')) changes[key] = value;
  });
  const dirty = Object.keys(changes).length > 0 || Boolean(photoFile) || (removePhoto && Boolean(profile.avatar_url));

  const pickPhoto = (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (!AVATAR_TYPES.includes(file.type)) return setError('Profile photos must be JPG, PNG or WEBP.');
    if (file.size > AVATAR_MAX_BYTES) return setError('Profile photos must be 5 MB or smaller.');
    setError(null);
    setPhotoFile(file);
    setPhotoPreview(URL.createObjectURL(file));
    setRemovePhoto(false);
  };

  const save = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      await track((async () => {
        let latest = null;
        if (photoFile) latest = await uploadProfileAvatar(photoFile);
        else if (removePhoto && profile.avatar_url) latest = await removeProfileAvatar();
        if (Object.keys(changes).length) latest = await updateProfile(changes);
        if (latest) onProfileSaved(latest);
      })());
      setPhotoFile(null);
      setPhotoPreview(null);
      setRemovePhoto(false);
    } catch (err) {
      setError(err?.message || null);
    }
  };

  const avatarSrc = removePhoto ? null : (photoPreview || profile.avatar_url);

  return (
    <section className="pf-card st-card" aria-labelledby="st-profile-title">
      <CardHead icon={UserRound} title={<span id="st-profile-title">Profile</span>} subtitle="Manage your account information" status={status} />
      <form className="st-profile" onSubmit={save}>
        <div className="st-avatar-col">
          <div className="st-avatar-wrap">
            <div className="pf-avatar st-avatar" aria-hidden="true">
              {avatarSrc ? <img src={avatarSrc} alt="" /> : initialsOf(form.display_name || profile.display_name)}
            </div>
            <button type="button" className="st-avatar-btn" onClick={() => fileInputRef.current?.click()} title="Change profile photo" aria-label="Change profile photo">
              <Camera size={15} />
            </button>
          </div>
          {(photoFile || (profile.avatar_url && !removePhoto)) && (
            <button type="button" className="st-link-btn" onClick={() => { setPhotoFile(null); setPhotoPreview(null); setRemovePhoto(true); }}>
              Remove photo
            </button>
          )}
          <input ref={fileInputRef} type="file" accept={AVATAR_TYPES.join(',')} hidden onChange={pickPhoto} />
        </div>

        <div className="st-fields">
          <div className="pf-field">
            <label htmlFor="st-display-name">Display name</label>
            <input id="st-display-name" className="pf-input" value={form.display_name} maxLength={60} required
              onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))} />
          </div>
          <div className="pf-field">
            <label htmlFor="st-username">Username</label>
            <div className="pf-input-wrap">
              <span className="pf-input-prefix">@</span>
              <input id="st-username" className="pf-input" value={form.username} maxLength={30} required
                pattern="[a-z0-9_]{3,30}" title="3-30 characters: lowercase letters, digits or underscores"
                onChange={(e) => setForm((f) => ({ ...f, username: e.target.value.toLowerCase().replace(/^@/, '') }))} />
            </div>
          </div>
          <div className="pf-field">
            <label htmlFor="st-bio">Bio</label>
            <textarea id="st-bio" className="pf-textarea" rows={2} maxLength={160} value={form.bio}
              onChange={(e) => setForm((f) => ({ ...f, bio: e.target.value }))} />
            <div className="pf-field-hint"><span /><span>{form.bio.length}/160</span></div>
          </div>
          {error && <div className="pf-form-error" role="alert">{error}</div>}
          <div className="st-actions">
            <button type="submit" className="pf-btn pf-btn-primary" disabled={!dirty || status === 'saving'}>
              {status === 'saving' ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </div>
      </form>
    </section>
  );
}

// ---- Delete account ----------------------------------------------------------------

function DeleteAccountDialog({ open, onOpenChange }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="pf-dialog-overlay" />
        <Dialog.Content className="pf-dialog">
          <Dialog.Title className="pf-dialog-title">Delete your SatQuery account?</Dialog.Title>
          <Dialog.Description className="pf-dialog-desc">
            Your profile, conversations, scenes and associated data may be permanently deleted.
          </Dialog.Description>
          <div className="st-notice" role="note">
            <AlertCircle size={16} />
            <span>Account deletion is not currently available. This prototype runs as a single workspace without sign-in, so there is no account to delete. Nothing has been removed.</span>
          </div>
          <div className="pf-dialog-actions">
            <Dialog.Close asChild>
              <button type="button" className="pf-btn">Cancel</button>
            </Dialog.Close>
            <button type="button" className="pf-btn st-btn-destructive" disabled>
              <Trash2 size={14} /> Delete Account
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// ---- Screen ------------------------------------------------------------------------

function SettingsSkeleton() {
  return (
    <div className="pf-page st-page" aria-busy="true" aria-label="Loading settings">
      <div className="pf-skel" style={{ height: 96, borderRadius: 16 }} />
      <div className="st-grid">
        {[0, 1, 2, 3].map((i) => <div key={i} className="pf-skel" style={{ height: 300, borderRadius: 14 }} />)}
      </div>
    </div>
  );
}

export function SettingsPage({ settingsState, onRetry, onSave, onProfileSaved }) {
  const [prefStatus, trackPrefs] = useSaveStatus();
  const [notifStatus, trackNotifs] = useSaveStatus();
  const [privacyStatus, trackPrivacy] = useSaveStatus();
  const [deleteOpen, setDeleteOpen] = useState(false);

  if (settingsState.status === 'loading' && !settingsState.data) return <SettingsSkeleton />;

  if (!settingsState.data) {
    const error = settingsState.error;
    return (
      <div className="pf-page st-page">
        <div className="pf-card pf-error" role="alert">
          <AlertCircle size={26} />
          <div className="pf-error-title">Unable to load settings.</div>
          {error?.code === 'SCHEMA_NOT_MIGRATED' && <div className="pf-error-detail">{error.message}</div>}
          <button className="pf-btn" onClick={onRetry}><RefreshCw size={14} /> Retry</button>
        </div>
      </div>
    );
  }

  const { profile, preferences, notifications, privacy } = settingsState.data;
  // The optimistic value shows at once; a failure reverts it (in App) and the
  // card reports "Failed to save changes."
  const save = (track) => (changes) => track(onSave(changes)).catch(() => {});
  const savePrefs = save(trackPrefs);
  const saveNotifs = save(trackNotifs);
  const savePrivacy = save(trackPrivacy);

  return (
    <div className="pf-page st-page">
      <header className="st-head">
        <div className="st-head-image" aria-hidden="true" />
        <div className="st-head-body">
          <div className="st-head-icon" aria-hidden="true"><SettingsIcon size={24} /></div>
          <div>
            <h1 className="st-title">Settings</h1>
            <p className="st-subtitle">Customize your SatQuery experience</p>
          </div>
        </div>
      </header>

      <div className="st-grid">
        <ProfileCard profile={profile} onProfileSaved={onProfileSaved} />

        <section className="pf-card st-card" aria-labelledby="st-prefs-title">
          <CardHead icon={MonitorCog} title={<span id="st-prefs-title">App Preferences</span>} subtitle="Customize the look and feel" status={prefStatus} />
          <div className="st-rows">
            <SelectRow id="st-language" label="Language" value={preferences.language} options={LANGUAGE_OPTIONS} onChange={(v) => savePrefs({ language: v })} />
            <SelectRow id="st-density" label="Sidebar density" value={preferences.sidebar_density} options={DENSITY_OPTIONS} onChange={(v) => savePrefs({ sidebar_density: v })} />
            <SelectRow id="st-data-type" label="Default data type" value={preferences.default_data_type} options={DATA_TYPE_OPTIONS} onChange={(v) => savePrefs({ default_data_type: v })} />
            <SelectRow id="st-task" label="Default analysis task" value={preferences.default_analysis_task} options={TASK_OPTIONS} onChange={(v) => savePrefs({ default_analysis_task: v })} />
          </div>
        </section>

        <section className="pf-card st-card" aria-labelledby="st-notif-title">
          <CardHead icon={BellRing} title={<span id="st-notif-title">Notifications</span>} subtitle="Manage what you get notified about" status={notifStatus} />
          <div className="st-toggles">
            <ToggleRow id="st-notify-completion" icon={Mail} label="Analysis completion" description="Notify when a satellite analysis finishes"
              checked={notifications.analysis_completion} onChange={(v) => saveNotifs({ notify_analysis_completion: v })} />
            <ToggleRow id="st-notify-updates" icon={Megaphone} label="Product updates" description="Important SatQuery updates"
              checked={notifications.product_updates} onChange={(v) => saveNotifs({ notify_product_updates: v })} />
            <ToggleRow id="st-notify-usage" icon={Gauge} label="Plan & usage alerts" description="Notify when approaching usage limits"
              checked={notifications.usage_alerts} onChange={(v) => saveNotifs({ notify_usage_alerts: v })} />
          </div>
          <p className="st-footnote">Your choices are saved now and apply once notifications are available.</p>
        </section>

        <section className="pf-card st-card" aria-labelledby="st-privacy-title">
          <CardHead icon={ShieldCheck} title={<span id="st-privacy-title">Account &amp; Privacy</span>} subtitle="Manage your account and data" status={privacyStatus} />
          <div className="st-toggles">
            <ToggleRow id="st-save-results" label="Save analysis results to library" description="Keep finished analyses in your library"
              checked={privacy.save_analysis_results} onChange={(v) => savePrivacy({ save_analysis_results: v })} />
            <ToggleRow id="st-share-analytics" label="Share anonymous usage analytics" description="Help improve SatQuery with anonymous usage data"
              checked={privacy.share_usage_analytics} onChange={(v) => savePrivacy({ share_usage_analytics: v })} />
          </div>
          <div className="st-account-actions">
            <div className="st-account-row">
              <button type="button" className="pf-btn" disabled aria-describedby="st-signout-note">
                <LogOut size={14} /> Sign Out
              </button>
              <span className="st-account-note" id="st-signout-note">Sign-in isn't enabled in this prototype.</span>
            </div>
            <button type="button" className="pf-btn st-btn-destructive st-delete" onClick={() => setDeleteOpen(true)}>
              <Trash2 size={14} /> Delete Account
            </button>
          </div>
        </section>
      </div>

      <DeleteAccountDialog open={deleteOpen} onOpenChange={setDeleteOpen} />
    </div>
  );
}

export default SettingsPage;
