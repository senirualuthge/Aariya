import React from 'react';
import useStore from '../store';
import DraggablePanel from './DraggablePanel';

// Helper component for progress bars - moved outside to avoid recreation on each render
const ProgressBar = ({ label, value, color, min = -1, max = 1 }) => {
    const pct = ((value - min) / (max - min)) * 100;
    return (
        <div style={{ marginBottom: '8px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: '#ccc', marginBottom: '2px' }}>
                <span>{label}</span>
                <span>{value.toFixed(2)}</span>
            </div>
            <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', overflow: 'hidden' }}>
                <div style={{ width: `${Math.min(100, Math.max(0, pct))}%`, height: '100%', background: color, transition: 'width 0.2s ease' }} />
            </div>
        </div>
    );
};

export default function BrainMonitor() {
    const { 
        personalityAxes, 
        userAudioStats, 
        currentPersonality, 
        emotions,
        thinking
    } = useStore();

    return (
        <DraggablePanel 
            id="aariya_brain_monitor"
            defaultPosition={{ x: window.innerWidth - 252, y: 32 }}
            defaultSize={{ width: '220px' }}
            autoHeight={true}
            className="ui-panel" 
            style={{
                fontSize: '12px',
                zIndex: 40
            }}
        >
            <div className="drag-handle" style={{ cursor: 'grab', fontSize: '0.65rem', color: 'rgba(255,255,255,0.4)', marginBottom: '0.3rem' }}>⋮⋮ Drag</div>
            <h3 style={{ margin: '0 0 10px 0', fontSize: '14px', color: '#ff8fa3', borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '4px' }}>
                🧠 NEURAL MONITOR
            </h3>

            {/* STATUS */}
            <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
                <div style={{ background: thinking ? '#fff' : 'rgba(255,255,255,0.1)', color: thinking ? '#000' : '#ccc', padding: '2px 6px', borderRadius: '4px', fontWeight: 'bold', fontSize: '10px' }}>
                    {thinking ? '⚡ THINKING' : '💤 IDLE'}
                </div>
                <div style={{ background: 'rgba(255, 143, 163, 0.2)', color: '#ff8fa3', padding: '2px 6px', borderRadius: '4px', fontSize: '10px' }}>
                    {currentPersonality?.toUpperCase()}
                </div>
            </div>

            {/* AXES */}
            <div style={{ marginBottom: '16px' }}>
                <div style={{ fontSize: '10px', opacity: 0.7, marginBottom: '6px' }}>PERSONALITY AXES</div>
                <ProgressBar label="Energy" value={personalityAxes?.energy || 0} color="#ffeb3b" min={-1} max={1} />
                <ProgressBar label="Warmth" value={personalityAxes?.warmth || 0} color="#ff9800" min={-1} max={1} />
                <ProgressBar label="Dominance" value={personalityAxes?.dominance || 0} color="#f44336" min={-1} max={1} />
            </div>

            {/* INPUTS */}
            <div style={{ marginBottom: '16px' }}>
                <div style={{ fontSize: '10px', opacity: 0.7, marginBottom: '6px' }}>SENSORY INPUT</div>
                <ProgressBar label="Audio Energy" value={(userAudioStats?.energy || 0) / 255} color="#00bcd4" min={0} max={1} />
                <div style={{ fontSize: '10px', color: userAudioStats?.isLoud ? '#f44336' : '#ccc' }}>
                    {userAudioStats?.isLoud ? '⚠ LOUD DETECTED' : '✓ Audio Safe'}
                </div>
            </div>

            {/* EMOTIONS */}
            <div>
                 <div style={{ fontSize: '10px', opacity: 0.7, marginBottom: '6px' }}>EMOTION STATE</div>
                 {Object.entries(emotions || {})
                    .sort(([, a], [, b]) => b - a)
                    .slice(0, 3)
                    .map(([key, val]) => (
                        <ProgressBar key={key} label={key.toUpperCase()} value={val} color="#e91e63" min={0} max={1.5} />
                    ))
                 }
            </div>
        </DraggablePanel>
    );
}
