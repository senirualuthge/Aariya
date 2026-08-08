import React from 'react';
import { useSessionsStore } from '../store/useSessionsStore';

export default function LiveMonitorPage() {
  const sessions = useSessionsStore(s => s.sessions);
  const sessionList = Object.values(sessions);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <h1 style={{ margin: 0, fontSize: '1.8rem', fontWeight: 300 }}>Live Monitor</h1>
      
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
        gap: '24px'
      }}>
        {sessionList.length === 0 ? (
          <div style={{ color: 'rgba(255,255,255,0.3)' }}>No active sessions detected.</div>
        ) : (
          sessionList.map(session => (
            <div key={session.sessionId} style={{
              background: 'rgba(255,255,255,0.03)',
              border: `1px solid ${session.latencyMs > 500 ? '#ef4444' : 'rgba(255,255,255,0.1)'}`,
              padding: '20px',
              borderRadius: '12px'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '16px' }}>
                <strong style={{ fontSize: '1.1rem' }}>{session.platform.toUpperCase()} Node</strong>
                <span style={{ color: session.latencyMs > 500 ? '#ef4444' : '#10b981' }}>
                  {session.latencyMs}ms
                </span>
              </div>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.9rem', color: 'rgba(255,255,255,0.6)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>QoS Profile</span>
                  <span style={{ color: '#fff' }}>{session.qosProfile}</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Trust Score</span>
                  <span style={{ color: '#fff' }}>{session.trustScore?.toFixed(2) || 'N/A'}</span>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
