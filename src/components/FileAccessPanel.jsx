import React, { useEffect, useRef, useState } from 'react';
import { eventBus } from '../core/EventBus';
import { BRAIN_EVENT } from '../systems/brainClient';

/**
 * FileAccessPanel.jsx
 * ───────────────────
 * Appears whenever Aariya actually touches local files, shows WHAT is
 * happening (real operation name, real paths, real outcome + duration fed by
 * the backend's `file_access` frames over /ws/dashboard/stream), then fades
 * away a few seconds after the last operation finishes. The next file access
 * makes it reappear automatically.
 *
 * No synthetic activity: if no `file_access` frames arrive, this panel never
 * renders. Frames come from two real sources:
 *   - filesystem router (list/read/search/semantic/sandbox/screenshot)
 *   - safety governor  (write/append/delete/open/denials/rollback — covers
 *     chat-driven and agent-driven access too)
 */

const HIDE_AFTER_MS = 4000; // linger after the last op completes, then hide
const MAX_ROWS = 6;

const OP_LABELS = {
  list_directory: 'Listing directory',
  read_file: 'Reading file',
  search_files: 'Searching files',
  semantic_search: 'Semantic search',
  write_file: 'Writing file',
  append_file: 'Appending to file',
  delete_file: 'Deleting file',
  open_path: 'Opening with OS',
  run_code: 'Running sandboxed code',
  rollback: 'Rolling back changes',
  screenshot_write: 'Capturing screen',
};

const COLORS = {
  running: '#67e8f9',   // cyan — in progress
  executed: '#34d399',  // emerald — succeeded
  denied: '#fbbf24',    // amber — refused (governor/guard said no)
  error: '#f87171',     // red — failed
};

function shortPath(p) {
  if (!p) return '';
  const parts = String(p).split('/').filter(Boolean);
  if (parts.length <= 2) return p;
  return `…/${parts.slice(-2).join('/')}`;
}

function basename(p) {
  if (!p) return '';
  return String(p).split('/').filter(Boolean).pop() || p;
}

export default function FileAccessPanel() {
  const [ops, setOps] = useState({});       // id → {op, paths, status, detail, duration_ms}
  const [order, setOrder] = useState([]);   // insertion order of ids
  const [visible, setVisible] = useState(false);
  const hideTimer = useRef(null);

  useEffect(() => {
    const onMessage = (data) => {
      if (!data || data.type !== 'file_access') return;

      setOps((prev) => {
        const next = { ...prev };
        if (data.phase === 'start') {
          next[data.id] = {
            op: data.op,
            paths: data.paths,
            actor: data.actor,
            status: 'running',
            startedAt: data.ts,
          };
        } else {
          // end frame — either updates a tracked start or stands alone
          // (single-frame ops like governor mutations).
          const existing = next[data.id];
          next[data.id] = existing
            ? { ...existing, status: data.status, detail: data.detail,
                duration_ms: data.duration_ms }
            : { op: data.op, paths: data.paths, actor: data.actor,
                status: data.status, detail: data.detail,
                duration_ms: data.duration_ms };
        }
        return next;
      });
      setOrder((prev) => (prev.includes(data.id) ? prev : [...prev, data.id]));

      // Any activity (re)shows the panel and re-arms the auto-hide timer.
      setVisible(true);
      if (hideTimer.current) clearTimeout(hideTimer.current);
      hideTimer.current = setTimeout(() => setVisible(false), HIDE_AFTER_MS);
    };

    const unsub = eventBus.subscribe(BRAIN_EVENT, onMessage);
    return () => {
      unsub();
      if (hideTimer.current) clearTimeout(hideTimer.current);
    };
  }, []);

  const rows = order
    .slice(-MAX_ROWS)
    .map((id) => ({ id, ...ops[id] }))
    .filter((r) => r && r.op);

  if (!visible || rows.length === 0) return null;
  const runningCount = rows.filter((r) => r.status === 'running').length;

  return (
    <div data-testid="file-access-panel" style={styles.wrap}>
      <style>{`
        @keyframes fap-spin { to { transform: rotate(360deg); } }
        @keyframes fap-in { from { opacity: 0; transform: translateY(8px); }
                            to { opacity: 1; transform: translateY(0); } }
      `}</style>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{
          width: 8, height: 8, borderRadius: '50%',
          background: runningCount > 0 ? COLORS.running : COLORS.executed,
          boxShadow: runningCount > 0 ? `0 0 8px ${COLORS.running}` : 'none',
          flexShrink: 0,
        }} />
        <span style={{
          fontSize: 11, fontWeight: 800, letterSpacing: 1.2,
          textTransform: 'uppercase', color: 'rgba(226,254,255,0.9)',
        }}>
          Local File Access
        </span>
        <span style={{
          marginLeft: 'auto', fontSize: 10, fontFamily: "'JetBrains Mono', monospace",
          color: runningCount > 0 ? COLORS.running : 'rgba(226,254,255,0.45)',
        }}>
          {runningCount > 0 ? `${runningCount} running` : 'done'}
        </span>
      </div>

      {/* Operation rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {rows.map((r) => {
          const color = COLORS[r.status] || COLORS.running;
          return (
            <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {/* status glyph */}
              {r.status === 'running' ? (
                <span style={{
                  flexShrink: 0, width: 12, height: 12, color,
                  display: 'inline-flex', animation: 'fap-spin 0.9s linear infinite',
                }}>◠</span>
              ) : (
                <span style={{ flexShrink: 0, fontSize: 12, color }}>
                  {r.status === 'executed' ? '✓' : r.status === 'denied' ? '⊘' : '✕'}
                </span>
              )}

              {/* what + where */}
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 11.5, color: '#e7feff', whiteSpace: 'nowrap' }}>
                  {OP_LABELS[r.op] || r.op}
                  {r.paths.length > 0 && (
                    <span
                      title={r.paths.join('\n')}
                      style={{
                        fontFamily: "'JetBrains Mono', monospace", fontSize: 10.5,
                        color: 'rgba(226,254,255,0.55)', marginLeft: 6,
                      }}
                    >
                      {r.paths.length === 1
                        ? basename(r.paths[0]) || shortPath(r.paths[0])
                        : `${r.paths.length} paths`}
                    </span>
                  )}
                </div>
              </div>

              {/* outcome */}
              <span style={{
                flexShrink: 0, fontFamily: "'JetBrains Mono', monospace",
                fontSize: 10, fontWeight: 700, color,
              }}>
                {r.status === 'running'
                  ? '…'
                  : r.duration_ms != null
                    ? `${r.duration_ms.toFixed(0)}ms`
                    : r.status}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const styles = {
  wrap: {
    position: 'fixed',
    bottom: 24,
    left: 24,
    zIndex: 70,
    width: 320,
    maxHeight: '40vh',
    overflowY: 'auto',
    background: 'rgba(4, 18, 24, 0.88)',
    backdropFilter: 'blur(16px)',
    WebkitBackdropFilter: 'blur(16px)',
    border: '1px solid rgba(103, 232, 249, 0.28)',
    borderRadius: 12,
    padding: '12px 14px',
    fontFamily: "'Inter', 'system-ui', sans-serif",
    boxShadow: '0 10px 32px rgba(0,0,0,0.45), inset 0 0 16px rgba(103,232,249,0.04)',
    animation: 'fap-in 0.3s ease-out forwards',
  },
};
