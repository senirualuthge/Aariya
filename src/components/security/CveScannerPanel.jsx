import { useState, useEffect, useCallback } from 'react';
import { apiBase } from '../../utils/apiHost';

// ── Palette / helpers ──────────────────────────────────────────────────────────
const SEV = {
  HIGH:     { bg: 'rgba(239,68,68,0.15)',   border: '#ef4444', text: '#ef4444',   glow: 'rgba(239,68,68,0.3)'   },
  CRITICAL: { bg: 'rgba(239,68,68,0.15)',   border: '#ef4444', text: '#ef4444',   glow: 'rgba(239,68,68,0.3)'   },
  MEDIUM:   { bg: 'rgba(249,115,22,0.15)',  border: '#f97316', text: '#f97316',   glow: 'rgba(249,115,22,0.3)'  },
  MODERATE: { bg: 'rgba(249,115,22,0.15)',  border: '#f97316', text: '#f97316',   glow: 'rgba(249,115,22,0.3)'  },
  LOW:      { bg: 'rgba(16,185,129,0.12)',  border: '#10b981', text: '#10b981',   glow: 'rgba(16,185,129,0.3)'  },
  SAFE:     { bg: 'rgba(34,211,238,0.12)',  border: '#22d3ee', text: '#22d3ee',   glow: 'rgba(34,211,238,0.3)'  },
};

const TOOL_COLOR = {
  'bandit':    '#a78bfa',
  'pip-audit': '#22d3ee',
  'npm-audit': '#f0a500',
};

const TOOL_ICON = {
  'bandit':    '🐍',
  'pip-audit': '📦',
  'npm-audit': '📎',
};

// ── Sub-components ─────────────────────────────────────────────────────────────

function StatBadge({ label, value, color }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      background: 'rgba(255,255,255,0.04)', borderRadius: 12,
      border: `1px solid rgba(255,255,255,0.08)`, padding: '12px 18px', minWidth: 72,
    }}>
      <span style={{ fontSize: 22, fontWeight: 700, color }}>{value}</span>
      <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.45)', marginTop: 2, letterSpacing: 0.8 }}>{label}</span>
    </div>
  );
}

function ToolStatus({ name, available }) {
  const color = TOOL_COLOR[name] || '#888';
  const icon  = TOOL_ICON[name] || '🔧';
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px',
      borderRadius: 8, background: 'rgba(255,255,255,0.04)',
      border: `1px solid ${available ? color + '44' : 'rgba(255,255,255,0.1)'}`,
    }}>
      <span style={{ fontSize: 14 }}>{icon}</span>
      <span style={{ fontSize: 11, color: available ? color : 'rgba(255,255,255,0.3)', fontWeight: 600 }}>
        {name}
      </span>
      <span style={{
        marginLeft: 'auto', fontSize: 9, padding: '2px 6px', borderRadius: 4,
        background: available ? color + '22' : 'rgba(255,255,255,0.06)',
        color: available ? color : 'rgba(255,255,255,0.3)',
        border: `1px solid ${available ? color + '44' : 'rgba(255,255,255,0.1)'}`,
      }}>
        {available ? 'ACTIVE' : 'OFFLINE'}
      </span>
    </div>
  );
}

function FindingRow({ finding, onIgnore }) {
  const [expanded, setExpanded] = useState(false);
  const sev   = finding.severity?.toUpperCase() || 'LOW';
  const style = SEV[sev] || SEV.LOW;
  const tool  = finding.tool || 'unknown';
  const color = TOOL_COLOR[tool] || '#888';

  return (
    <div
      onClick={() => setExpanded(e => !e)}
      style={{
        borderRadius: 8, border: `1px solid ${style.border}44`,
        background: style.bg, marginBottom: 6, cursor: 'pointer',
        transition: 'all 0.2s', boxShadow: expanded ? `0 0 12px ${style.glow}` : 'none',
      }}
    >
      {/* Row header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px' }}>
        {/* Severity badge */}
        <span style={{
          fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 4,
          background: style.bg, border: `1px solid ${style.border}`, color: style.text,
          letterSpacing: 0.8, minWidth: 46, textAlign: 'center',
        }}>
          {sev}
        </span>

        {/* Tool badge */}
        <span style={{
          fontSize: 9, padding: '2px 6px', borderRadius: 4,
          background: `${color}22`, border: `1px solid ${color}44`, color,
          letterSpacing: 0.5,
        }}>
          {TOOL_ICON[tool] || '🔧'} {tool}
        </span>

        {/* Message */}
        <span style={{
          flex: 1, fontSize: 12, color: 'rgba(255,255,255,0.8)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {finding.message}
        </span>

        {/* CVE tag */}
        {finding.cve && (
          <span style={{
            fontSize: 9, padding: '2px 6px', borderRadius: 4,
            background: 'rgba(239,68,68,0.15)', border: '1px solid #ef444444', color: '#ef4444',
          }}>
            {finding.cve}
          </span>
        )}

        <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginLeft: 4 }}>
          {expanded ? '▲' : '▼'}
        </span>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div style={{
          borderTop: '1px solid rgba(255,255,255,0.06)',
          padding: '10px 12px',
          display: 'flex', flexDirection: 'column', gap: 4,
        }}>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>
            <span style={{ color: 'rgba(255,255,255,0.3)' }}>File:</span>{' '}
            <code style={{ color: '#a78bfa', fontSize: 10 }}>{finding.file || '—'}</code>
            {finding.line > 0 && (
              <span style={{ color: 'rgba(255,255,255,0.3)' }}> · Line {finding.line}</span>
            )}
          </div>
          {finding.fix && (
            <div style={{ fontSize: 11, color: '#10b981' }}>
              <span style={{ color: 'rgba(255,255,255,0.3)' }}>Fix:</span> {finding.fix}
            </div>
          )}
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)' }}>
            <span style={{ color: 'rgba(255,255,255,0.3)' }}>Confidence:</span> {finding.confidence}
          </div>
          <div style={{ marginTop: 8, display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <button
              onClick={(e) => {
                e.stopPropagation();
                const text = `[${sev}] ${tool} finding\nMessage: ${finding.message}\nCVE: ${finding.cve || 'N/A'}\nFile: ${finding.file || 'N/A'}\nFix: ${finding.fix || 'N/A'}`;
                navigator.clipboard.writeText(text);
              }}
              style={{
                padding: '4px 12px', borderRadius: 6, fontSize: 10, fontWeight: 600,
                cursor: 'pointer', background: 'transparent',
                border: `1px solid ${style.border}50`, color: style.text,
              }}
            >
              📋 Copy Threat
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onIgnore(); }}
              style={{
                padding: '4px 12px', borderRadius: 6, fontSize: 10, fontWeight: 600,
                cursor: 'pointer', background: 'transparent',
                border: `1px solid ${style.border}88`, color: style.text,
              }}
            >
              ✓ Acknowledge & Mute
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────────
export default function CveScannerPanel() {
  const [scan, setScan]         = useState(null);
  const [loading, setLoading]   = useState(false);
  const [autoRefresh, setAuto]  = useState(true);
  const [filter, setFilter]     = useState('ALL');   // ALL | SAST | SCA | HIGH | MEDIUM | LOW
  const [lastRun, setLastRun]   = useState(null);
  const [ignored, setIgnored]   = useState(new Set());

  const runScan = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const url = `${apiBase()}/api/security/scan${force ? '?force=true' : ''}`;
      const res = await fetch(url, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setScan(data);
        setLastRun(new Date());
      }
    } catch (err) {
      console.error('Security scan fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Load cached result on mount
  useEffect(() => {
    fetch(`${apiBase()}/api/security/last-scan`)
      .then(r => r.ok ? r.json() : null)
      .then(d => d && !d.message ? setScan(d) : runScan())
      .catch(() => runScan());
  }, [runScan]);

  // Auto-refresh every 2 min
  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(() => runScan(), 120_000);
    return () => clearInterval(id);
  }, [autoRefresh, runScan]);

  // ── Filtered findings ──────────────────────────────────────────────────────
  const findings = scan?.findings || [];
  const filtered = findings.filter(f => {
    const id = f.cve || f.message;
    if (ignored.has(id)) return false;
    
    if (filter === 'ALL')    return true;
    if (filter === 'SAST')   return f.type === 'SAST';
    if (filter === 'SCA')    return f.type === 'SCA';
    return f.severity?.toUpperCase() === filter;
  });

  const gateColor = scan?.gate === 'PASS' ? '#10b981' : '#ef4444';
  const gateGlow  = scan?.gate === 'PASS' ? 'rgba(16,185,129,0.4)' : 'rgba(239,68,68,0.4)';

  const panelStyle = {
    background: 'rgba(15,20,40,0.6)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: 16, padding: 20,
    backdropFilter: 'blur(12px)',
  };

  const btnStyle = (active) => ({
    padding: '4px 12px', borderRadius: 6, fontSize: 10, fontWeight: 600,
    cursor: 'pointer', letterSpacing: 0.5, transition: 'all 0.15s',
    background: active ? 'rgba(167,139,250,0.2)' : 'transparent',
    border: `1px solid ${active ? '#a78bfa' : 'rgba(255,255,255,0.1)'}`,
    color: active ? '#a78bfa' : 'rgba(255,255,255,0.45)',
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* ── Header ────────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#fff', letterSpacing: 0.5 }}>
            🔍 CVE Scanner — Live Security Analysis
          </div>
          <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', marginTop: 2 }}>
            SAST · SCA · Dependency Audit · npm Audit
            {lastRun && <span> · Last run: {lastRun.toLocaleTimeString()}</span>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            onClick={() => setAuto(a => !a)}
            style={{
              ...btnStyle(autoRefresh),
              color: autoRefresh ? '#22d3ee' : 'rgba(255,255,255,0.45)',
              borderColor: autoRefresh ? '#22d3ee' : 'rgba(255,255,255,0.1)',
              background:  autoRefresh ? 'rgba(34,211,238,0.1)' : 'transparent',
            }}
          >
            {autoRefresh ? '⏸ Auto' : '▶ Auto'}
          </button>
          <button
            onClick={() => runScan(true)}
            disabled={loading}
            style={{
              padding: '5px 14px', borderRadius: 7, fontSize: 11, fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer',
              background: loading ? 'rgba(255,255,255,0.04)' : 'rgba(167,139,250,0.15)',
              border: `1px solid ${loading ? 'rgba(255,255,255,0.08)' : '#a78bfa88'}`,
              color: loading ? 'rgba(255,255,255,0.3)' : '#a78bfa',
              transition: 'all 0.2s',
            }}
          >
            {loading ? '⟳ Scanning…' : '⟳ Run Scan'}
          </button>
        </div>
      </div>

      {/* ── Gate + Stats Row ──────────────────────────────────────────── */}
      {scan && (
        <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: 16 }}>
          {/* Gate */}
          <div style={{
            ...panelStyle,
            display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: 6,
            boxShadow: `0 0 20px ${gateGlow}`,
            border: `1px solid ${gateColor}44`,
          }}>
            <span style={{ fontSize: 28 }}>{scan.gate === 'PASS' ? '✅' : '❌'}</span>
            <span style={{ fontSize: 13, fontWeight: 800, color: gateColor, letterSpacing: 1.5 }}>
              {scan.gate}
            </span>
            <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.3)', textAlign: 'center' }}>
              Security Gate
            </span>
          </div>

          {/* Stats */}
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <StatBadge label="HIGH" value={scan.summary?.high ?? 0}   color="#ef4444" />
            <StatBadge label="MEDIUM" value={scan.summary?.medium ?? 0} color="#f97316" />
            <StatBadge label="LOW" value={scan.summary?.low ?? 0}     color="#10b981" />
            <StatBadge label="PY Clean" value={`${scan.summary?.python_packages_clean ?? 0}/${scan.summary?.python_packages_total ?? 0}`} color="#22d3ee" />
            <StatBadge label="Scan Time" value={`${scan.duration_ms ?? 0}ms`} color="#a78bfa" />
          </div>
        </div>
      )}

      {/* ── Tool Status ────────────────────────────────────────────────── */}
      {scan?.tools && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {Object.entries(scan.tools).map(([name, avail]) => (
            <ToolStatus key={name} name={name.replace('_', '-')} available={avail} />
          ))}
        </div>
      )}

      {/* ── Findings list ──────────────────────────────────────────────── */}
      <div style={panelStyle}>
        {/* Filter bar */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginRight: 4 }}>Filter:</span>
          {['ALL', 'HIGH', 'MEDIUM', 'LOW', 'SAST', 'SCA'].map(f => (
            <button key={f} style={btnStyle(filter === f)} onClick={() => setFilter(f)}>{f}</button>
          ))}
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'rgba(255,255,255,0.3)' }}>
            {filtered.length} finding{filtered.length !== 1 ? 's' : ''}
          </span>
        </div>

        {/* Loading */}
        {loading && !scan && (
          <div style={{ textAlign: 'center', padding: '40px 0', color: 'rgba(255,255,255,0.3)', fontSize: 13 }}>
            <div style={{ fontSize: 28, marginBottom: 8, animation: 'spin 1.2s linear infinite', display: 'inline-block' }}>⟳</div>
            <div>Running security scanners…</div>
            <div style={{ fontSize: 10, marginTop: 4, opacity: 0.5 }}>This may take 30–90 seconds</div>
          </div>
        )}

        {/* No findings */}
        {!loading && scan && filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: '30px 0', color: 'rgba(255,255,255,0.25)' }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>✅</div>
            <div style={{ fontSize: 13 }}>No findings match the current filter</div>
          </div>
        )}

        {/* Findings */}
        <div style={{ maxHeight: 340, overflowY: 'auto', paddingRight: 4 }}>
          {filtered.map((f, i) => (
            <FindingRow 
              key={i} 
              finding={f} 
              onIgnore={() => setIgnored(prev => new Set([...prev, f.cve || f.message]))} 
            />
          ))}
        </div>
      </div>

      {/* No scan yet */}
      {!scan && !loading && (
        <div style={{
          textAlign: 'center', padding: '40px 0',
          color: 'rgba(255,255,255,0.25)', fontSize: 13,
        }}>
          <div style={{ fontSize: 36, marginBottom: 10 }}>🔍</div>
          <div>No scan data yet</div>
          <button
            onClick={() => runScan(true)}
            style={{
              marginTop: 12, padding: '8px 20px', borderRadius: 8,
              background: 'rgba(167,139,250,0.2)', border: '1px solid #a78bfa88',
              color: '#a78bfa', fontSize: 12, cursor: 'pointer', fontWeight: 600,
            }}
          >
            Run First Scan
          </button>
        </div>
      )}
    </div>
  );
}
