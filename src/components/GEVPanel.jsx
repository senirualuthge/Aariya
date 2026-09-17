import React, { useState } from 'react';
import DraggablePanel from './DraggablePanel';
import useStore from '../store';
import './GEVPanel.css';

export default function GEVPanel() {
  const [isRefreshing, setIsRefreshing] = useState(false);
  const toggleGevPanel = useStore((s) => s.toggleGevPanel);
  const gevFocus = useStore((s) => s.gevFocus);

  const handleRefresh = () => {
    setIsRefreshing(true);
    setTimeout(() => setIsRefreshing(false), 500);
  };

  const getIframeUrl = () => {
    const baseUrl = import.meta.env.VITE_GEV_URL || 'http://localhost:4173/';
    if (!gevFocus) return baseUrl;
    const params = new URLSearchParams();
    if (gevFocus.lat) params.append('lat', gevFocus.lat);
    if (gevFocus.lon) params.append('lon', gevFocus.lon);
    if (gevFocus.layer) params.append('layer', gevFocus.layer);
    if (gevFocus.id) params.append('id', gevFocus.id);
    const qs = params.toString();
    return qs ? `${baseUrl}?${qs}` : baseUrl;
  };

  return (
    <DraggablePanel
      id="aariya_gev"
      defaultPosition={{ x: Math.max(0, window.innerWidth - 640), y: 64 }}
      defaultSize={{ width: '600px', height: '600px' }}
      className="ui-panel gev-panel"
    >
      <div className="drag-handle panel-title-bar">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="2" y1="12" x2="22" y2="12"></line>
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>
        </svg>
        God's Eye View (GEV)
        <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px' }}>
          <button
            onClick={handleRefresh}
            className="gev-icon-btn"
            title="Refresh Map"
          >
            ↻
          </button>
          <button
            onClick={toggleGevPanel}
            className="gev-icon-btn"
            title="Close Panel"
          >
            ✕
          </button>
        </div>
      </div>

      <div className="gev-content-container">
        {/* HUD Overlays */}
        <div className="hud-overlay scanning-line"></div>
        <div className="hud-overlay reticle top-left"></div>
        <div className="hud-overlay reticle top-right"></div>
        <div className="hud-overlay reticle bottom-left"></div>
        <div className="hud-overlay reticle bottom-right"></div>
        
        {!isRefreshing ? (
          <iframe
            src={getIframeUrl()}
            title="God's Eye View"
            className="gev-iframe"
            allow="geolocation"
          />
        ) : (
          <div className="gev-refreshing-state">
            Refreshing map data...
          </div>
        )}
      </div>
    </DraggablePanel>
  );
}
