import React from 'react';
import { useAdminUIStore } from '../store/useAdminUIStore';
import { useSignalsStore } from '../store/useSignalsStore';

export default function Sidebar() {
  const { activePage, setPage, sidebarOpen } = useAdminUIStore();
  const signals = useSignalsStore(s => s.signals);
  
  const criticalCount = signals.filter(s => s.severity === 'critical' && s.status === 'new').length;

  const menuItems = [
    { id: 'overview', label: 'Overview', icon: '📊' },
    { id: 'live_monitor', label: 'Live Monitor', icon: '📡' },
    { id: 'timeline', label: 'Timeline', icon: '⏱️' },
    { id: 'signals', label: 'Signals & Bugs', icon: '🐞', count: criticalCount },
    { id: 'qos', label: 'QoS & Network', icon: '🌐' },
    { id: 'health', label: 'System Health', icon: '⚙️' }
  ];

  if (!sidebarOpen) return null;

  return (
    <div style={{
      width: '260px',
      background: '#0a0a0f',
      borderRight: '1px solid rgba(255,143,163,0.1)',
      display: 'flex',
      flexDirection: 'column',
      height: '100%'
    }}>
      <div style={{ padding: '24px 20px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
        <h2 style={{ margin: 0, color: '#ff8fa3', fontSize: '1.2rem', letterSpacing: '1px', textTransform: 'uppercase' }}>
          SignalBus <span style={{ color: '#fff', opacity: 0.5 }}>Admin</span>
        </h2>
      </div>

      <div style={{ padding: '20px 12px', display: 'flex', flexDirection: 'column', gap: '4px', flex: 1 }}>
        {menuItems.map(item => (
          <button
            key={item.id}
            onClick={() => setPage(item.id)}
            style={{
              padding: '12px 16px',
              background: activePage === item.id ? 'rgba(255,143,163,0.15)' : 'transparent',
              border: 'none',
              borderRadius: '8px',
              color: activePage === item.id ? '#ff8fa3' : 'rgba(255,255,255,0.6)',
              textAlign: 'left',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              fontWeight: activePage === item.id ? '600' : '400',
              transition: 'all 0.2s',
              fontSize: '0.95rem'
            }}
            onMouseOver={e => {
              if (activePage !== item.id) e.currentTarget.style.background = 'rgba(255,255,255,0.05)';
            }}
            onMouseOut={e => {
              if (activePage !== item.id) e.currentTarget.style.background = 'transparent';
            }}
          >
            <span style={{ marginRight: '12px', fontSize: '1.1rem' }}>{item.icon}</span>
            {item.label}
            {item.count > 0 && (
              <span style={{
                marginLeft: 'auto',
                background: '#dc2626',
                color: '#fff',
                padding: '2px 8px',
                borderRadius: '12px',
                fontSize: '0.75rem',
                fontWeight: 'bold'
              }}>
                {item.count}
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
