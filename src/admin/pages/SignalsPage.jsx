import React, { useState } from 'react';
import { useSignalsStore } from '../store/useSignalsStore';

export default function SignalsPage() {
  const { signals, acknowledge, resolve } = useSignalsStore();
  const [filter, setFilter] = useState('all');

  const filtered = signals.filter(s => {
    if (filter === 'all') return true;
    if (filter === 'bugs') return s.type === 'bug' || s.type === 'error';
    if (filter === 'telemetry') return s.type === 'telemetry';
    return true;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1 style={{ margin: 0, fontSize: '1.8rem', fontWeight: 300 }}>Signals & Bugs</h1>
        <div style={{ display: 'flex', gap: '8px' }}>
          {['all', 'bugs', 'telemetry'].map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              style={{
                background: filter === f ? 'rgba(255,143,163,0.2)' : 'rgba(255,255,255,0.05)',
                color: filter === f ? '#ff8fa3' : '#fff',
                border: '1px solid rgba(255,143,163,0.3)',
                padding: '6px 16px',
                borderRadius: '16px',
                cursor: 'pointer',
                textTransform: 'capitalize'
              }}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      <div style={{ 
        flex: 1, 
        background: 'rgba(255,255,255,0.02)', 
        border: '1px solid rgba(255,255,255,0.05)',
        borderRadius: '12px',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column'
      }}>
        {/* Table Header */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '120px 100px 1fr 180px 150px 150px',
          padding: '16px 20px',
          background: 'rgba(255,255,255,0.03)',
          borderBottom: '1px solid rgba(255,255,255,0.05)',
          color: 'rgba(255,255,255,0.5)',
          fontSize: '0.8rem',
          textTransform: 'uppercase',
          letterSpacing: '1px'
        }}>
          <span>Time</span>
          <span>Severity</span>
          <span>Signal Title</span>
          <span>Source</span>
          <span>Status</span>
          <span>Actions</span>
        </div>

        {/* Table Body */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {filtered.length === 0 ? (
            <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.3)', marginTop: '40px' }}>
              No signals found for this filter.
            </div>
          ) : (
            filtered.map((s) => (
              <div key={s.id} style={{
                display: 'grid',
                gridTemplateColumns: '120px 100px 1fr 180px 150px 150px',
                padding: '16px 20px',
                borderBottom: '1px solid rgba(255,255,255,0.02)',
                alignItems: 'center',
                fontSize: '0.9rem'
              }}>
                <span style={{ color: 'rgba(255,255,255,0.5)' }}>
                  {new Date(s.timestamp * 1000).toLocaleTimeString()}
                </span>
                
                <span style={{
                  color: s.severity === 'critical' ? '#ef4444' : s.severity === 'high' ? '#f97316' : '#10b981',
                  fontWeight: 600
                }}>
                  {s.severity.toUpperCase()}
                </span>

                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ fontWeight: 500 }}>{s.payload?.title || s.type}</span>
                  {s.payload?.description && (
                    <span style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.4)', marginTop: '4px' }}>
                      {s.payload.description}
                    </span>
                  )}
                </div>

                <span style={{ color: '#8b5cf6', fontSize: '0.85rem' }}>
                  {s.source?.system || 'Unknown'}
                </span>

                <span style={{
                  color: s.status === 'new' ? '#fff' : 'rgba(255,255,255,0.3)',
                  textTransform: 'capitalize'
                }}>
                  {s.status}
                </span>

                <div style={{ display: 'flex', gap: '8px' }}>
                  {s.status === 'new' && (
                    <>
                      <button onClick={() => acknowledge(s.id)} style={btnStyle}>Ack</button>
                      <button onClick={() => resolve(s.id)} style={{...btnStyle, color: '#10b981'}}>Resolve</button>
                    </>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

const btnStyle = {
  background: 'rgba(255,255,255,0.1)',
  border: 'none',
  padding: '6px 12px',
  borderRadius: '4px',
  color: '#fff',
  cursor: 'pointer',
  fontSize: '0.8rem'
};
