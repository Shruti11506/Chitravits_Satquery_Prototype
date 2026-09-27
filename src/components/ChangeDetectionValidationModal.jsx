import React, { useEffect, useRef } from 'react';
import { AlertTriangle, X, RefreshCw, Check } from 'lucide-react';

export function ChangeDetectionValidationModal({
  isOpen,
  onClose,
  onReplace,
  modalState
}) {
  const primaryBtnRef = useRef(null);

  useEffect(() => {
    if (isOpen) {
      const timer = setTimeout(() => primaryBtnRef.current?.focus(), 50);
      const handleKeyDown = (e) => {
        if (e.key === 'Escape') onClose();
      };
      window.addEventListener('keydown', handleKeyDown);
      return () => {
        clearTimeout(timer);
        window.removeEventListener('keydown', handleKeyDown);
      };
    }
  }, [isOpen, onClose]);

  if (!isOpen || !modalState) return null;

  const {
    title = 'Invalid Input',
    message = 'These images cannot be used for change detection.',
    details,
    resolution = 'Change detection requires two compatible image types.'
  } = modalState;

  return (
    <div
      className="cd-modal-overlay"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 99999,
        background: 'rgba(0, 0, 0, 0.75)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
        animation: 'fadeIn 0.18s ease-out'
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="cd-modal-title"
    >
      <div
        className="cd-modal-container"
        style={{
          width: '100%',
          maxWidth: '480px',
          background: 'var(--bg-card, #111827)',
          border: '1px solid rgba(245, 158, 11, 0.35)',
          borderRadius: '16px',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.7), 0 0 30px rgba(245, 158, 11, 0.12)',
          padding: '24px',
          color: 'var(--text-primary, #f9fafb)',
          position: 'relative',
          display: 'flex',
          flexDirection: 'column',
          gap: '16px',
          animation: 'slideUp 0.22s cubic-bezier(0.16, 1, 0.3, 1)'
        }}
      >
        {/* Close Icon Top Right */}
        <button
          type="button"
          onClick={onClose}
          style={{
            position: 'absolute',
            top: '16px',
            right: '16px',
            background: 'transparent',
            border: 'none',
            color: 'var(--text-muted, #9ca3af)',
            cursor: 'pointer',
            padding: '6px',
            borderRadius: '8px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}
          title="Close dialog"
          aria-label="Close"
        >
          <X size={18} />
        </button>

        {/* Header with Alert Icon and Title */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div
            style={{
              width: '42px',
              height: '42px',
              borderRadius: '12px',
              background: 'rgba(245, 158, 11, 0.15)',
              border: '1px solid rgba(245, 158, 11, 0.4)',
              color: '#f59e0b',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0
            }}
          >
            <AlertTriangle size={22} />
          </div>
          <div>
            <h2
              id="cd-modal-title"
              style={{
                fontSize: '1.25rem',
                fontWeight: 700,
                color: 'var(--text-primary, #ffffff)',
                margin: 0,
                letterSpacing: '-0.02em'
              }}
            >
              {title}
            </h2>
            <div
              style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                color: '#ef4444',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                marginTop: '2px'
              }}
            >
              Change Detection Blocked
            </div>
          </div>
        </div>

        {/* Explanatory Message */}
        <p
          style={{
            fontSize: '0.92rem',
            color: 'var(--text-secondary, #d1d5db)',
            lineHeight: 1.5,
            margin: 0
          }}
        >
          {message}
        </p>

        {/* Image Details Comparison Card */}
        {details && (details.t1 || details.t2) && (
          <div
            style={{
              background: 'rgba(0, 0, 0, 0.4)',
              border: '1px solid var(--border-subtle, rgba(255, 255, 255, 0.08))',
              borderRadius: '10px',
              padding: '14px 16px',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px'
            }}
          >
            {details.t1 && (
              <div>
                <div
                  style={{
                    fontSize: '0.72rem',
                    textTransform: 'uppercase',
                    color: 'var(--text-muted, #9ca3af)',
                    fontWeight: 600,
                    letterSpacing: '0.04em',
                    marginBottom: '3px'
                  }}
                >
                  Image 1 (Reference)
                </div>
                <div
                  style={{
                    fontSize: '0.92rem',
                    fontWeight: 600,
                    color: '#60a5fa'
                  }}
                >
                  {details.t1}
                </div>
              </div>
            )}

            {details.t1 && details.t2 && (
              <div
                style={{
                  height: '1px',
                  background: 'var(--border-subtle, rgba(255, 255, 255, 0.08))'
                }}
              />
            )}

            {details.t2 && (
              <div>
                <div
                  style={{
                    fontSize: '0.72rem',
                    textTransform: 'uppercase',
                    color: 'var(--text-muted, #9ca3af)',
                    fontWeight: 600,
                    letterSpacing: '0.04em',
                    marginBottom: '3px'
                  }}
                >
                  Image 2 (Comparison)
                </div>
                <div
                  style={{
                    fontSize: '0.92rem',
                    fontWeight: 600,
                    color: '#f59e0b'
                  }}
                >
                  {details.t2}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Resolution / Requirement Callout */}
        {resolution && (
          <div
            style={{
              fontSize: '0.84rem',
              color: 'var(--text-muted, #9ca3af)',
              lineHeight: 1.45,
              padding: '10px 14px',
              borderRadius: '8px',
              background: 'rgba(255, 255, 255, 0.03)',
              borderLeft: '3px solid #f59e0b'
            }}
          >
            {resolution}
          </div>
        )}

        {/* Action Buttons */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: '10px',
            marginTop: '8px'
          }}
        >
          {onReplace && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                onClose();
                onReplace();
              }}
              style={{
                padding: '8px 16px',
                fontSize: '0.86rem',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <RefreshCw size={14} />
              <span>Replace Images</span>
            </button>
          )}

          <button
            ref={primaryBtnRef}
            type="button"
            className="btn btn-primary"
            onClick={onClose}
            style={{
              padding: '8px 22px',
              fontSize: '0.88rem',
              fontWeight: 600,
              minWidth: '90px'
            }}
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
}
