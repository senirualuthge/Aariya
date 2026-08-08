import React from 'react';
import { useAdminUIStore } from '../store/useAdminUIStore';
import { useSignalsStore } from '../store/useSignalsStore';

export default function TopBar() {
  const { toggleSidebar } = useAdminUIStore();
  const signals = useSignalsStore(s => s.signals);

  const errorCount = signals.filter(s => ['bug', 'error', 'anomaly'].includes(s.type) && s.status === 'new').length;
  
  // Calculate stability visually mapping to the spec requirement 
  const stability = errorCount > 10 ? '🔴 Unstable' : errorCount > 0 ? '🟡 Degraded' : '🟢 Optimal';

  return (
    <div style={{
      height: '64px',
      background: 'rgba(10,14,26,0.8)',
      backdropFilter: 'blur(10px)',
      borderBottom: '1px solid rgba(255,255,255,0.05)',
      display: 'flex',
      alignItems: 'center',
      padding: '0 24px',
      justifyContent: 'space-between'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
        <button 
          onClick={toggleSidebar}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'rgba(255,255,255,0.6)',
            cursor: 'pointer',
            fontSize: '1.2rem',
            padding: '4px'
          }}
        >
          ☰
        </button>
        
        <div style={{
          background: 'rgba(255,255,255,0.05)',
          padding: '6px 16px',
          borderRadius: '20px',
          fontSize: '0.85rem',
          color: '#fff',
          fontWeight: '500',
          border: '1px solid rgba(255,255,255,0.1)'
        }}>
          System Status: {stability}
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        {errorCount > 0 && (
          <div style={{ color: '#fbbf24', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>⚠️ {errorCount} Active Issues</span>
          </div>
        )}
        
        <div style={{ width: '1px', height: '24px', background: 'rgba(255,255,255,0.1)' }} />
        
        <select style={{
          background: 'transparent',
          border: 'none',
          color: 'rgba(255,255,255,0.6)',
          outline: 'none',
          cursor: 'pointer',
          fontSize: '0.9rem'
        }}>
          <option value="prod">Production</option>
          <option value="staging">Staging</option>
          <option value="local">Local Development</option>
        </select>
      </div>
    </div>
  );
}
