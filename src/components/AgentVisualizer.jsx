import React, { useEffect, useRef, useState } from 'react';
import { useAgentRegistry } from '../hooks/useAgentRegistry';
import useStore from '../store';

const CORE_SYSTEMS = [
  { id: 'sys_stabilizer', name: 'Stabilizer', desc: 'Input Smoothing',    color: '#10b981', angleOffset: 0 },
  { id: 'sys_intent',     name: 'IntentLayer',desc: 'Classification',     color: '#a78bfa', angleOffset: Math.PI / 3 },
  { id: 'sys_governor',   name: 'Governor',   desc: 'Module Control',     color: '#f59e0b', angleOffset: 2 * Math.PI / 3 },
  { id: 'sys_validator',  name: 'Validator',  desc: 'A/B Quality Check',  color: '#ec4899', angleOffset: Math.PI },
  { id: 'sys_selfmodel',  name: 'SelfModel',  desc: 'Reflection Engine',  color: '#3b82f6', angleOffset: 4 * Math.PI / 3 },
  { id: 'sys_router',     name: 'ModeRouter', desc: 'Behavior Switching', color: '#06b6d4', angleOffset: 5 * Math.PI / 3 },
];

const AgentVisualizer = ({ signals, selectedAgent, onSelectAgent }) => {
  const { agents } = useAgentRegistry();
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const { personalityPreset, trust } = useStore();
  
  const particlesRef = useRef([]);
  const activeBeamsRef = useRef([]);
  const nodesRef = useRef([]);
  const timeRef = useRef(0);
  const mouseRef = useRef({ x: -1000, y: -1000 });
  const [hoveredNodeId, setHoveredNodeId] = useState(null);

  // Mouse interaction
  const handleMouseMove = (e) => {
    if (!canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    mouseRef.current.x = e.clientX - rect.left;
    mouseRef.current.y = e.clientY - rect.top;

    // Detect hover
    let found = null;
    for (const node of nodesRef.current) {
       const dist = Math.hypot(node.sx - mouseRef.current.x, node.sy - mouseRef.current.y);
       if (dist < (node.radius * (node.scale || 1)) + 15) {
          found = node.id;
          break;
       }
    }
    setHoveredNodeId(found);
    canvasRef.current.style.cursor = found ? 'pointer' : 'default';
  };

  const handleMouseClick = () => {
     let found = null;
     for (const node of nodesRef.current) {
        const dist = Math.hypot(node.sx - mouseRef.current.x, node.sy - mouseRef.current.y);
        if (dist < (node.radius * (node.scale || 1)) + 15) {
           found = node;
           break;
        }
     }
     if (found && found.agentData) {
         if (onSelectAgent) onSelectAgent(found.agentData);
     } else if (!found && onSelectAgent) {
         onSelectAgent(null);
     }
  };

  // Signal processing for real-time activity
  useEffect(() => {
    if (signals.length === 0) return;
    const latestSignal = signals[0];
    const sourceName = latestSignal.source?.system || 'AariyaBrain';
    const currentNodes = nodesRef.current;
    
    const brainNode = currentNodes.find(n => n.id === 'core');
    if (!brainNode) return;

    let sourceNode = currentNodes.find(n => n.name.includes(sourceName) || sourceName.includes(n.name)) || brainNode;
    let targetNode = brainNode;
    const isCoreModuleSource = CORE_SYSTEMS.some(sys => sys.id === sourceNode.id);

    if (sourceNode.id === 'core') {
       const availNodes = currentNodes.filter(n => n.id !== 'core');
       if (availNodes.length > 0) targetNode = availNodes[Math.floor(Math.random() * availNodes.length)];
    } else if (!isCoreModuleSource && Math.random() > 0.5) {
       const coreNodes = currentNodes.filter(n => CORE_SYSTEMS.some(sys => sys.id === n.id));
       if (coreNodes.length > 0) targetNode = coreNodes[Math.floor(Math.random() * coreNodes.length)];
    } else if (isCoreModuleSource) {
       targetNode = brainNode;
    }
      
    if (sourceNode && targetNode && sourceNode.id !== targetNode.id) {
       let color = '#00f2ff';
       if (latestSignal.severity === 'critical') color = '#ef4444';
       else if (latestSignal.severity === 'high') color = '#fb923c';
       else if (latestSignal.severity === 'warning') color = '#ffd93d';
       
       // Add beam (instant powerful data transfer)
       activeBeamsRef.current.push({
           sourceId: sourceNode.id,
           targetId: targetNode.id,
           color,
           life: 1.0, // Fades out
       });

       // Add particles
       const count = latestSignal.severity === 'critical' ? 8 : 3;
       for(let i=0; i<count; i++) {
           setTimeout(() => {
               if(particlesRef.current.length < 150) {
                   particlesRef.current.push({
                     sourceId: sourceNode.id,
                     targetId: targetNode.id,
                     color,
                     progress: 0,
                     speed: 0.02 + Math.random() * 0.03,
                     wobble: Math.random() * 20 - 10,
                     offset: Math.random() * Math.PI * 2
                   });
               }
           }, i * 50);
       }
    }
  }, [signals]);

  // Main Render Loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let animationFrameId;

    const resize = () => {
      const rect = canvas.parentElement.getBoundingClientRect();
      canvas.width = rect.width;
      canvas.height = rect.height;
    };
    resize();
    window.addEventListener('resize', resize);

    // Advanced 3D projection
    const project = (x3d, y3d, z3d, cx, cy) => {
        // Isometric tilt
        const tilt = Math.PI / 3.5; // ~51 degrees
        const yRot = Math.cos(tilt) * y3d - Math.sin(tilt) * z3d;
        const zRot = Math.sin(tilt) * y3d + Math.cos(tilt) * z3d;
        
        // Depth scale
        const depth = 800;
        const zOff = zRot + 400; 
        const scale = depth / (depth + zOff);
        
        return {
            sx: cx + x3d * scale,
            sy: cy + yRot * scale,
            scale: scale
        };
    };

    const render = () => {
      timeRef.current += 0.01;
      const t = timeRef.current;
      const width = canvas.width;
      const height = canvas.height;
      
      if(width === 0 || height === 0) {
          animationFrameId = window.requestAnimationFrame(render);
          return;
      }
      
      const centerX = width / 2;
      const centerY = height / 2.2; // Shift up slightly
      
      // Update Nodes
      const newNodes = [];
      const brainRadius = 35 + Math.sin(t * 5) * 4;
      newNodes.push({ id: 'core', name: 'AariyaBrain', x3d: 0, y3d: -40, z3d: 0, radius: brainRadius, color: '#00f2ff', agentData: null });
      
      const coreRadius = Math.min(width, height) * 0.35; 
      CORE_SYSTEMS.forEach(sys => {
        const ang = sys.angleOffset + t * 0.3;
        newNodes.push({
           id: sys.id, name: sys.name, desc: sys.desc,
           x3d: Math.cos(ang) * coreRadius,
           y3d: 0,
           z3d: Math.sin(ang) * coreRadius,
           radius: 20, color: sys.color, isCoreSys: true, agentData: null
        });
      });

      const totalAgents = agents.length;
      const outerRadius = Math.min(width, height) * 0.65;
      agents.forEach((agent, i) => {
        const ang = (i / totalAgents) * Math.PI * 2 - (t * 0.15);
        let color = '#4a9eff';
        if (agent.status === 'new') color = '#ffc800';
        if (agent.status === 'removed') color = '#ff4444';
        
        newNodes.push({
          id: agent.name, name: agent.name,
          x3d: Math.cos(ang) * outerRadius,
          y3d: Math.sin(t * 3 + i) * 15, // Bobbing
          z3d: Math.sin(ang) * outerRadius,
          radius: 16, color, status: agent.status, isAgent: true, agentData: agent
        });
      });

      // Apply projections
      newNodes.forEach(n => {
          const p = project(n.x3d, n.y3d, n.z3d, centerX, centerY);
          n.sx = p.sx; n.sy = p.sy; n.scale = p.scale;
      });
      
      // Sort by depth for correct 3D overlap drawing
      nodesRef.current = newNodes;
      const sortedNodes = [...newNodes].sort((a, b) => a.scale - b.scale);

      // Background
      ctx.fillStyle = 'rgba(7, 8, 15, 0.6)'; 
      ctx.fillRect(0, 0, width, height);
      
      // Grid Floor
      ctx.save();
      ctx.beginPath();
      for(let i = -1000; i <= 1000; i += 100) {
          const l1 = project(i, 0, -1000, centerX, centerY);
          const l2 = project(i, 0, 1000, centerX, centerY);
          ctx.moveTo(l1.sx, l1.sy); ctx.lineTo(l2.sx, l2.sy);
          const r1 = project(-1000, 0, i, centerX, centerY);
          const r2 = project(1000, 0, i, centerX, centerY);
          ctx.moveTo(r1.sx, r1.sy); ctx.lineTo(r2.sx, r2.sy);
      }
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.03)';
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.restore();

      // Orbital Rings (Projected)
      const drawRing = (rad, color, dash) => {
          ctx.beginPath();
          for(let i=0; i<=60; i++) {
              const ang = (i/60) * Math.PI * 2;
              const px = Math.cos(ang) * rad;
              const pz = Math.sin(ang) * rad;
              const p = project(px, 0, pz, centerX, centerY);
              i===0 ? ctx.moveTo(p.sx, p.sy) : ctx.lineTo(p.sx, p.sy);
          }
          if(dash) ctx.setLineDash(dash);
          ctx.strokeStyle = color;
          ctx.stroke();
          ctx.setLineDash([]);
      };
      drawRing(coreRadius, 'rgba(0, 242, 255, 0.1)', [4, 12]);
      drawRing(outerRadius, 'rgba(100, 150, 255, 0.05)', [2, 8]);

      // Active Connection Beams
      for (let i = activeBeamsRef.current.length - 1; i >= 0; i--) {
          const beam = activeBeamsRef.current[i];
          beam.life -= 0.02;
          if (beam.life <= 0) { activeBeamsRef.current.splice(i, 1); continue; }
          const src = newNodes.find(n => n.id === beam.sourceId);
          const tgt = newNodes.find(n => n.id === beam.targetId);
          if (src && tgt) {
              ctx.beginPath();
              ctx.moveTo(src.sx, src.sy);
              
              // Draw an arc/curve
              const midX = (src.sx + tgt.sx)/2;
              const midY = (src.sy + tgt.sy)/2 - 100 * beam.life;
              ctx.quadraticCurveTo(midX, midY, tgt.sx, tgt.sy);
              
              ctx.strokeStyle = `${beam.color}${Math.floor(beam.life * 255).toString(16).padStart(2,'0')}`;
              ctx.lineWidth = 3 * beam.life;
              ctx.shadowBlur = 10;
              ctx.shadowColor = beam.color;
              ctx.stroke();
              ctx.shadowBlur = 0;
          }
      }

      // Live Particles
      for (let i = particlesRef.current.length - 1; i >= 0; i--) {
        const p = particlesRef.current[i];
        p.progress += p.speed;
        if (p.progress >= 1) { particlesRef.current.splice(i, 1); continue; }
        
        const src = newNodes.find(n => n.id === p.sourceId);
        const tgt = newNodes.find(n => n.id === p.targetId);
        if(!src || !tgt) { particlesRef.current.splice(i, 1); continue; }

        const ease = p.progress;
        // Interpret 3D path
        const curX = src.x3d + (tgt.x3d - src.x3d) * ease;
        const curY = src.y3d + (tgt.y3d - src.y3d) * ease - Math.sin(ease * Math.PI) * 50; // Arcing jump
        const curZ = src.z3d + (tgt.z3d - src.z3d) * ease;
        
        const proj = project(curX, curY, curZ, centerX, centerY);
        const wobbleX = Math.cos(p.offset + t * 10) * p.wobble * proj.scale;
        const wobbleY = Math.sin(p.offset + t * 10) * p.wobble * proj.scale;

        ctx.beginPath();
        ctx.arc(proj.sx + wobbleX, proj.sy + wobbleY, Math.max(1, 4 * proj.scale), 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.fill();
        ctx.beginPath();
        ctx.arc(proj.sx + wobbleX, proj.sy + wobbleY, Math.max(2, 8 * proj.scale), 0, Math.PI * 2);
        ctx.strokeStyle = p.color;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Draw Nodes
      sortedNodes.forEach(node => {
        const isHovered = node.id === hoveredNodeId;
        const isSelected = selectedAgent && selectedAgent.name === node.id;
        const rad = node.radius * node.scale;

        // HUD Reticle for selected
        if (isSelected) {
            ctx.save();
            ctx.translate(node.sx, node.sy);
            ctx.rotate(t * 2);
            ctx.beginPath();
            ctx.arc(0, 0, rad + 15, 0, Math.PI*2);
            ctx.setLineDash([10, 15]);
            ctx.strokeStyle = '#00f2ff';
            ctx.lineWidth = 2;
            ctx.stroke();
            ctx.restore();
        }

        // Drop shadow / Floor glow
        ctx.beginPath();
        ctx.ellipse(node.sx, node.sy + 10 * node.scale, rad * 1.5, rad * 0.4, 0, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(0,0,0, 0.5)`;
        ctx.fill();

        // Node Outer Glow
        ctx.beginPath();
        ctx.arc(node.sx, node.sy, rad + (isHovered ? 12 : 6), 0, Math.PI * 2);
        const grad = ctx.createRadialGradient(node.sx, node.sy, rad*0.2, node.sx, node.sy, rad + (isHovered ? 12 : 6));
        grad.addColorStop(0, `${node.color}${isHovered ? 'FF' : 'AA'}`);
        grad.addColorStop(1, 'transparent');
        ctx.fillStyle = grad;
        ctx.fill();

        // Node Core
        ctx.beginPath();
        ctx.arc(node.sx, node.sy, rad, 0, Math.PI * 2);
        ctx.fillStyle = '#0a0d16';
        ctx.fill();
        ctx.lineWidth = node.isCoreSys ? 3 : 2;
        ctx.strokeStyle = node.color;
        if (node.status === 'removed') ctx.strokeStyle = `rgba(255, 68, 68, 0.8)`;
        else if (node.status === 'new') ctx.strokeStyle = `rgba(255, 200, 0, 0.8)`;
        ctx.stroke();

        ctx.beginPath();
        ctx.arc(node.sx, node.sy, rad * 0.4, 0, Math.PI*2);
        ctx.fillStyle = node.color;
        ctx.fill();

        // Labels
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.globalAlpha = node.scale * 1.2; // Fade distant nodes
        
        if (node.id === 'core') {
            ctx.fillStyle = '#fff';
            ctx.font = `bold ${Math.max(10, 14 * node.scale)}px "Inter", sans-serif`;
            ctx.fillText(node.name, node.sx, node.sy + rad + 8);
            ctx.fillStyle = '#00f2ff';
            ctx.font = `${Math.max(8, 11 * node.scale)}px monospace`;
            ctx.fillText(`[${(personalityPreset||'BALANCED').toUpperCase()}]`, node.sx, node.sy + rad + 22);
        } else if (node.isCoreSys) {
            ctx.fillStyle = '#fff';
            ctx.font = `bold ${Math.max(9, 12 * node.scale)}px sans-serif`;
            ctx.fillText(node.name, node.sx, node.sy + rad + 6);
            ctx.fillStyle = node.color;
            ctx.font = `${Math.max(8, 10 * node.scale)}px monospace`;
            ctx.fillText(node.desc, node.sx, node.sy + rad + 18);
        } else {
            ctx.fillStyle = isSelected ? '#00f2ff' : 'rgba(255,255,255,0.8)';
            ctx.font = `${isSelected ? 'bold ' : ''}${Math.max(9, 11 * node.scale)}px monospace`;
            let label = node.name.replace('Agent', '');
            if (label.length > 12) label = label.substring(0, 10) + '..';
            ctx.fillText(label, node.sx, node.sy + rad + 6);
            if (node.status === 'new') {
                ctx.fillStyle = '#ffc800';
                ctx.fillText('[NEW]', node.sx, node.sy + rad + Math.max(9, 11 * node.scale) + 8);
            }
        }
        ctx.globalAlpha = 1.0;
      });

      animationFrameId = window.requestAnimationFrame(render);
    };

    render();

    return () => {
      window.cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', resize);
    };
  }, [agents, personalityPreset, trust, selectedAgent, hoveredNodeId]);

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', minHeight: '400px', position: 'relative', background: 'radial-gradient(ellipse at center, #0b0c14 0%, #030408 100%)', borderRadius: 12, border: '1px solid rgba(255,255,255,0.05)', overflow: 'hidden', boxShadow: 'inset 0 0 40px rgba(0,0,0,0.8)' }}>
      
      {/* Title Overlay */}
      <div style={{ position: 'absolute', top: 16, left: 20, zIndex: 10, pointerEvents: 'none' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#00f2ff', boxShadow: '0 0 10px #00f2ff', animation: 'statusPulse 2s infinite' }}></div>
            <div style={{ color: '#00f2ff', fontSize: 13, letterSpacing: 3, fontWeight: 800, textTransform: 'uppercase' }}>Cognitive Swarm Topology</div>
        </div>
        <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: 10, letterSpacing: 1, marginTop: 6, fontFamily: 'monospace' }}>
            // 3D Isometric Projection [Live Monitoring]
        </div>
      </div>

      {/* Selected Agent Info Panel Overlay */}
      {selectedAgent && (
        <div style={{ 
            position: 'absolute', top: 16, right: 16, zIndex: 20, 
            width: 320, background: 'rgba(10, 12, 20, 0.85)', backdropFilter: 'blur(16px)',
            border: '1px solid #4a9eff88', borderRadius: 10, padding: 16,
            boxShadow: '0 16px 40px rgba(0,0,0,0.6), inset 0 0 20px rgba(74, 158, 255, 0.1)',
            animation: 'fadeInSlide 0.3s cubic-bezier(0.16, 1, 0.3, 1)'
        }}>
           <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: 12, marginBottom: 12 }}>
               <div>
                   <h3 style={{ margin: 0, color: '#cce0ff', fontSize: 16, fontFamily: 'monospace', textTransform: 'uppercase', letterSpacing: 1 }}>{selectedAgent.name}</h3>
                   <span style={{ display: 'inline-block', marginTop: 6, color: '#445', fontSize: 10, background: '#111a2a', padding: '2px 8px', borderRadius: 4, letterSpacing: 1 }}>{selectedAgent.kind?.toUpperCase() || 'SWARM AGENT'}</span>
               </div>
               <button onClick={() => onSelectAgent?.(null)} style={{ background: 'none', border: 'none', color: '#889', cursor: 'pointer', fontSize: 18 }}>×</button>
           </div>
           
           <div style={{ marginBottom: 12 }}>
               <div style={{ fontSize: 10, color: '#889', letterSpacing: 1, textTransform: 'uppercase', marginBottom: 4 }}>Memory Location</div>
               <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#556877', wordBreak: 'break-all' }}>{selectedAgent.file}:{selectedAgent.line}</div>
           </div>

           {selectedAgent.docstring && (
             <div style={{ marginBottom: 12 }}>
                 <div style={{ fontSize: 10, color: '#889', letterSpacing: 1, textTransform: 'uppercase', marginBottom: 4 }}>Directive</div>
                 <div style={{ fontStyle: 'italic', fontSize: 12, color: '#fff', lineHeight: 1.4, opacity: 0.8 }}>"{selectedAgent.docstring}"</div>
             </div>
           )}

           <div style={{ marginBottom: 12 }}>
               <div style={{ fontSize: 10, color: '#889', letterSpacing: 1, textTransform: 'uppercase', marginBottom: 6 }}>Class Inheritance</div>
               <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                   {(selectedAgent.base_classes || []).map(b => (
                       <span key={b} style={{ fontSize: 10, color: '#a78bfa', background: 'rgba(167, 139, 250, 0.1)', padding: '2px 6px', border: '1px solid rgba(167, 139, 250, 0.2)', borderRadius: 4 }}>↑ {b}</span>
                   ))}
               </div>
           </div>

           <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 16, paddingTop: 12, borderTop: '1px solid rgba(255,255,255,0.1)' }}>
               <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                   <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#10b981', boxShadow: '0 0 8px #10b981', animation: 'statusPulse 2s infinite' }}></div>
                   <span style={{ fontSize: 10, color: '#10b981', letterSpacing: 1, fontWeight: 'bold' }}>SYSTEM ONLINE</span>
               </div>
               <span style={{ fontSize: 10, color: '#445', fontFamily: 'monospace' }}>UPTIME: OK</span>
           </div>
        </div>
      )}

      {/* Global Telemetry Bottom Left (moved to left to avoid conflicting with panel if extended) */}
      <div style={{ position: 'absolute', bottom: 16, left: 20, zIndex: 10, background: 'rgba(10,12,20,0.7)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: '12px 16px', backdropFilter: 'blur(8px)', pointerEvents: 'none' }}>
          <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.4)', letterSpacing: 1.5, marginBottom: 8, textTransform: 'uppercase', display: 'flex', gap: 20 }}>
             <span>Global Routing</span>
             <span style={{ color: '#00f2ff', animation: 'statusPulse 2s infinite' }}>● ACTIVE</span>
          </div>
          <div style={{ display: 'flex', gap: 16 }}>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ fontSize: 15, color: '#10b981', fontFamily: 'monospace', fontWeight: 'bold' }}>{agents.filter(a => a.status!=='removed').length}</span>
                  <span style={{ fontSize: 9, color: '#556' }}>AGENTS</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ fontSize: 15, color: '#a78bfa', fontFamily: 'monospace', fontWeight: 'bold' }}>6</span>
                  <span style={{ fontSize: 9, color: '#556' }}>CORES</span>
              </div>
          </div>
      </div>

      <canvas 
        ref={canvasRef} 
        onMouseMove={handleMouseMove}
        onClick={handleMouseClick}
        style={{ width: '100%', height: '100%', display: 'block' }}
      />
    </div>
  );
};

export default AgentVisualizer;
