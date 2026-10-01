import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Pencil, Trash2, X, Loader2 } from 'lucide-react';
import { updateProject, deleteProject } from '../lib/apiClient';

// Rename / Delete dialogs for a project, opened from the sidebar's or the
// Projects page's ⋯ menu. They call the backend (PATCH / DELETE
// /projects/{id}) and only report success after it answers; the caller then
// refreshes the one shared project list (App.jsx).

function Dialog({ labelledBy, onDismiss, busy, children }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape' && !busy) onDismiss();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onDismiss, busy]);

  return createPortal(
    <div
      className="fixed inset-0 z-[99999] flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in-0 duration-200"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onDismiss();
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby={labelledBy}
    >
      <div className="relative w-full max-w-[540px] rounded-[18px] border border-[rgba(59,130,246,0.22)] bg-[#0d131f] p-6 sm:p-8 text-white shadow-[0_25px_60px_-15px_rgba(0,0,0,0.85),0_0_30px_rgba(59,130,246,0.08)] animate-in zoom-in-95 duration-200">
        <button
          type="button"
          onClick={() => !busy && onDismiss()}
          disabled={busy}
          className="absolute top-5 right-5 p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-50 cursor-pointer"
          aria-label="Close dialog"
        >
          <X className="w-4 h-4" />
        </button>
        {children}
      </div>
    </div>,
    document.body
  );
}

function DialogHeader({ id, icon, tone, title, subtitle }) {
  const toneClass =
    tone === 'danger'
      ? 'bg-red-500/10 border-red-500/25 text-red-400'
      : 'bg-blue-500/10 border-blue-500/25 text-blue-400';
  return (
    <div className="flex items-start gap-4 mb-6 pr-8">
      <div className={`flex items-center justify-center w-11 h-11 rounded-xl border shrink-0 ${toneClass}`}>{icon}</div>
      <div className="flex-1 min-w-0">
        {/* Inline colour: index.css's unlayered h1-h6 rule would beat Tailwind's text-white in the light theme. */}
        <h3 id={id} className="text-lg font-semibold tracking-tight leading-tight" style={{ color: '#ffffff' }}>{title}</h3>
        {subtitle && <p className="text-[13px] text-slate-400 mt-1.5">{subtitle}</p>}
      </div>
    </div>
  );
}

const CANCEL_CLASS =
  'shrink-0 px-5 py-2.5 text-sm font-medium rounded-xl text-slate-300 hover:text-white hover:bg-slate-800/80 transition-colors disabled:opacity-50 cursor-pointer';

function RenameDialog({ project, onClose, onRenamed, onError }) {
  const [name, setName] = useState(project.name || '');
  const [saving, setSaving] = useState(false);
  const inputRef = useRef(null);
  const cleaned = name.replace(/\s+/g, ' ').trim();
  const canSave = Boolean(cleaned) && cleaned !== project.name && !saving;

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const save = async (e) => {
    e?.preventDefault();
    if (!canSave) return;
    setSaving(true);
    try {
      const updated = await updateProject(project.id, { name: cleaned });
      await onRenamed(updated);
    } catch (err) {
      console.error('[SatQuery] Rename project failed:', err);
      onError('Unable to update the project. Please try again.');
      setSaving(false);
    }
  };

  return (
    <Dialog labelledBy="rename-project-title" onDismiss={onClose} busy={saving}>
      <form onSubmit={save}>
        <DialogHeader
          id="rename-project-title"
          icon={<Pencil className="w-5 h-5" />}
          title="Rename Project"
          subtitle="Choose a new name for this project."
        />
        <label htmlFor="rename-project-input" className="block text-xs font-medium text-slate-400 mb-2">
          Project name
        </label>
        <input
          id="rename-project-input"
          ref={inputRef}
          value={name}
          maxLength={120}
          onChange={(e) => setName(e.target.value)}
          disabled={saving}
          className="w-full h-11 rounded-xl border border-slate-700/80 bg-slate-900/70 px-4 text-[15px] text-white outline-none transition-colors focus:border-blue-500 focus:ring-2 focus:ring-blue-500/25 disabled:opacity-60"
        />
        {!cleaned && <p className="mt-2 text-xs text-red-300">Project name cannot be empty.</p>}

        <div className="flex flex-wrap items-center justify-end gap-3 mt-8">
          <button type="button" onClick={onClose} disabled={saving} className={CANCEL_CLASS}>
            Cancel
          </button>
          <button
            type="submit"
            disabled={!canSave}
            className="shrink-0 inline-flex items-center justify-center gap-2 px-5 py-2.5 text-sm font-semibold rounded-xl bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-900/30 transition-all duration-150 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-blue-600 cursor-pointer"
          >
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            <span>{saving ? 'Saving…' : 'Save Changes'}</span>
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function DeleteDialog({ project, onClose, onDeleted, onError }) {
  const [deleting, setDeleting] = useState(false);

  const confirm = async () => {
    if (deleting) return;
    setDeleting(true);
    try {
      await deleteProject(project.id);
      await onDeleted(project);
    } catch (err) {
      console.error('[SatQuery] Delete project failed:', err);
      onError('Unable to delete the project. Please try again.');
      setDeleting(false);
    }
  };

  return (
    <Dialog labelledBy="delete-project-title" onDismiss={onClose} busy={deleting}>
      <DialogHeader
        id="delete-project-title"
        tone="danger"
        icon={<Trash2 className="w-5 h-5" />}
        title="Delete Project"
        subtitle="This action cannot be undone."
      />
      <div className="rounded-xl border border-slate-800/80 bg-slate-900/60 px-5 py-4 text-sm leading-relaxed text-slate-300">
        <p>
          Are you sure you want to delete{' '}
          <span className="font-semibold text-white break-words">"{project.name}"</span>?
        </p>
        <p className="mt-3 text-slate-400">
          The project, its custom instructions and its knowledge files will be permanently removed. Its chats are
          kept and moved out of the project.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-3 mt-8">
        <button type="button" onClick={onClose} disabled={deleting} className={CANCEL_CLASS}>
          Cancel
        </button>
        <button
          type="button"
          onClick={confirm}
          disabled={deleting}
          className="shrink-0 inline-flex items-center justify-center gap-2 px-5 py-2.5 text-sm font-semibold rounded-xl bg-red-600 hover:bg-red-500 text-white shadow-lg shadow-red-900/30 transition-all duration-150 active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer"
        >
          {deleting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
          <span>{deleting ? 'Deleting…' : 'Delete Project'}</span>
        </button>
      </div>
    </Dialog>
  );
}

/** action: { type: 'rename' | 'delete', project } | null */
export function ProjectActionDialogs({ action, onClose, onRenamed, onDeleted, onError }) {
  if (!action?.project) return null;
  if (action.type === 'rename') {
    return <RenameDialog key={action.project.id} project={action.project} onClose={onClose} onRenamed={onRenamed} onError={onError} />;
  }
  if (action.type === 'delete') {
    return <DeleteDialog key={action.project.id} project={action.project} onClose={onClose} onDeleted={onDeleted} onError={onError} />;
  }
  return null;
}
