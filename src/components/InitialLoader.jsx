import React from 'react';
import { ChitravitsEmblem } from './ui/ChitravitsLogo';
import { AlertCircle, RefreshCw } from 'lucide-react';

export function InitialLoader({
  stepText = "Initializing SatQuery...",
  error = null,
  onRetry = null,
  isExiting = false
}) {
  return (
    <div
      role="status"
      aria-busy={!error}
      aria-live="polite"
      className={`fixed inset-0 z-[99999] flex flex-col items-center justify-center bg-[#080d18] text-white select-none transition-opacity duration-300 ease-out ${
        isExiting ? "opacity-0 pointer-events-none" : "opacity-100"
      }`}
      style={{
        backgroundImage: "radial-gradient(circle at 50% 40%, rgba(24, 82, 148, 0.18) 0%, rgba(8, 13, 24, 0.95) 70%)"
      }}
    >
      <div className="flex flex-col items-center max-w-sm px-6 text-center animate-in fade-in zoom-in-95 duration-300">
        {!error ? (
          <>
            {/* Satellite Orbital Radar Animation Container */}
            <div className="relative flex items-center justify-center w-36 h-36 mb-8">
              {/* Outer Outer Soft Glow Ring */}
              <div className="absolute inset-0 rounded-full bg-blue-500/10 blur-2xl animate-pulse" />

              {/* Orbital Radar Ring 1 (Clockwise Spin) */}
              <div 
                className="absolute inset-0 rounded-full border border-blue-500/20 border-t-blue-400 border-r-cyan-400 animate-spin"
                style={{ animationDuration: "3s" }}
              />

              {/* Orbital Radar Ring 2 (Counter-Clockwise Spin) */}
              <div 
                className="absolute inset-2.5 rounded-full border border-blue-400/15 border-b-cyan-300 animate-spin"
                style={{ animationDuration: "5s", animationDirection: "reverse" }}
              />

              {/* Orbiting Satellite Dot */}
              <div 
                className="absolute inset-0 rounded-full animate-spin"
                style={{ animationDuration: "3s" }}
              >
                <div className="w-2.5 h-2.5 rounded-full bg-cyan-400 shadow-[0_0_10px_#00e5ff] -top-1 left-1/2 -translate-x-1/2 absolute" />
              </div>

              {/* Inner Disc with SatQuery Emblem */}
              <div className="relative z-10 w-20 h-20 rounded-full bg-white flex items-center justify-center shadow-[0_0_30px_rgba(59,130,246,0.35)] p-1 border border-blue-400/40">
                <ChitravitsEmblem size={60} />
              </div>
            </div>

            {/* Brand Title */}
            <div className="flex items-center gap-1.5 mb-2">
              <span className="text-xl font-bold tracking-tight text-white">
                Sat<span className="text-blue-400">Query</span>
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 font-semibold border border-blue-500/30">
                AI
              </span>
            </div>

            {/* Status Message */}
            <p className="text-sm text-blue-200/80 font-medium h-6 flex items-center justify-center">
              {stepText}
            </p>

            {/* Indeterminate Shimmer Line */}
            <div className="w-48 h-1 bg-blue-950 rounded-full mt-5 overflow-hidden relative border border-blue-500/20">
              <div className="absolute inset-y-0 w-1/2 bg-gradient-to-r from-transparent via-blue-400 to-transparent animate-shimmer" style={{ animation: "shimmerSlide 1.8s infinite linear" }} />
            </div>
          </>
        ) : (
          <>
            {/* Error Icon Container */}
            <div className="w-16 h-16 rounded-full bg-red-500/10 border border-red-500/30 flex items-center justify-center text-red-400 mb-6 shadow-[0_0_20px_rgba(239,68,68,0.2)]">
              <AlertCircle className="w-8 h-8" />
            </div>

            {/* Brand Title */}
            <div className="flex items-center gap-1.5 mb-3">
              <span className="text-lg font-bold tracking-tight text-white">
                Sat<span className="text-blue-400">Query</span>
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 font-semibold border border-blue-500/30">
                AI
              </span>
            </div>

            <h3 className="text-base font-semibold text-red-200 mb-2">
              Unable to Connect to SatQuery
            </h3>
            <p className="text-xs text-slate-400 leading-relaxed mb-6 max-w-xs">
              {error || "Could not synchronize workspace with the backend services."}
            </p>

            {onRetry && (
              <button
                onClick={onRetry}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-lg shadow-blue-600/30 transition-all cursor-pointer hover:scale-105 active:scale-95"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Retry Connection</span>
              </button>
            )}
          </>
        )}
      </div>

      <style>{`
        @keyframes shimmerSlide {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(200%); }
        }
      `}</style>
    </div>
  );
}
