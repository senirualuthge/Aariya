import React, { useEffect, useState } from 'react';
import { isBuildSummaryFresh } from '../utils/buildFreshness.js';
import { apiBase } from '../utils/apiHost';

/**
 * BuildWarningsBanner.jsx
 * ──────────────────────
 * Surfaces oversized-JS-chunk warnings (from `npm run dev -- --prod`) inside the
 * GUI itself, so users see them without opening the terminal.
 *
 * Data sources (first that answers wins):
 *   1. Electron: window.electronAPI.getBuildSummary() — IPC read of
 *      .build-summary.json from the main process (run_gui flow).
 *   2. Browser fallback: GET /api/build/summary on the backend — the same
 *      endpoint the analytics dashboard's Build tab uses.
 *
 * The banner only shows when the summary is FRESH (built within the last 24h)
 * — a stale summary from an old `--prod` build never surfaces in dev mode.
 * It is dismissible and remembers its dismissal per build (keyed by built_at),
 * so a fresh build re-shows it while an old one stays hidden.
 */

const AMBER = '#fbbf24';
const AMBER_DIM = 'rgba(251, 191, 36, 0.12)';

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return '? B';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  const num = value >= 100 ? Math.round(value) : value.toFixed(1);
  return `${num} ${units[unit]}`;
}

function truncate(str, max) {
  if (str.length <= max) return str;
  const keep = Math.floor((max - 1) / 2);
  return `${str.slice(0, keep)}…${str.slice(-(max - keep - 1))}`;
}

export default function BuildWarningsBanner() {
  const [summary, setSummary] = useState(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      let data = null;
      try {
        if (window.electronAPI?.getBuildSummary) {
          data = await window.electronAPI.getBuildSummary();
        } else {
          const res = await fetch(`${apiBase()}/api/build/summary`);
          if (res.ok) data = await res.json();
        }
      } catch {
        data = null; // offline / no summary — just hide the banner
      }
      if (mounted) setSummary(data);
    })();
    return () => { mounted = false; };
  }, []);

  const warnings = summary?.warnings || [];
  const threshold = summary?.chunk_warn_kb;
  const builtAt = summary?.built_at;
  // Hide stale summaries (e.g. an old --prod build while running in dev mode).
  // The gate guarantees builtAt is valid whenever the banner can render, so the
  // dismissal key is always the per-build one (a fresh build re-shows it).
  const fresh = isBuildSummaryFresh(builtAt);

  if (!fresh || !warnings.length || dismissed) return null;

  const dismissKey = `aariya_build_warnings_dismissed_${builtAt}`;
  let isDismissed = false;
  try { isDismissed = localStorage.getItem(dismissKey) === '1'; } catch { /* storage blocked */ }
  if (isDismissed) return null;

  const dismiss = () => {
    try { localStorage.setItem(dismissKey, '1'); } catch { /* ignore */ }
    setDismissed(true);
  };

  const openBuildTab = () => {
    if (window.electronAPI?.openAnalytics) {
      window.electronAPI.openAnalytics();
    } else {
      window.open('http://localhost:5173/?route=analytics', '_blank', 'width=1200,height=800');
    }
  };

  const shown = warnings.slice(0, 3);
  const more = warnings.length - shown.length;
  const builtLabel = new Date(builtAt).toLocaleString();

  return (
    <div
      role="alert"
      data-testid="build-warnings-banner"
      style={{
        position: 'fixed',
        top: 92,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 60,
        width: 'min(720px, calc(100vw - 48px))',
        maxHeight: 'calc(100vh - 120px)',
        overflowY: 'auto',
        background: 'rgba(24, 16, 6, 0.92)',
        backdropFilter: 'blur(18px)',
        WebkitBackdropFilter: 'blur(18px)',
        border: `1px solid ${AMBER}55`,
        borderLeft: `4px solid ${AMBER}`,
        borderRadius: 14,
        boxShadow: `0 12px 40px rgba(0,0,0,0.5), 0 0 24px ${AMBER_DIM}, inset 0 0 18px rgba(251,191,36,0.04)`,
        padding: '14px 16px 12px',
        fontFamily: "'Inter', 'system-ui', sans-serif",
        color: '#ffe9c2',
        animation: 'fadeIn 0.35s ease-out forwards',
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        <span style={{ fontSize: 18, lineHeight: '22px', flexShrink: 0 }}>⚠️</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 800, letterSpacing: 0.5, color: AMBER, textTransform: 'uppercase' }}>
            {warnings.length} JS chunk{warnings.length === 1 ? '' : 's'} over the {threshold ?? '500'} KB warn threshold
          </div>
          <div style={{ fontSize: 11, color: 'rgba(255, 233, 194, 0.55)', marginTop: 2 }}>
            Consider code-splitting or lazy loading · built {builtLabel}
          </div>
        </div>

        {/* Dismiss */}
        <button
          onClick={dismiss}
          aria-label="Dismiss build warnings"
          style={{
            flexShrink: 0,
            width: 26,
            height: 26,
            borderRadius: '50%',
            border: '1px solid rgba(251,191,36,0.3)',
            background: 'rgba(251,191,36,0.08)',
            color: AMBER,
            cursor: 'pointer',
            fontSize: 13,
            lineHeight: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'all 0.2s ease',
          }}
          onMouseOver={(e) => { e.currentTarget.style.background = 'rgba(251,191,36,0.22)'; e.currentTarget.style.transform = 'rotate(90deg)'; }}
          onMouseOut={(e) => { e.currentTarget.style.background = 'rgba(251,191,36,0.08)'; e.currentTarget.style.transform = 'rotate(0deg)'; }}
        >
          ✕
        </button>
      </div>

      {/* Chunk list */}
      <div style={{ margin: '10px 0 4px 28px', display: 'flex', flexDirection: 'column', gap: 4 }}>
        {shown.map((w, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
            <span style={{ color: 'rgba(255,233,194,0.35)', flexShrink: 0 }}>▸</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", color: '#fff', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {truncate(w.rel, 52)}
            </span>
            <span style={{ marginLeft: 'auto', flexShrink: 0, fontFamily: "'JetBrains Mono', monospace", fontWeight: 700, color: AMBER }}>
              {formatBytes(w.size)}
            </span>
          </div>
        ))}
        {more > 0 && (
          <div style={{ fontSize: 11, color: 'rgba(255,233,194,0.45)', paddingLeft: 16 }}>
            + {more} more in the Build tab
          </div>
        )}
      </div>

      {/* Action row */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
        <button
          onClick={openBuildTab}
          style={{
            background: `linear-gradient(135deg, ${AMBER}22, ${AMBER_DIM})`,
            border: `1px solid ${AMBER}66`,
            color: AMBER,
            padding: '6px 14px',
            borderRadius: 8,
            cursor: 'pointer',
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 0.8,
            textTransform: 'uppercase',
            transition: 'all 0.2s ease',
          }}
          onMouseOver={(e) => { e.currentTarget.style.background = 'rgba(251,191,36,0.28)'; e.currentTarget.style.boxShadow = '0 0 14px rgba(251,191,36,0.3)'; }}
          onMouseOut={(e) => { e.currentTarget.style.background = 'rgba(251,191,36,0.14)'; e.currentTarget.style.boxShadow = 'none'; }}
        >
          📦 View Build tab
        </button>
      </div>
    </div>
  );
}
