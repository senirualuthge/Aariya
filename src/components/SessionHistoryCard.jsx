/**
 * src/components/SessionHistoryCard.jsx
 * Real session + memory history from the backend analytics API.
 *   GET /api/analytics/overview  → session rows + lifetime totals
 *   GET /api/analytics/memories  → significant memories (timeline)
 * Polls every 30 s. Shows honest empty/error states — never fabricates.
 */

import { useEffect, useState } from 'react';
import { apiBase } from '../utils/apiHost';

const REFRESH_MS = 30000;

function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(typeof ts === 'number' ? ts : String(ts).replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return String(ts);
  return d.toLocaleString();
}

export default function SessionHistoryCard() {
  const [overview, setOverview] = useState(null);
  const [memories, setMemories] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;

    async function load() {
      try {
        const [oRes, mRes] = await Promise.all([
          fetch(`${apiBase()}/api/analytics/overview?limit=10`),
          fetch(`${apiBase()}/api/analytics/memories?limit=6`),
        ]);
        if (!oRes.ok) throw new Error(`overview ${oRes.status}`);
        if (!mRes.ok) throw new Error(`memories ${mRes.status}`);
        const o = await oRes.json();
        const m = await mRes.json();
        if (!alive) return;
        setOverview(o);
        setMemories(m);
        setError(null);
      } catch (e) {
        if (alive) setError(e.message);
      }
    }

    load();
    const t = setInterval(load, REFRESH_MS);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const info = overview?.user_info || {};
  const sessions = overview?.sessions || [];

  const labelStyle = {
    fontSize: 11, color: 'rgba(255,255,255,0.4)',
    letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 12,
  };

  return (
    <div style={{
      background: 'rgba(255,255,255,0.03)', borderRadius: 14,
      border: '1px solid rgba(255,255,255,0.06)', padding: 18,
    }}>
      <div style={{ ...labelStyle, display: 'flex', justifyContent: 'space-between' }}>
        <span>📅 Session History &amp; Memory Timeline</span>
        <span style={{ letterSpacing: 0, textTransform: 'none' }}>live · 30s</span>
      </div>

      {error && (
        <div style={{ fontSize: 12, color: '#f87171' }}>
          Analytics unavailable ({error}) — showing no fabricated data.
        </div>
      )}

      {!error && !overview && (
        <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)' }}>Loading…</div>
      )}

      {overview && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 14 }}>
            <Stat label="Total Sessions" value={info.total_sessions ?? 0} />
            <Stat label="Last Session" value={fmtTime(info.last_session)} small />
            <Stat
              label="Lifetime Avg Valence"
              value={info.lifetime_avg_valence == null ? '—'
                : `${(info.lifetime_avg_valence * 100).toFixed(0)}%`}
              color={info.lifetime_avg_valence >= 0 ? '#34d399' : '#ff9a9e'}
            />
          </div>

          {sessions.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              {sessions.slice(0, 3).map((s) => (
                <div key={s.session_id} style={{
                  display: 'flex', justifyContent: 'space-between', fontSize: 11,
                  color: 'rgba(255,255,255,0.55)', padding: '3px 0',
                  fontFamily: 'monospace',
                }}>
                  <span>{s.session_id?.slice(0, 8)}</span>
                  <span>{fmtTime(s.start_time)}</span>
                  <span>v {(s.avg_valence ?? 0).toFixed(2)} · a {(s.avg_arousal ?? 0).toFixed(2)}</span>
                </div>
              ))}
            </div>
          )}

          {Array.isArray(memories) && memories.length > 0 && (
            <div>
              <div style={{ ...labelStyle, marginBottom: 8 }}>Significant Memories</div>
              {memories.map((m) => (
                <div key={m.memory_id} style={{
                  display: 'flex', gap: 10, alignItems: 'baseline',
                  fontSize: 12, padding: '5px 0',
                  borderBottom: '1px solid rgba(255,255,255,0.04)',
                }}>
                  <span style={{
                    flexShrink: 0, width: 54, height: 4, alignSelf: 'center',
                    background: `rgba(52,211,153,${Math.max(0.15, m.significance ?? 0)})`,
                    borderRadius: 2,
                  }} />
                  <span style={{ flex: 1, color: 'rgba(255,255,255,0.75)' }}>{m.content}</span>
                  <span style={{ flexShrink: 0, fontSize: 10, color: 'rgba(255,255,255,0.35)', fontFamily: 'monospace' }}>
                    {fmtTime(m.timestamp)}
                  </span>
                </div>
              ))}
            </div>
          )}

          {Array.isArray(memories) && memories.length === 0 && sessions.length === 0 && (
            <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.4)' }}>
              No sessions or memories recorded yet for user_default.
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Stat({ label, value, color = '#e5e7eb', small = false }) {
  return (
    <div style={{
      background: 'rgba(0,0,0,0.25)', borderRadius: 10, padding: '10px 12px',
    }}>
      <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.4)', letterSpacing: 1, textTransform: 'uppercase' }}>
        {label}
      </div>
      <div style={{
        fontSize: small ? 13 : 20, fontWeight: 700, color, marginTop: 2,
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      }}>
        {value}
      </div>
    </div>
  );
}
