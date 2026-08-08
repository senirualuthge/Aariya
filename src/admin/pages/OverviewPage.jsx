import React from 'react';
import { useSignalsStore } from '../store/useSignalsStore';

export default function OverviewPage() {
  const signals = useSignalsStore(s => s.signals);
  
  const bugs = signals.filter(s => s.type === 'bug').length;
  const metrics = signals.filter(s => s.type === 'telemetry').length;
  const qos = signals.filter(s => s.type === 'qos').length;
  const critical = signals.filter(s => s.severity === 'critical' && s.status === 'new').length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
      <h1 style={{ margin: 0, fontSize: '1.8rem', fontWeight: 300 }}>System Overview</h1>
      
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '24px' }}>
        {[
          { label: 'Critical Open Issues', value: critical, color: critical > 0 ? '#ef4444' : '#10b981' },
          { label: 'Bugs Logged', value: bugs, color: '#3b82f6' },
          { label: 'Telemetry Events', value: metrics, color: '#8b5cf6' },
          { label: 'QoS Shifts', value: qos, color: '#f59e0b' }
        ].map((stat, i) => (
          <div key={i} style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.05)',
            padding: '24px',
            borderRadius: '12px',
            display: 'flex',
            flexDirection: 'column',
            gap: '8px'
          }}>
            <span style={{ fontSize: '0.85rem', color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '1px' }}>
              {stat.label}
            </span>
            <span style={{ fontSize: '2.5rem', fontWeight: 600, color: stat.color }}>
              {stat.value}
            </span>
          </div>
        ))}
      </div>

      <div style={{
        background: 'rgba(255,255,255,0.03)',
        border: '1px solid rgba(255,255,255,0.05)',
        borderRadius: '12px',
        padding: '24px',
        minHeight: '300px'
      }}>
        <h3 style={{ margin: '0 0 16px 0', fontSize: '1.1rem', fontWeight: 400 }}>Recent Signal Feed</h3>
        {signals.length === 0 ? (
          <div style={{ color: 'rgba(255,255,255,0.3)', textAlign: 'center', marginTop: '60px' }}>
            No signals flowing yet. Awaiting backend connection.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
             {signals.slice(0, 10).map((s, i) => (
               <div key={i} style={{
                 padding: '12px 16px',
                 background: 'rgba(255,255,255,0.02)',
                 borderLeft: `4px solid ${s.severity === 'critical' ? '#ef4444' : s.severity === 'medium' ? '#f59e0b' : '#3b82f6'}`,
                 borderRadius: '0 8px 8px 0',
                 display: 'flex',
                 justifyContent: 'space-between',
                 alignItems: 'center'
               }}>
                 <div>
                   <span style={{ fontWeight: 600, marginRight: '8px' }}>[{s.type.toUpperCase()}]</span>
                   <span>{s.payload?.title || 'Unknown Signal'}</span>
                 </div>
                 <span style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.4)' }}>
                   {new Date(s.timestamp * 1000).toLocaleTimeString()}
                 </span>
               </div>
             ))}
          </div>
        )}
      </div>
    </div>
  );
}
