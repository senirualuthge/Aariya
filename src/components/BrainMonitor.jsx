import React, { useEffect, useState } from 'react';
import useStore from '../store';
import DraggablePanel from './DraggablePanel';
import { subscribeMetrics } from '../systems/metricsClient';
import { apiBase } from '../utils/apiHost';

const ProgressBar = ({ label, value, color, min = 0, max = 100 }) => {
    const pct = ((value - min) / (max - min)) * 100;
    return (
        <div style={{ marginBottom: '8px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: '#ccc', marginBottom: '2px' }}>
                <span>{label}</span>
                <span>{typeof value === 'number' ? value.toFixed(1) : value}%</span>
            </div>
            <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', overflow: 'hidden' }}>
                <div style={{ width: `${Math.min(100, Math.max(0, pct))}%`, height: '100%', background: color, transition: 'width 0.2s ease' }} />
            </div>
        </div>
    );
};

export default function BrainMonitor() {
    const { thinking } = useStore();
    const [health, setHealth] = useState(null);
    const [conn, setConn] = useState(false);

    // Primary: poll the REST health endpoint (confirmed live) so the panel
    // always shows real data even if the metrics websocket isn't connected.
    // Secondary: the shared /ws/brain_metrics stream pushes fresh frames every
    // 2 s — whichever arrives last wins.
    useEffect(() => {
        let cancelled = false;
        const load = () => {
            fetch(`${apiBase()}/api/system/health`)
                .then(r => r.ok ? r.json() : null)
                .then(d => { if (!cancelled && d) setHealth(d); })
                .catch(() => {});
        };
        load();
        const timer = setInterval(load, 3000);

        const unsub = subscribeMetrics(
            (m) => m.type === 'system_health',
            (m) => { if (m.data) setHealth(m.data); }
        );
        // Brain online status — same `__conn` event the dashboard's BRAIN chip
        // uses, so this panel is ONLINE exactly when the brain is ONLINE.
        const unsubConn = subscribeMetrics(
            (m) => m.type === '__conn',
            (m) => setConn(!!m.connected)
        );

        return () => {
            cancelled = true;
            clearInterval(timer);
            unsub();
            unsubConn();
        };
    }, []);

    const server = health?.server || {};
    const cpu = server.cpu_percent ?? 0;
    const ram = server.ram_percent ?? 0;
    const swap = server.swap_percent ?? 0;
    const processCpu = server.process?.cpu_percent ?? 0;
    const processRss = server.process?.rss_mb ?? 0;
    const loadAvg = server.load_avg ? server.load_avg[0] : 0;

    // ONLINE = brain metrics socket connected AND real health data present.
    const ts = health?.ts ?? 0;
    const stale = (Date.now() / 1000) - ts > 10;
    const online = conn && !!health && !stale;

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
            <div className="drag-handle drag-handle-mini">⋮⋮ Drag</div>
            <h3 style={{ margin: '0 0 10px 0', fontSize: '14px', color: '#00f2ff', borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '4px' }}>
                🖥️ SYSTEM TELEMETRY
            </h3>

            {/* STATUS */}
            <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', flexWrap: 'wrap' }}>
                <div style={{ background: '#10b981', color: '#000', padding: '2px 6px', borderRadius: '4px', fontWeight: 'bold', fontSize: '10px' }}>
                    ● REAL TELEMETRY
                </div>
                <div style={{ background: thinking ? '#fff' : 'rgba(255,255,255,0.1)', color: thinking ? '#000' : '#ccc', padding: '2px 6px', borderRadius: '4px', fontWeight: 'bold', fontSize: '10px' }}>
                    {thinking ? '⚡ AI INFERENCE: THINKING' : '💤 AI INFERENCE: IDLE'}
                </div>
                <div style={{ background: online ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)', color: online ? '#10b981' : '#ef4444', padding: '2px 6px', borderRadius: '4px', fontSize: '10px' }}>
                    {online ? 'SERVER ONLINE' : 'OFFLINE'}
                </div>
            </div>

            {/* SERVER RESOURCES */}
            <div style={{ marginBottom: '16px' }}>
                <div style={{ fontSize: '10px', opacity: 0.7, marginBottom: '6px' }}>SYSTEM RESOURCES</div>
                <ProgressBar label="CPU Usage" value={cpu} color={cpu > 80 ? "#ef4444" : cpu > 50 ? "#ffd93d" : "#00f2ff"} />
                <ProgressBar label="RAM Usage" value={ram} color={ram > 80 ? "#ef4444" : ram > 50 ? "#ffd93d" : "#00f2ff"} />
                <ProgressBar label="Swap Memory" value={swap} color={swap > 50 ? "#ef4444" : "#a78bfa"} />
            </div>

            {/* PROCESS METRICS */}
            <div style={{ marginBottom: '16px' }}>
                <div style={{ fontSize: '10px', opacity: 0.7, marginBottom: '6px' }}>PROCESS METRICS</div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', marginBottom: '4px' }}>
                    <span style={{ color: '#ccc' }}>Process CPU</span>
                    <span style={{ color: '#fff', fontFamily: 'monospace' }}>{processCpu.toFixed(1)}%</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', marginBottom: '4px' }}>
                    <span style={{ color: '#ccc' }}>Process RAM (RSS)</span>
                    <span style={{ color: '#fff', fontFamily: 'monospace' }}>{processRss} MB</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', marginBottom: '4px' }}>
                    <span style={{ color: '#ccc' }}>Load Avg (1m)</span>
                    <span style={{ color: '#fff', fontFamily: 'monospace' }}>{loadAvg.toFixed(2)}</span>
                </div>
            </div>
            
            {/* NETWORK I/O */}
            <div>
                 <div style={{ fontSize: '10px', opacity: 0.7, marginBottom: '6px' }}>NETWORK I/O (MB)</div>
                 <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px' }}>
                    <span style={{ color: '#ccc' }}>Total Sent</span>
                    <span style={{ color: '#34d399', fontFamily: 'monospace' }}>{server.network?.bytes_sent_mb ?? 0} MB</span>
                 </div>
                 <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', marginTop: '4px' }}>
                    <span style={{ color: '#ccc' }}>Total Recv</span>
                    <span style={{ color: '#a78bfa', fontFamily: 'monospace' }}>{server.network?.bytes_recv_mb ?? 0} MB</span>
                 </div>
            </div>
        </DraggablePanel>
    );
}
