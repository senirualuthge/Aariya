// src/components/ThermalMonitor.tsx
/**
 * Thermal Monitor Component
 * 
 * Displays real-time thermal state and performance metrics
 */

import { useEffect, useState } from 'react';
import { thermalController, ThermalLevel } from '../core/thermalController';
import type { ThermalState } from '../core/thermalController';

export default function ThermalMonitor() {
  const [state, setState] = useState<ThermalState | null>(null);
  const [visible, setVisible] = useState(false);
  
  useEffect(() => {
    // Update state every second
    const interval = setInterval(() => {
      setState(thermalController.getState());
    }, 1000);
    
    // Listen for thermal events
    const handleThermalChange = (e: CustomEvent) => {
      console.log('[Thermal Monitor] Thermal state changed:', e.detail);
      setState(thermalController.getState());
      
      // Show monitor when thermal throttling occurs
      if (e.detail.level > ThermalLevel.Normal) {
        setVisible(true);
      }
    };
    
    window.addEventListener('thermalStateChanged', handleThermalChange as EventListener);
    
    // Keyboard shortcut to toggle (Ctrl+Shift+T)
    const handleKeyPress = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'T') {
        setVisible(v => !v);
      }
    };
    
    window.addEventListener('keydown', handleKeyPress);
    
    return () => {
      clearInterval(interval);
      window.removeEventListener('thermalStateChanged', handleThermalChange as EventListener);
      window.removeEventListener('keydown', handleKeyPress);
    };
  }, []);
  
  if (!visible || !state) return null;
  
  const getLevelColor = (level: ThermalLevel): string => {
    switch (level) {
      case ThermalLevel.Normal: return '#4ade80';
      case ThermalLevel.Light: return '#fbbf24';
      case ThermalLevel.Medium: return '#fb923c';
      case ThermalLevel.Heavy: return '#f87171';
      case ThermalLevel.Critical: return '#dc2626';
      default: return '#9ca3af';
    }
  };
  
  const getLevelName = (level: ThermalLevel): string => {
    return ThermalLevel[level];
  };
  
  return (
    <div style={{
      position: 'fixed',
      top: '10px',
      right: '10px',
      backgroundColor: 'rgba(0, 0, 0, 0.85)',
      color: '#fff',
      padding: '12px 16px',
      borderRadius: '8px',
      fontFamily: 'monospace',
      fontSize: '12px',
      zIndex: 10000,
      minWidth: '250px',
      backdropFilter: 'blur(10px)',
      border: `2px solid ${getLevelColor(state.level)}`,
    }}>
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center',
        marginBottom: '10px',
      }}>
        <strong>🌡️ Thermal Monitor</strong>
        <button
          onClick={() => setVisible(false)}
          style={{
            background: 'transparent',
            border: 'none',
            color: '#fff',
            cursor: 'pointer',
            fontSize: '16px',
          }}
        >
          ✕
        </button>
      </div>
      
      <div style={{ marginBottom: '8px' }}>
        <div style={{ 
          display: 'flex', 
          justifyContent: 'space-between',
          marginBottom: '4px',
        }}>
          <span>Level:</span>
          <strong style={{ color: getLevelColor(state.level) }}>
            {getLevelName(state.level)}
          </strong>
        </div>
        
        {state.degradationReason !== 'none' && (
          <div style={{ fontSize: '10px', color: '#9ca3af' }}>
            Reason: {state.degradationReason.replace(/_/g, ' ')}
          </div>
        )}
      </div>
      
      <div style={{ 
        borderTop: '1px solid #374151',
        paddingTop: '8px',
        marginTop: '8px',
      }}>
        <div style={{ marginBottom: '4px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>CPU Load:</span>
            <span>{state.cpuLoad.toFixed(1)}%</span>
          </div>
          <div style={{ 
            height: '4px', 
            background: '#374151', 
            borderRadius: '2px',
            marginTop: '2px',
          }}>
            <div style={{ 
              height: '100%', 
              width: `${Math.min(100, state.cpuLoad)}%`,
              background: state.cpuLoad > 85 ? '#dc2626' : state.cpuLoad > 70 ? '#fbbf24' : '#4ade80',
              borderRadius: '2px',
              transition: 'width 0.3s',
            }} />
          </div>
        </div>
        
        <div style={{ marginBottom: '4px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>GPU Time:</span>
            <span>{state.gpuFrameTime.toFixed(2)}ms</span>
          </div>
          <div style={{ 
            height: '4px', 
            background: '#374151', 
            borderRadius: '2px',
            marginTop: '2px',
          }}>
            <div style={{ 
              height: '100%', 
              width: `${Math.min(100, (state.gpuFrameTime / 33) * 100)}%`,
              background: state.gpuFrameTime > 30 ? '#dc2626' : state.gpuFrameTime > 20 ? '#fbbf24' : '#4ade80',
              borderRadius: '2px',
              transition: 'width 0.3s',
            }} />
          </div>
        </div>
        
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>Avg Frame Time:</span>
            <span>{state.avgFrameTime.toFixed(2)}ms</span>
          </div>
          <div style={{ 
            height: '4px', 
            background: '#374151', 
            borderRadius: '2px',
            marginTop: '2px',
          }}>
            <div style={{ 
              height: '100%', 
              width: `${Math.min(100, (state.avgFrameTime / 33) * 100)}%`,
              background: state.avgFrameTime > 25 ? '#dc2626' : state.avgFrameTime > 20 ? '#fbbf24' : '#4ade80',
              borderRadius: '2px',
              transition: 'width 0.3s',
            }} />
          </div>
        </div>
      </div>
      
      <div style={{ 
        marginTop: '10px',
        paddingTop: '8px',
        borderTop: '1px solid #374151',
        fontSize: '10px',
        color: '#9ca3af',
      }}>
        Press Ctrl+Shift+T to toggle
      </div>
    </div>
  );
}
