import React, { useRef, useMemo, useState, useEffect } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls, Line, Text, Stars, Html } from '@react-three/drei';
import * as THREE from 'three';

// ── Configuration ─────────────────────────────────────────────────────────────
// When 'auto', predictive ghost/anomaly overlays render ONLY if the backend
// reports real GNN training. Set to true/false to force the behavior.
const PREDICTIVE_OVERLAYS = 'auto'; // 'auto' | true | false

// ── Color mapping ─────────────────────────────────────────────────────────────
function valenceToColor(v) {
    if (v > 0.65) return new THREE.Color('#00ff99');  // Positive
    if (v < 0.35) return new THREE.Color('#ff2255');  // Negative
    return new THREE.Color('#00d2ff');                 // Neutral
}

function BrainCore({ trust = 0.5, valence = 0.0 }) {
    const meshRef = useRef();
    const matRef  = useRef();
    const haloRef = useRef();
    const color = useMemo(() => valenceToColor(valence), [valence]);

    useFrame(({ clock }) => {
        if (!meshRef.current || !matRef.current || !haloRef.current) return;
        const breathe = Math.sin(clock.elapsedTime * 1.8) * 0.06;
        const s = 0.7 + trust * 0.5 + breathe;
        meshRef.current.scale.setScalar(s);
        matRef.current.emissiveIntensity = 0.3 + trust * 0.5 + Math.sin(clock.elapsedTime * 2) * 0.15;
        matRef.current.color.lerp(color, 0.05);
        matRef.current.emissive.lerp(color, 0.05);
        
        // Animated rotations
        haloRef.current.rotation.x = clock.elapsedTime * 0.15;
        haloRef.current.rotation.y = clock.elapsedTime * 0.2;
        meshRef.current.rotation.y = clock.elapsedTime * -0.1;
    });

    return (
        <group>
            {/* Outer glow ring */}
            <mesh ref={haloRef} position={[0, 0, 0]}>
                <icosahedronGeometry args={[1.7, 2]} />
                <meshStandardMaterial
                    color={color} emissive={color}
                    emissiveIntensity={0.2}
                    transparent opacity={0.15}
                    wireframe
                />
            </mesh>
            {/* Inner solid core */}
            <mesh ref={meshRef} position={[0, 0, 0]}>
                <icosahedronGeometry args={[1, 4]} />
                <meshStandardMaterial
                    ref={matRef}
                    color={color} emissive={color}
                    emissiveIntensity={0.5}
                    roughness={0.1} metalness={0.8}
                    transparent opacity={0.3}
                    wireframe
                />
            </mesh>
        </group>
    );
}

// ── Planetary orbit visualizer ───────────────────────────────────────────────
function Planet({ data, index, total }) {
    const meshRef = useRef();
    const glowRef = useRef();
    const groupRef = useRef();
    const ringRef = useRef();
    
    // Distribute orbits
    // Base distance is 3.5, but varied by index
    const baseDistance = 3.5 + (index * 1.2); 
    const angleOffset = (index / total) * Math.PI * 2;
    
    // Physics targets for lerping. Predictive orbit: velocity boosts speed
    // (doc §241: orbit_speed + velocity * 2).
    const targetRadius = useRef(data.radius || 0.25);
    const targetSpeed = useRef((data.orbit_speed || 0.5) + (data.velocity || 0) * 2);
    const targetGlow = useRef(data.glow || 0.5);
    
    useEffect(() => {
        targetRadius.current = data.radius || 0.25;
        targetSpeed.current = (data.orbit_speed || 0.5) + (data.velocity || 0) * 2;
        targetGlow.current = data.glow || 0.5;
    }, [data.radius, data.orbit_speed, data.glow, data.velocity]);

    useFrame(({ clock }, delta) => {
        if (!meshRef.current || !groupRef.current || !glowRef.current) return;
        
        // Smoothly interpolate current values towards targets
        const currentSpeed = THREE.MathUtils.lerp(groupRef.current.userData.speed || (data.orbit_speed || 0.5), targetSpeed.current, 0.05);
        groupRef.current.userData.speed = currentSpeed;
        
        const currentRadius = meshRef.current.scale.x;
        const newRadius = THREE.MathUtils.lerp(currentRadius, targetRadius.current, 0.05);
        meshRef.current.scale.setScalar(newRadius);
        glowRef.current.scale.setScalar(newRadius * 1.8);
        
        const currentGlow = glowRef.current.material.opacity;
        const newGlow = THREE.MathUtils.lerp(currentGlow, targetGlow.current * 0.3, 0.05);
        glowRef.current.material.opacity = newGlow;
        
        if (ringRef.current) {
            ringRef.current.rotation.x = Math.PI / 2; // Flat by default
        }

        // Orbital mechanics
        const time = clock.elapsedTime;
        // Group rotates around origin
        groupRef.current.rotation.y = time * currentSpeed + angleOffset;
        
        // Tilt slightly (different per planet)
        groupRef.current.rotation.z = Math.sin(index) * 0.15;
        groupRef.current.rotation.x = Math.cos(index) * 0.15;
        
        // Planet rotates on own axis
        meshRef.current.rotation.y += currentSpeed * delta * 2;
    });

    return (
        <group ref={groupRef}>
            {/* Orbit path line */}
            <mesh ref={ringRef}>
                <ringGeometry args={[baseDistance - 0.02, baseDistance + 0.02, 64]} />
                <meshBasicMaterial color={data.color} transparent opacity={0.08} side={THREE.DoubleSide} />
            </mesh>

            <group position={[baseDistance, 0, 0]}>
                {/* Glow Ring */}
                <mesh ref={glowRef}>
                    <sphereGeometry args={[1, 16, 16]} />
                    <meshBasicMaterial color={data.color} transparent opacity={0.15} />
                </mesh>
                
                {/* Planet Body */}
                <mesh ref={meshRef}>
                    <sphereGeometry args={[1, 32, 32]} />
                    <meshStandardMaterial 
                        color={data.color} 
                        emissive={data.color}
                        emissiveIntensity={0.6}
                        roughness={0.2}
                        metalness={0.8}
                    />
                </mesh>
                
                {/* Planet Label */}
                <Text
                    position={[0, -1.8 * targetRadius.current - 0.6, 0]}
                    fontSize={0.28}
                    color="white"
                    anchorX="center" anchorY="middle"
                    font={undefined} // Use default
                >
                    {data.name}
                </Text>
            </group>
        </group>
    );
}

function PlanetarySystem({ planets }) {
    if (!planets || !planets.length) return null;
    return (
        <group>
            {planets.map((p, i) => (
                <Planet key={p.id} data={p} index={i} total={planets.length} />
            ))}
        </group>
    );
}

// ── Floating metric label (HTML overlay in 3D space) ──────────────────────────
function MetricBadge({ position, label, value, color }) {
    return (
        <Html position={position} center>
            <div style={{
                background: 'rgba(0,0,0,0.7)', border: `1px solid ${color}`,
                borderRadius: 6, padding: '3px 8px', color, fontSize: 11,
                fontFamily: 'monospace', whiteSpace: 'nowrap', pointerEvents: 'none',
                boxShadow: `0 0 8px ${color}44`
            }}>
                <span style={{ color: 'rgba(255,255,255,0.5)', marginRight: 4 }}>{label}</span>
                <strong>{value}</strong>
            </div>
        </Html>
    );
}

// ── Camera Focus Controller ────────────────────────────────────────────────────
// Smoothly animates OrbitControls target + camera position
function CameraFocus({ controlsRef }) {
    const { camera } = useThree();
    const targetPos = useRef(new THREE.Vector3());
    const targetLook = useRef(new THREE.Vector3());
    const active = useRef(false);

    useEffect(() => {
        // Reset to default overview position
        targetPos.current.set(0, 0, 16);
        targetLook.current.set(0, 0, 0);
        active.current = true;
    }, []);

    useFrame(() => {
        if (!active.current) return;
        camera.position.lerp(targetPos.current, 0.08);
        if (controlsRef.current) {
            controlsRef.current.target.lerp(targetLook.current, 0.08);
            controlsRef.current.update();
        }
        // Stop when close enough
        if (camera.position.distanceTo(targetPos.current) < 0.05) {
            active.current = false;
        }
    });

    return null;
}

// ── Predictive Ghost Layer (§225) — faded future positions ─────────────────────
function GhostLayer({ predicted }) {
    if (!predicted || !Array.isArray(predicted) || predicted.length === 0) return null;
    return (
        <group>
            {predicted.map((p, i) => {
                const radius = 2.5 + (i % 5) * 0.9;
                const angle = (i / Math.max(1, predicted.length)) * Math.PI * 2;
                return (
                    <mesh key={`ghost-${i}`} position={[Math.cos(angle) * radius, Math.sin(angle) * radius, -0.4]}>
                        <sphereGeometry args={[0.16, 12, 12]} />
                        <meshBasicMaterial color="#00a2ff" transparent opacity={0.35} depthWrite={false} />
                    </mesh>
                );
            })}
        </group>
    );
}

// ── Anomaly Heatmap (§226) — red zones pulsing on deviation ────────────────────
function AnomalyHeatmap({ anomalies }) {
    if (!anomalies || !Array.isArray(anomalies) || anomalies.length === 0) return null;
    return (
        <group>
            {anomalies.slice(0, 6).map((a, i) => {
                const sev = a.severity ?? 0.5;
                const radius = 3.2 + (i % 4) * 1.0;
                const angle = (i / Math.max(1, anomalies.length)) * Math.PI * 2;
                return (
                    <group key={`anom-${i}`} position={[Math.cos(angle) * radius, Math.sin(angle) * radius, -0.2]}>
                        <mesh>
                            <sphereGeometry args={[0.5 + sev * 0.5, 12, 12]} />
                            <meshBasicMaterial color="#ff2255" transparent opacity={0.5 + sev * 0.3} />
                        </mesh>
                        <Html distanceFactor={6} position={[0, 0.9, 0]}>
                            <div style={{
                                color: '#ff4466', fontSize: 9, fontFamily: 'monospace',
                                whiteSpace: 'nowrap', textShadow: '0 0 6px rgba(255,34,85,0.8)',
                            }}>
                                {String(a.location || a.type || 'ANOMALY').toUpperCase()}
                            </div>
                        </Html>
                    </group>
                );
            })}
        </group>
    );
}

// ── Event Shock Waves (§227) — expanding ripples from anomalies ────────────────
function ShockWaves({ anomalies }) {
    const refs = useRef([]);
    const count = (anomalies && Array.isArray(anomalies)) ? anomalies.length : 0;
    const baseAngle = (i) => (i / Math.max(1, count)) * Math.PI * 2;
    const baseRadius = (i) => 3.2 + (i % 4) * 1.0;
    // Hook first: an early return above useFrame would change hook order when
    // the first anomaly arrives ("rendered more hooks than during the previous
    // render"). The frame body is inert while refs are empty.
    useFrame(({ clock }) => {
        refs.current.forEach((mesh, i) => {
            if (!mesh) return;
            const t = (clock.elapsedTime + i * 0.8) % 3;
            const s = 0.4 + t * 1.4;
            mesh.scale.setScalar(s);
            mesh.material.opacity = Math.max(0, 0.6 - t * 0.25);
        });
    });
    if (count === 0) return null;
    return (
        <group>
            {Array.from({ length: count }).map((_, i) => {
                const angle = baseAngle(i);
                const radius = baseRadius(i);
                return (
                    <mesh
                        key={`shock-${i}`}
                        ref={(el) => (refs.current[i] = el)}
                        position={[Math.cos(angle) * radius, Math.sin(angle) * radius, 0]}
                    >
                        <ringGeometry args={[0.85, 1, 24]} />
                        <meshBasicMaterial color="#ff8844" transparent opacity={0.5} side={THREE.DoubleSide} depthWrite={false} />
                    </mesh>
                );
            })}
        </group>
    );
}

// ── Timeline Divergence (§228/§256) — branching possible futures ───────────────
function TimelineDivergence({ prediction }) {
    const refs = useRef([]);
    const branches = prediction && Array.isArray(prediction) ? prediction.slice(0, 3) : [];
    const baseAngle = (i) => (i / Math.max(1, branches.length)) * Math.PI * 2;
    // Hook before the empty guard — see ShockWaves.
    useFrame(({ clock }) => {
        refs.current.forEach((line, i) => {
            if (!line) return;
            line.material.opacity = 0.18 + (Math.sin(clock.elapsedTime * 1.2 + i * 1.5) + 1) * 0.1;
        });
    });
    if (branches.length === 0) return null;
    return (
        <group>
            {branches.map((b, i) => {
                const angle = baseAngle(i);
                const dir = [Math.cos(angle) * 2.2, Math.sin(angle) * 2.2, 0];
                const end = [dir[0] * 1.6, dir[1] * 1.6, -1.6];
                return (
                    <line
                        key={`div-${i}`}
                        ref={(el) => (refs.current[i] = el)}
                        points={[[0, 0, 0], [dir[0] * 0.8, dir[1] * 0.8, -0.4], end]}
                        color={['#00d2ff', '#ff66ff', '#00ff99'][i % 3]}
                        lineWidth={1}
                        transparent
                        opacity={0.3}
                    />
                );
            })}
        </group>
    );
}

// ── Scene (inside Canvas) ────────────────────────────────────────────────
function Scene({ data, controlsRef }) {
    const synoptic = data?.synoptic || {};
    // Predictive overlays are only grounded when the backend reports real
    // GNN ghost training (`gnn.trained`). In fallback/heuristic mode we keep
    // the 3D scene clean instead of drawing speculative ghosts/heatmaps.
    const gnn = synoptic.gnn || {};
    const predictiveMode = PREDICTIVE_OVERLAYS === true
        ? true
        : PREDICTIVE_OVERLAYS === false
            ? false
            : gnn.trained === true;
    // Prefer the live-trained GNN ghost predictions (Agents Swarm Visualize
    // §241) when present; fall back to the heuristic velocity forecast.
    const gnnGhosts = (Array.isArray(synoptic.prediction_g) && synoptic.prediction_g.length)
        ? synoptic.prediction_g.map((g, i) => ({ id: g.id ?? i, x: g.x, y: g.y, confidence: g.confidence }))
        : null;
    const predicted = synoptic.predicted || {};
    const predictionGhosts = gnnGhosts || Object.entries(predicted).map(([k, v]) => ({ id: k, value: v }));
    const anomalies = synoptic.anomalies || [];
    return (
        <>
            <Stars radius={120} depth={80} count={1200} factor={4} saturation={0} fade speed={0.4} />
            <ambientLight intensity={0.12} />
            <pointLight position={[10,  10,  10]} intensity={2.5} color="#ffffff" />
            <pointLight position={[-8, -8,  -8]} intensity={1.0} color="#0044ff" />
            <pointLight position={[0,   0,   8]} intensity={1.4} color="#ff0066" decay={2} />
            <pointLight position={[0,  -6,   0]} intensity={0.6} color="#9d6bff" decay={2} />

            <BrainCore trust={data?.trust || 0.5} valence={data?.valence || 0.0} />

            <PlanetarySystem planets={data?.planetary || []} />

            {/* Predictive intelligence overlays (Synoptics v2) — only when the
                backend confirms real GNN ghost training, not heuristic mode */}
            {predictiveMode && (
                <>
                    <GhostLayer predicted={predictionGhosts} />
                    <TimelineDivergence prediction={predictionGhosts} />
                </>
            )}
            {predictiveMode && (
                <>
                    <AnomalyHeatmap anomalies={anomalies} />
                    <ShockWaves anomalies={anomalies} />
                </>
            )}

            {/* Floating metric badges near core */}
            <MetricBadge position={[0,  2.2, 0]}  label="Trust"   value={`${((data?.trust || 0) * 100).toFixed(0)}%`} color="#9d6bff" />
            <MetricBadge position={[2.4, 0,  0]}  label="Valence" value={`${((data?.valence || 0) * 100).toFixed(0)}%`} color="#00d2ff" />
            <MetricBadge position={[-2.4,0,  0]}  label="Arousal" value={`${((data?.arousal || 0) * 100).toFixed(0)}%`} color="#ff6b9d" />

            <CameraFocus controlsRef={controlsRef} />

            <OrbitControls
                makeDefault
                ref={controlsRef}
                enablePan={true}
                enableZoom={true}
                zoomSpeed={1.2}
                enableRotate={true}
                autoRotate={true}
                autoRotateSpeed={0.35}
                minDistance={1}
                maxDistance={50}
            />
        </>
    );
}

// ── Synoptic Panel overlay ────────────────────────────────────────────────────────
// ── Radial Cognitive Map (doc §215) ─────────────────────────────────────────
// SVG concentric "star map" of domain activations + predicted ghost positions.
function RadialCognitiveMap({ synoptic }) {
    const domains = synoptic?.domains || {};
    const trend = synoptic?.trend || {};
    const entries = Object.entries(domains);
    if (!entries.length) return null;
    const size = 150, cx = size / 2, cy = size / 2, R = 52;
    return (
        <div style={{
            position: 'absolute', left: 12, top: 12, width: size, height: size,
            zIndex: 18, pointerEvents: 'none',
        }}>
            <svg width={size} height={size}>
                {[0.33, 0.66, 1.0].map((r) => (
                    <circle key={r} cx={cx} cy={cy} r={R * r} fill="none"
                        stroke="rgba(0,210,255,0.10)" strokeWidth="1" />
                ))}
                {[0, 45, 90, 135, 180, 225, 270, 315].map((deg) => {
                    const a = (deg * Math.PI) / 180;
                    return <line key={deg} x1={cx} y1={cy}
                        x2={cx + Math.cos(a) * R} y2={cy + Math.sin(a) * R}
                        stroke="rgba(0,210,255,0.06)" strokeWidth="1" />;
                })}
                {entries.map(([name, val], i) => {
                    const a = (i / entries.length) * Math.PI * 2 - Math.PI / 2;
                    const r = (0.25 + val * 0.75) * R;
                    const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
                    const vel = trend[name] || 0;
                    // ghost preview (predicted position)
                    const px = cx + Math.cos(a) * (r + vel * 30);
                    const py = cy + Math.sin(a) * (r + vel * 30);
                    return (
                        <g key={name}>
                            <circle cx={x} cy={y} r={5 + val * 6} fill="rgba(0,210,255,0.25)"
                                stroke="#00d2ff" strokeWidth="1" />
                            <circle cx={px} cy={py} r={3} fill="rgba(255,102,255,0.5)" />
                            <text x={x} y={y - 8} fontSize="7" fill="rgba(255,255,255,0.6)"
                                textAnchor="middle" fontFamily="monospace">{name.toUpperCase()}</text>
                        </g>
                    );
                })}
            </svg>
        </div>
    );
}

// ── Trend Bars (doc §215) ────────────────────────────────────────────────────
function TrendBars({ synoptic }) {
    const trend = synoptic?.trend || {};
    const entries = Object.entries(trend);
    if (!entries.length) return null;
    return (
        <div style={{
            position: 'absolute', left: 12, top: 175, width: 150,
            background: 'rgba(6,6,18,0.78)', backdropFilter: 'blur(10px)',
            border: '1px solid rgba(0,210,255,0.15)', borderRadius: 8, padding: 10,
            zIndex: 18, boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
        }}>
            <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace', letterSpacing: 1.5, marginBottom: 8 }}>
                DOMAIN VELOCITY
            </div>
            {entries.slice(0, 8).map(([name, v]) => {
                const pct = Math.min(100, Math.abs(v) * 400);
                const rising = v >= 0;
                return (
                    <div key={name} style={{ marginBottom: 5 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, fontFamily: 'monospace', color: 'rgba(255,255,255,0.6)', marginBottom: 2 }}>
                            <span>{name.toUpperCase()}</span>
                            <span style={{ color: rising ? '#00ff99' : '#ff2255' }}>{v >= 0 ? '▲' : '▼'}</span>
                        </div>
                        <div style={{ height: 3, background: 'rgba(255,255,255,0.06)', borderRadius: 2, overflow: 'hidden' }}>
                            <div style={{
                                width: `${pct}%`, height: '100%',
                                background: rising ? '#00ff99' : '#ff2255',
                                boxShadow: rising ? '0 0 6px #00ff99' : '0 0 6px #ff2255',
                                transition: 'width 0.4s ease',
                            }} />
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

// ── Synoptic Overlay UI ──────────────────────────────────────────────────────
function SynopticPanel({ synoptic }) {
    if (!synoptic) return null;
    
    return (
        <div style={{
            position: 'absolute', top: 12, right: 12,
            width: 260, background: 'rgba(6, 6, 18, 0.82)',
            backdropFilter: 'blur(12px)', border: '1px solid rgba(0, 210, 255, 0.3)',
            borderRadius: 8, padding: 18, zIndex: 20,
            display: 'flex', flexDirection: 'column', gap: 14,
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.6)'
        }}>
            <h3 style={{ margin: 0, color: 'white', fontSize: 13, fontFamily: 'monospace', letterSpacing: 1.5, borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: 8 }}>
                SYNOPTIC OBSERVABILITY
            </h3>
            
            <div>
                <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace', marginBottom: 4, letterSpacing: 1 }}>DOMINANT DOMAIN</div>
                <div style={{ fontSize: 18, color: '#00d2ff', fontFamily: 'monospace', fontWeight: 'bold' }}>
                    {(synoptic.dominant_domain || 'UNKNOWN').toUpperCase()}
                </div>
            </div>
            
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace', marginBottom: 4, letterSpacing: 1 }}>COHERENCE</div>
                    <div style={{ fontSize: 16, color: '#00ff99', fontFamily: 'monospace', textShadow: '0 0 8px rgba(0,255,153,0.4)' }}>
                        {((synoptic.coherence || 0) * 100).toFixed(1)}%
                    </div>
                </div>
                <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace', marginBottom: 4, letterSpacing: 1 }}>CONFLICT</div>
                    <div style={{ fontSize: 16, color: '#ff4444', fontFamily: 'monospace', textShadow: '0 0 8px rgba(255,68,68,0.4)' }}>
                        {((synoptic.conflict || 0) * 100).toFixed(1)}%
                    </div>
                </div>
            </div>
            
            <div style={{ marginTop: 4 }}>
                <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace', marginBottom: 8, letterSpacing: 1 }}>DOMAIN ACTIVATIONS</div>
                {Object.entries(synoptic.domains || {}).map(([key, val]) => (
                    <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                        <div style={{ width: 70, fontSize: 10, color: 'rgba(255,255,255,0.7)', fontFamily: 'monospace' }}>{key.toUpperCase()}</div>
                        <div style={{ flex: 1, height: 6, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
                            <div style={{ width: `${val * 100}%`, height: '100%', background: '#00d2ff', borderRadius: 3, transition: 'width 0.4s ease', boxShadow: '0 0 8px #00d2ff' }} />
                        </div>
                    </div>
                ))}
            </div>

            {(synoptic.cognition || synoptic.desktop || synoptic.causal) && (
                <div style={{ marginTop: 4, borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: 10 }}>
                    <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace', marginBottom: 8, letterSpacing: 1 }}>COGNITIVE LAYER</div>
                    {synoptic.cognition?.focus && (
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                            <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.6)', fontFamily: 'monospace' }}>FOCUS</span>
                            <span style={{ fontSize: 11, color: '#ff66ff', fontFamily: 'monospace' }}>{(synoptic.cognition.focus || '—').toUpperCase()}</span>
                        </div>
                    )}
                    {synoptic.desktop?.active_app && (
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                            <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.6)', fontFamily: 'monospace' }}>ACTIVE APP</span>
                            <span style={{ fontSize: 11, color: '#00ff99', fontFamily: 'monospace' }}>{synoptic.desktop.active_app.toUpperCase()}</span>
                        </div>
                    )}
                    {synoptic.causal?.stability != null && (
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.6)', fontFamily: 'monospace' }}>CAUSAL STABILITY</span>
                            <span style={{ fontSize: 11, color: '#00d2ff', fontFamily: 'monospace' }}>{((synoptic.causal.stability) * 100).toFixed(0)}%</span>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

// ── Global Metrics Strip ───────────────────────────────────────────────────────
function MetricsStrip({ data }) {
    // ── Real-time metrics, pulled straight from the live brain state ─────────
    // Every entry is read from actual backend values (data.trust / valence /
    // arousal come from the brain frame; the rest come from the synoptic
    // frame). Nothing here is fabricated or defaulted — a metric only renders
    // when the backend actually supplied a value.
    const synoptic = data?.synoptic || {};
    const health = synoptic.companion_health || {};
    const swarm = synoptic.swarm_stability || {};
    const drift = synoptic.narrative_drift || {};
    const causal = synoptic.causal || {};
    const pMetrics = synoptic.prediction_metrics || {};
    const features = synoptic.swarm_features || {};
    const cognition = synoptic.cognition || {};
    const gnn = synoptic.gnn || {};

    // Bar-type metrics (0..1): show a bar + percentage.
    const barMetrics = [
        { label: 'TRUST',     value: data?.trust,   color: '#9d6bff' },
        { label: 'VALENCE',   value: data?.valence, color: '#00d2ff' },
        { label: 'AROUSAL',   value: data?.arousal, color: '#ff6b9d' },
        { label: 'STABILITY', value: health.stability_index, color: '#00ff99' },
        { label: 'ATTACHMENT', value: health.attachment, color: '#ff8fa3' },
        { label: 'OVER-ATTACH RISK', value: health.over_attachment_risk, color: '#ffaa00' },
        { label: 'TRUST VOLATILITY', value: health.trust_volatility, color: '#ff6b6b' },
        { label: 'SWARM STABILITY', value: swarm.stability ?? swarm.stability_score, color: '#a78bfa' },
        { label: 'PRED ACCURACY', value: pMetrics.accuracy, color: '#34d399' },
        { label: 'CAUSAL STABILITY', value: causal.stability, color: '#22d3ee' },
    ].filter(m => m.value != null);

    // Value-type metrics: raw numeric readouts (not 0..1 bars).
    const valueMetrics = [];
    if (drift.score != null) valueMetrics.push({ label: 'NARRATIVE DRIFT', value: drift.score.toFixed(3), color: '#9d6bff' });
    if (gnn.train_loss != null) valueMetrics.push({ label: 'GNN TRAIN LOSS', value: gnn.train_loss.toFixed(4), color: '#00d2ff' });
    if (features.entropy != null) valueMetrics.push({ label: 'SWARM ENTROPY', value: features.entropy.toFixed(3), color: '#ff6b9d' });
    if (features.density != null) valueMetrics.push({ label: 'SWARM DENSITY', value: String(features.density), color: '#00ff99' });
    if (cognition.focus) valueMetrics.push({ label: 'COGNITIVE FOCUS', value: String(cognition.focus).toUpperCase(), color: '#7df9ff' });
    if (pMetrics.verified != null) valueMetrics.push({ label: 'PRED VERIFIED', value: `${pMetrics.verified}/${pMetrics.total ?? '—'}`, color: '#34d399' });

    return (
        <div style={{
            position: 'absolute', bottom: 0, left: 0, right: 0,
            display: 'flex', flexWrap: 'wrap',
            background: 'rgba(0,0,0,0.72)',
            borderTop: '1px solid rgba(255,255,255,0.06)',
            backdropFilter: 'blur(8px)', zIndex: 10,
            padding: '6px 8px', gap: '4px 0',
        }}>
            {barMetrics.map(m => (
                <div key={m.label} style={{
                    flex: '1 1 120px', padding: '6px 10px',
                    borderRight: '1px solid rgba(255,255,255,0.05)',
                    display: 'flex', flexDirection: 'column', gap: 3,
                }}>
                    <div style={{ fontSize: 9, letterSpacing: 1.5, color: 'rgba(255,255,255,0.35)', fontFamily: 'monospace' }}>
                        {m.label}
                    </div>
                    <div style={{ height: 3, background: 'rgba(255,255,255,0.07)', borderRadius: 2 }}>
                        <div style={{
                            width: `${Math.max(0, Math.min(1, m.value)) * 100}%`, height: '100%',
                            background: m.color,
                            boxShadow: `0 0 10px ${m.color}`,
                            borderRadius: 2, transition: 'width 0.4s ease'
                        }} />
                    </div>
                    <div style={{ fontSize: 13, color: '#fff', fontFamily: 'monospace', fontWeight: 700 }}>
                        {(m.value * 100).toFixed(0)}%
                    </div>
                </div>
            ))}
            {valueMetrics.map(m => (
                <div key={m.label} style={{
                    flex: '1 1 120px', padding: '6px 10px',
                    borderRight: '1px solid rgba(255,255,255,0.05)',
                    display: 'flex', flexDirection: 'column', gap: 3,
                }}>
                    <div style={{ fontSize: 9, letterSpacing: 1.5, color: 'rgba(255,255,255,0.35)', fontFamily: 'monospace' }}>
                        {m.label}
                    </div>
                    <div style={{ fontSize: 12, color: m.color, fontFamily: 'monospace', fontWeight: 700 }}>
                        {m.value}
                    </div>
                </div>
            ))}
        </div>
    );
}

// ── Live indicator dot ─────────────────────────────────────────────────────────
function LiveDot() {
    const [on, setOn] = useState(true);
    useEffect(() => {
        const t = setInterval(() => setOn(p => !p), 800);
        return () => clearInterval(t);
    }, []);
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{
                width: 8, height: 8, borderRadius: '50%',
                background: on ? '#00ff99' : 'transparent',
                border: '1.5px solid #00ff99',
                transition: 'background 0.2s'
            }} />
            <span style={{ color: '#00ff99', fontSize: 11, fontFamily: 'monospace', letterSpacing: 2 }}>LIVE</span>
        </div>
    );
}

const VIEW_PRESETS = [
    { id: 'reset', label: '⟳',  title: 'Reset view',     pos: [0, 0, 16],   look: [0, 0, 0] },
    { id: 'top',   label: '↑',  title: 'Top view',        pos: [0, 18, 0],   look: [0, 0, 0] },
    { id: 'front', label: '◎',  title: 'Front view',      pos: [0,  0, 18],  look: [0, 0, 0] },
    { id: 'side',  label: '→',  title: 'Side view',       pos: [18, 0, 0],   look: [0, 0, 0] },
    { id: 'diag',  label: '⤢',  title: 'Diagonal view',   pos: [12, 8, 12],  look: [0, 0, 0] },
];

// ── Goal / Hierarchy Panel (doc §201-207) ────────────────────────────────────
function GoalPanel({ synoptic }) {
    if (!synoptic?.goal && !synoptic?.plan) return null;
    const goal = synoptic.goal || {};
    const plan = synoptic.plan || {};
    const actions = plan.actions || [];
    return (
        <div style={{
            position: 'absolute', left: 12, bottom: 100, width: 230,
            background: 'rgba(6, 6, 18, 0.82)', backdropFilter: 'blur(12px)',
            border: '1px solid rgba(0, 255, 153, 0.25)', borderRadius: 8, padding: 14,
            zIndex: 20, display: 'flex', flexDirection: 'column', gap: 8,
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.6)',
        }}>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace', letterSpacing: 1.5 }}>
                ACTIVE GOAL
            </div>
            {goal.type && (
                <div style={{ fontSize: 14, color: '#00ff99', fontFamily: 'monospace', fontWeight: 'bold' }}>
                    {String(goal.type).toUpperCase()}
                </div>
            )}
            {goal.priority != null && (
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'monospace', color: 'rgba(255,255,255,0.6)' }}>
                    <span>PRIORITY</span><span style={{ color: '#00d2ff' }}>{goal.priority.toFixed(2)}</span>
                </div>
            )}
            {goal.progress != null && (
                <div>
                    <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.6)', fontFamily: 'monospace', marginBottom: 4 }}>PROGRESS</div>
                    <div style={{ height: 5, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
                        <div style={{ width: `${Math.min(100, goal.progress * 100)}%`, height: '100%', background: '#00ff99', boxShadow: '0 0 8px #00ff99', transition: 'width 0.4s ease' }} />
                    </div>
                </div>
            )}
            {actions.length > 0 && (
                <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: 8, marginTop: 2 }}>
                    <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace', marginBottom: 6 }}>PLAN</div>
                    {actions.slice(0, 6).map((a, i) => (
                        <div key={i} style={{ fontSize: 10, fontFamily: 'monospace', color: 'rgba(255,255,255,0.75)', display: 'flex', gap: 6, marginBottom: 3 }}>
                            <span style={{ color: '#00d2ff' }}>{i + 1}.</span>
                            <span>{String(a.action || a.type || a).slice(0, 40)}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

// ── Hierarchical Goal Tree (L1/L2/L3, doc §202-207) ───────────────────────────
function GoalTree({ synoptic }) {
    const hg = synoptic?.hierarchical_goals || [];
    const hp = synoptic?.hierarchical_plan || {};
    if (!hg.length && !hp.actions) return null;
    return (
        <div style={{
            position: 'absolute', left: 12, top: 12, width: 210,
            background: 'rgba(6, 6, 18, 0.82)', backdropFilter: 'blur(12px)',
            border: '1px solid rgba(255, 102, 255, 0.22)', borderRadius: 8, padding: 14,
            zIndex: 20, boxShadow: '0 8px 32px rgba(0, 0, 0, 0.6)',
        }}>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace', letterSpacing: 1.5, marginBottom: 8 }}>
                HIERARCHY (L1/L2/L3)
            </div>
            {hg.slice(0, 8).map((g, i) => {
                const colors = { 1: '#ff66ff', 2: '#00d2ff', 3: '#00ff99' };
                const color = colors[g.level] || '#ff66ff';
                return (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5 }}>
                        <span style={{ fontSize: 8, color, fontFamily: 'monospace', border: `1px solid ${color}`, borderRadius: 3, padding: '0 4px' }}>L{g.level}</span>
                        <span style={{ fontSize: 10, fontFamily: 'monospace', color: 'rgba(255,255,255,0.8)', flex: 1 }}>{String(g.type).slice(0, 28)}</span>
                        <span style={{ fontSize: 9, fontFamily: 'monospace', color: 'rgba(255,255,255,0.45)' }}>{g.priority?.toFixed?.(2)}</span>
                    </div>
                );
            })}
            {(hp.actions || []).length > 0 && (
                <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: 6, marginTop: 4 }}>
                    <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.45)', fontFamily: 'monospace', marginBottom: 4 }}>EXECUTING</div>
                    {(hp.actions || []).slice(0, 4).map((a, i) => (
                        <div key={i} style={{ fontSize: 9, fontFamily: 'monospace', color: '#00d2ff', marginBottom: 2 }}>
                            ▶ {String(a.action || a.type || a).slice(0, 34)}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

// ── Narrative Arc Panel (doc §175-177) ───────────────────────────────────────
function ArcPanel({ synoptic }) {
    const arcs = synoptic?.arcs || [];
    if (!arcs.length) return null;
    return (
        <div style={{
            position: 'absolute', right: 12, bottom: 100, width: 200,
            background: 'rgba(6, 6, 18, 0.82)', backdropFilter: 'blur(12px)',
            border: '1px solid rgba(255, 170, 0, 0.25)', borderRadius: 8, padding: 14,
            zIndex: 20, boxShadow: '0 8px 32px rgba(0, 0, 0, 0.6)',
        }}>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace', letterSpacing: 1.5, marginBottom: 8 }}>
                NARRATIVE ARCS
            </div>
            {arcs.slice(0, 6).map((a, i) => (
                <div key={i} style={{ marginBottom: 7 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'monospace', marginBottom: 3 }}>
                        <span style={{ color: '#ffaa00' }}>{String(a.theme).toUpperCase()}</span>
                        <span style={{ color: 'rgba(255,255,255,0.5)' }}>{a.strength.toFixed(2)}</span>
                    </div>
                    <div style={{ height: 4, background: 'rgba(255,255,255,0.07)', borderRadius: 2, overflow: 'hidden' }}>
                        <div style={{ width: `${Math.min(100, a.strength * 100)}%`, height: '100%', background: '#ffaa00', boxShadow: '0 0 6px #ffaa00', transition: 'width 0.4s ease' }} />
                    </div>
                </div>
            ))}
        </div>
    );
}

// ── Meta-Cognition Panel (doc §184-195) ──────────────────────────────────────
function MetaPanel({ synoptic }) {
    const stability = synoptic?.swarm_stability;
    const drift = synoptic?.narrative_drift;
    const trendMeta = synoptic?.trend_meta || {};
    if (!stability && !drift && !Object.keys(trendMeta).length) return null;
    const stabilityVal = stability?.stability_score ?? stability?.stability ?? null;
    return (
        <div style={{
            position: 'absolute', right: 12, top: 200, width: 210,
            background: 'rgba(6, 6, 18, 0.82)', backdropFilter: 'blur(12px)',
            border: '1px solid rgba(157, 107, 255, 0.25)', borderRadius: 8, padding: 14,
            zIndex: 20, boxShadow: '0 8px 32px rgba(0, 0, 0, 0.6)',
        }}>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace', letterSpacing: 1.5, marginBottom: 8 }}>
                META-COGNITION
            </div>
            {stabilityVal != null && (
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5, fontSize: 10, fontFamily: 'monospace' }}>
                    <span style={{ color: 'rgba(255,255,255,0.6)' }}>STABILITY</span>
                    <span style={{ color: stabilityVal > 0.6 ? '#00ff99' : '#ffaa00' }}>{(stabilityVal * 100).toFixed(0)}%</span>
                </div>
            )}
            {drift?.score != null && (
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5, fontSize: 10, fontFamily: 'monospace' }}>
                    <span style={{ color: 'rgba(255,255,255,0.6)' }}>NARRATIVE DRIFT</span>
                    <span style={{ color: '#9d6bff' }}>{drift.score.toFixed(3)}</span>
                </div>
            )}
            {trendMeta.direction && (
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'monospace' }}>
                    <span style={{ color: 'rgba(255,255,255,0.6)' }}>TREND</span>
                    <span style={{ color: trendMeta.direction === 'rising' ? '#00ff99' : (trendMeta.direction === 'falling' ? '#ff2255' : '#aaa') }}>
                        {String(trendMeta.direction).toUpperCase()} · v{trendMeta.velocity?.toFixed?.(3) ?? ''}
                    </span>
                </div>
            )}
        </div>
    );
}

// ── Task Plan / Executor Panel (AccessFIles §21-22) ─────────────────────────
function PlanPanel({ synoptic }) {
    const plan = synoptic?.task_plan;
    const exec = synoptic?.executor;
    if (!plan?.steps?.length) return null;
    return (
        <div style={{
            position: 'absolute', right: 12, top: 330, width: 210,
            background: 'rgba(6, 6, 18, 0.82)', backdropFilter: 'blur(12px)',
            border: '1px solid rgba(255, 0, 153, 0.22)', borderRadius: 8, padding: 14,
            zIndex: 20, boxShadow: '0 8px 32px rgba(0, 0, 0, 0.6)',
        }}>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace', letterSpacing: 1.5, marginBottom: 8 }}>
                TASK PLAN
            </div>
            <div style={{ fontSize: 11, color: '#ff0099', fontFamily: 'monospace', marginBottom: 8 }}>
                {String(plan.goal).toUpperCase()}
            </div>
            {plan.steps.slice(0, 5).map((s, i) => (
                <div key={i} style={{ fontSize: 9, fontFamily: 'monospace', color: 'rgba(255,255,255,0.75)', marginBottom: 3, display: 'flex', gap: 5 }}>
                    <span style={{ color: '#ff0099' }}>{i + 1}.</span>
                    <span>{String(s.action).toUpperCase()}{s.app ? ` → ${s.app}` : ''}{s.url ? ` → ${s.url}` : ''}</span>
                </div>
            ))}
            {exec?.executed > 0 && (
                <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: 6, marginTop: 6 }}>
                    <div style={{ fontSize: 9, color: '#00ff99', fontFamily: 'monospace' }}>
                        EXECUTED {exec.executed} · BLOCKED {exec.blocked || 0}
                    </div>
                </div>
            )}
        </div>
    );
}

// ── Smart Layer panel (Agents Swarm Visualize §241-247) ──────────────────────
// Renders the live-trained GNN state, ghost predictions, multi-agent intent,
// shockwave cascades, the prediction verification loop, and strategic reuse —
// all data already emitted in the synoptics frame but previously unrendered.
function SmartLayerPanel({ synoptic }) {
    const gnn = synoptic?.gnn;
    const predG = synoptic?.prediction_g;
    const intent = synoptic?.intent;
    const shockwave = synoptic?.shockwave;
    const pMetrics = synoptic?.prediction_metrics;
    const reused = synoptic?.reused_plan;
    const recovery = synoptic?.recovery;
    const strategic = synoptic?.strategic;
    const causal = synoptic?.causal_learned;
    const selectedAction = synoptic?.selected_action;
    const rlStyle = synoptic?.rl_style;
    const socialAction = synoptic?.social_action;
    const proactiveAlerts = synoptic?.proactive_alerts;
    const beliefState = synoptic?.belief_state;
    const swarmFeatures = synoptic?.swarm_features;
    const swarmMeta = synoptic?.swarm_meta;
    const society = synoptic?.society;
    const hasData = gnn || predG || intent || shockwave || pMetrics || reused || recovery || strategic || causal
        || selectedAction || rlStyle || socialAction || proactiveAlerts || beliefState || swarmFeatures || society;
    if (!hasData) return null;

    const row = (label, value, color) => (
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 9, fontFamily: 'monospace' }}>
            <span style={{ color: 'rgba(255,255,255,0.55)' }}>{label}</span>
            <span style={{ color: color || '#9d6bff', textAlign: 'right' }}>{value}</span>
        </div>
    );

    const avgConf = Array.isArray(predG) && predG.length
        ? (predG.reduce((s, p) => s + (p.confidence || 0), 0) / predG.length).toFixed(3) : null;
    const intentEntries = intent?.intents ? Object.entries(intent.intents) : [];
    const shockMax = Array.isArray(shockwave?.history) && shockwave.history.length
        ? Math.max(...shockwave.history) : null;

    return (
        <div style={{
            position: 'absolute', left: 250, top: 12, width: 218,
            background: 'rgba(6, 6, 18, 0.84)', backdropFilter: 'blur(12px)',
            border: '1px solid rgba(0, 210, 255, 0.22)', borderRadius: 8, padding: 14,
            zIndex: 21, boxShadow: '0 8px 32px rgba(0, 0, 0, 0.6)',
        }}>
            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.5)', fontFamily: 'monospace', letterSpacing: 1.5, marginBottom: 8 }}>
                SMART LAYER
            </div>

            {gnn && (
                <div style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6, marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: '#00ff99', fontFamily: 'monospace', marginBottom: 4 }}>
                        GNN {gnn.trained ? '● TRAINED' : '○ PENDING'}
                    </div>
                    {gnn.train_loss != null && row('TRAIN LOSS', gnn.train_loss.toFixed(4), '#00d2ff')}
                    {avgConf != null && row('GHOST CONF', avgConf, '#9d6bff')}
                    {predG && <div style={{ fontSize: 8, color: 'rgba(255,255,255,0.4)', fontFamily: 'monospace' }}>
                        {predG.length} agent ghosts predicted
                    </div>}
                </div>
            )}

            {intentEntries.length > 0 && (
                <div style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6, marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.45)', fontFamily: 'monospace', marginBottom: 4 }}>AGENT INTENT</div>
                    {intentEntries.slice(0, 4).map(([k, v]) => row(String(k).toUpperCase(), `${v} agents`, k === 'stable' ? '#00ff99' : (k === 'unstable' ? '#ff2255' : '#ffaa00')))}
                </div>
            )}

            {shockMax != null && (
                <div style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6, marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.45)', fontFamily: 'monospace', marginBottom: 4 }}>SHOCKWAVE</div>
                    {row('PEAK CASCADE', shockMax.toFixed(3), '#ff6b9d')}
                </div>
            )}

            {pMetrics && pMetrics.verified > 0 && (
                <div style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6, marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.45)', fontFamily: 'monospace', marginBottom: 4 }}>PREDICTION VERIFICATION</div>
                    {row('ACCURACY', `${(pMetrics.accuracy * 100).toFixed(0)}%`, pMetrics.accuracy >= 0.6 ? '#00ff99' : '#ffaa00')}
                    {row('VERIFIED', `${pMetrics.verified}/${pMetrics.total}`, '#00d2ff')}
                    {pMetrics.loop_closed && row('LOOP', 'CLOSED ✓', '#00ff99')}
                </div>
            )}

            {selectedAction && (
                <div style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6, marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: '#7df9ff', fontFamily: 'monospace', marginBottom: 4 }}>SELECTED ACTION</div>
                    <div style={{ fontSize: 9, fontFamily: 'monospace', color: 'rgba(255,255,255,0.85)', marginBottom: 3 }}>
                        {String(selectedAction.description || selectedAction.id || '').toUpperCase()}
                    </div>
                    {selectedAction.score != null && row('SCORE', selectedAction.score.toFixed(3), '#00d2ff')}
                    {selectedAction.confidence != null && row('CONF', selectedAction.confidence.toFixed(3), '#9d6bff')}
                </div>
            )}

            {rlStyle && (
                <div style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6, marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: '#ff66ff', fontFamily: 'monospace', marginBottom: 4 }}>RL STYLE</div>
                    {row('ACTIVE', String(rlStyle).toUpperCase(), '#ff66ff')}
                </div>
            )}

            {socialAction && (
                <div style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6, marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: '#ff9d4d', fontFamily: 'monospace', marginBottom: 4 }}>SOCIAL ACTION</div>
                    {socialAction.emotion_intensity != null && row('INTENSITY', socialAction.emotion_intensity.toFixed(2), '#ff9d4d')}
                    {socialAction.disclosure_level != null && row('DISCLOSURE', socialAction.disclosure_level.toFixed(2), '#ffb35c')}
                    {socialAction.initiative_level != null && row('INITIATIVE', socialAction.initiative_level.toFixed(2), '#ffcc80')}
                </div>
            )}

            {Array.isArray(proactiveAlerts) && proactiveAlerts.length > 0 && (
                <div style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6, marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: '#ff6b6b', fontFamily: 'monospace', marginBottom: 4 }}>PROACTIVE ALERTS</div>
                    {proactiveAlerts.slice(0, 3).map((a, i) => (
                        <div key={i} style={{ fontSize: 8, fontFamily: 'monospace', color: 'rgba(255,255,255,0.7)', marginBottom: 2 }}>
                            {String(a.domain || '').toUpperCase()} · {a.impact?.toFixed(2)} impact
                        </div>
                    ))}
                </div>
            )}

            {swarmFeatures && (
                <div style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6, marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: '#00d2ff', fontFamily: 'monospace', marginBottom: 4 }}>SWARM FEATURES</div>
                    {row('DENSITY', swarmFeatures.density ?? 0, '#00d2ff')}
                    {row('ENTROPY', swarmFeatures.entropy?.toFixed?.(3) ?? swarmFeatures.entropy ?? 0, '#9d6bff')}
                    {row('VELOCITY', swarmFeatures.avg_velocity ?? 0, '#ff6b9d')}
                    {swarmMeta?.model_version && row('MODEL', swarmMeta.model_version, 'rgba(255,255,255,0.5)')}
                    {swarmMeta?.latency_ms != null && row('LATENCY', `${swarmMeta.latency_ms}ms`, 'rgba(255,255,255,0.5)')}
                </div>
            )}

            {beliefState && Object.keys(beliefState).length > 0 && (
                <div style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6, marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.45)', fontFamily: 'monospace', marginBottom: 4 }}>BELIEFS</div>
                    {Object.entries(beliefState).slice(0, 4).map(([k, v]) => (
                        <div key={k} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2, fontSize: 8, fontFamily: 'monospace' }}>
                            <span style={{ color: 'rgba(255,255,255,0.55)' }}>{k.toUpperCase()}</span>
                            <span style={{ color: v > 0.6 ? '#00ff99' : v < 0.4 ? '#ff2255' : '#ffaa00' }}>{(v * 100).toFixed(0)}%</span>
                        </div>
                    ))}
                </div>
            )}

            {reused && (
                <div style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6, marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: '#ff0099', fontFamily: 'monospace', marginBottom: 4 }}>REUSED PLAN</div>
                    {row('GOAL', String(reused.goal).toUpperCase(), '#ff0099')}
                    {row('REWARD', reused.reward.toFixed(2), '#00d2ff')}
                    {(reused.steps || []).slice(0, 3).map((s, i) => (
                        <div key={i} style={{ fontSize: 8, fontFamily: 'monospace', color: 'rgba(255,255,255,0.6)', marginLeft: 6 }}>
                            {i + 1}. {String(s).slice(0, 30)}
                        </div>
                    ))}
                </div>
            )}

            {recovery && (
                <div style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6, marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: '#ffaa00', fontFamily: 'monospace', marginBottom: 4 }}>INSTANT RECOVERY</div>
                    {row(String(recovery.failure).toUpperCase(), '→', '#ffaa00')}
                    <div style={{ fontSize: 8, fontFamily: 'monospace', color: 'rgba(255,255,255,0.7)' }}>{String(recovery.solution).slice(0, 44)}</div>
                </div>
            )}

            {society && (
                <div style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6, marginBottom: 6 }}>
                    <div style={{ fontSize: 9, color: '#ffd54d', fontFamily: 'monospace', marginBottom: 4 }}>SOCIETY</div>
                    {row('LEADER', String(society.leader || 'none').toUpperCase(), '#ffd54d')}
                    {society.confidence != null && row('CONF', society.confidence.toFixed(3), '#ffb35c')}
                    {society.agreement != null && row('AGREEMENT', society.agreement.toFixed(3), '#ffcc80')}
                </div>
            )}

            {causal && (causal.edge_count || 0) > 0 && (
                <div>
                    <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.45)', fontFamily: 'monospace', marginBottom: 4 }}>CAUSAL LEARNED</div>
                    {(causal.edges || []).slice(0, 3).map((e, i) => (
                        <div key={i} style={{ fontSize: 8, fontFamily: 'monospace', color: 'rgba(255,255,255,0.65)', marginBottom: 2 }}>
                            <span style={{ color: '#00d2ff' }}>{e.source}</span> → <span style={{ color: '#ff66ff' }}>{e.target}</span>
                            <span style={{ color: 'rgba(255,255,255,0.35)' }}> ({e.confidence.toFixed(2)})</span>
                        </div>
                    ))}
                </div>
            )}

            {!gnn && !intentEntries.length && !shockMax && !reused && !recovery && !pMetrics && !causal
                && !selectedAction && !rlStyle && !socialAction && !proactiveAlerts?.length && !swarmFeatures && !beliefState && !society && (
                <div style={{ fontSize: 9, fontFamily: 'monospace', color: 'rgba(255,255,255,0.4)' }}>
                    {strategic ? `Strategic memory: ${strategic.plans?.plan_count || 0} plans cached` : 'Waiting for live smart-layer data…'}
                </div>
            )}
        </div>
    );
}

function ViewToolbar({ controlsRef }) {    const [active, setActive] = useState('reset');

    const jumpTo = (preset) => {
        setActive(preset.id);
        const ctrl = controlsRef.current;
        if (!ctrl) return;
        // Directly set camera + controls target for instant snap
        ctrl.object.position.set(...preset.pos);
        ctrl.target.set(...preset.look);
        ctrl.update();
    };

    return (
        <div style={{
            position: 'absolute', bottom: 60, right: 12, zIndex: 10,
            display: 'flex', flexDirection: 'column', gap: 4,
        }}>
            {VIEW_PRESETS.map(p => (
                <button
                    key={p.id}
                    title={p.title}
                    onClick={() => jumpTo(p)}
                    style={{
                        width: 32, height: 32,
                        background: active === p.id ? 'rgba(0,210,255,0.18)' : 'rgba(0,0,0,0.55)',
                        border: `1px solid ${active === p.id ? '#00d2ff' : 'rgba(255,255,255,0.12)'}`,
                        borderRadius: 6, color: active === p.id ? '#00d2ff' : 'rgba(255,255,255,0.5)',
                        fontSize: 14, cursor: 'pointer', lineHeight: '32px', textAlign: 'center',
                        backdropFilter: 'blur(6px)',
                        transition: 'all 0.2s',
                    }}
                >{p.label}</button>
            ))}
        </div>
    );
}

// ── Main export ────────────────────────────────────────────────────────────────────────────────

const scrubBtnStyle = (active) => ({
    background: active ? 'rgba(0,210,255,0.15)' : 'transparent',
    color: active ? '#00ff99' : 'rgba(255,255,255,0.4)',
    border: `1px solid ${active ? '#00ff99' : 'rgba(255,255,255,0.2)'}`,
    borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontSize: 9, fontFamily: 'monospace',
    letterSpacing: 1,
});

export default function BrainScene({ data }) {
    const controlsRef = useRef();
    const [history, setHistory] = useState([]);
    const [scrubIdx, setScrubIdx] = useState(-1);
    const lastTs = useRef(0);

    // Capture synoptic frames into a rolling history for the timeline scrubber
    useEffect(() => {
        const st = data?.synoptic?.timestamp;
        if (!st || st === lastTs.current) return;
        lastTs.current = st;
        setHistory(prev => {
            const next = [...prev.slice(-120), {
                ts: st,
                synoptic: { ...data.synoptic, timestamp: st },
                trust: data.trust, valence: data.valence, arousal: data.arousal,
            }];
            if (scrubIdx === -1 || scrubIdx === prev.length - 1) setScrubIdx(next.length - 1);
            return next;
        });
    }, [data]);

    if (!data) return null;

    // When scrubbing into the past, overlay the historical frame instead of live
    const live = history.length ? history[history.length - 1] : null;
    const frame = (scrubIdx >= 0 && history[scrubIdx]) ? history[scrubIdx] : live;
    const viewSynoptic = frame?.synoptic || data.synoptic;
    const isLive = scrubIdx === -1 || (live && scrubIdx === history.length - 1);

    const displayData = frame ? {
        ...data,
        synoptic: viewSynoptic,
        trust: frame.trust, valence: frame.valence, arousal: frame.arousal,
    } : data;

    return (
        <div style={{
            width: '100%', height: '100%', minHeight: 520,
            background: 'radial-gradient(ellipse at 50% 60%, #0d0d1e 0%, #050508 100%)',
            borderRadius: 12, overflow: 'hidden', position: 'relative',
            border: '1px solid rgba(0, 210, 255, 0.12)',
            boxShadow: '0 0 40px rgba(0, 100, 255, 0.08) inset',
        }}>
            {/* Header overlay */}
            <div style={{
                position: 'absolute', top: 12, left: 16, zIndex: 10,
                display: 'flex', alignItems: 'center', gap: 12
            }}>
                <LiveDot />
                <span style={{ color: 'rgba(255,255,255,0.3)', fontSize: 11, fontFamily: 'monospace' }}>
                    PLANETARY COGNITION SIMULATION
                </span>
            </div>

            {/* Render new Synoptic Panel here if data presents it */}
            <SynopticPanel synoptic={displayData.synoptic} />
            <RadialCognitiveMap synoptic={displayData.synoptic} />
            <TrendBars synoptic={displayData.synoptic} />
            <GoalTree synoptic={displayData.synoptic} />
            <GoalPanel synoptic={displayData.synoptic} />
            <ArcPanel synoptic={displayData.synoptic} />
            <MetaPanel synoptic={displayData.synoptic} />
            <PlanPanel synoptic={displayData.synoptic} />
            <SmartLayerPanel synoptic={displayData.synoptic} />

            {/* Timeline scrubber */}
            {history.length > 1 && (
                <div style={{
                    position: 'absolute', bottom: 52, left: '50%', transform: 'translateX(-50%)',
                    zIndex: 20, display: 'flex', alignItems: 'center', gap: 10,
                    background: 'rgba(6,6,18,0.8)', backdropFilter: 'blur(10px)',
                    border: '1px solid rgba(0,210,255,0.2)', borderRadius: 8,
                    padding: '6px 12px', fontFamily: 'monospace', fontSize: 9,
                    boxShadow: '0 6px 20px rgba(0,0,0,0.5)',
                }}>
                    <button onClick={() => setScrubIdx(history.length - 1)}
                        style={scrubBtnStyle(isLive)}>LIVE</button>
                    <input type="range" min={0} max={history.length - 1} value={scrubIdx}
                        onChange={e => setScrubIdx(Number(e.target.value))}
                        style={{ width: 220, accentColor: '#00d2ff' }} />
                    <span style={{ color: isLive ? '#00ff99' : '#ffaa00', minWidth: 60 }}>
                        {isLive ? 'LIVE' : `t-${history.length - 1 - scrubIdx}`}
                    </span>
                </div>
            )}

            {/* Controls hint */}
            <div style={{
                position: 'absolute', bottom: 60, left: '50%', transform: 'translateX(-50%)',
                zIndex: 10, display: 'flex', gap: 16, pointerEvents: 'none',
                fontFamily: 'monospace', fontSize: 9, letterSpacing: 1,
            }}>
                {[
                    ['DRAG', 'orbit'],
                    ['SCROLL', 'zoom'],
                    ['RIGHT-DRAG', 'pan'],
                ].map(([key, action]) => (
                    <span key={key} style={{ color: 'rgba(255,255,255,0.18)' }}>
                        <span style={{ color: 'rgba(255,255,255,0.45)' }}>{key}</span> {action}
                    </span>
                ))}
            </div>

            <MetricsStrip data={displayData} />

            {/* View-preset toolbar */}
            <ViewToolbar controlsRef={controlsRef} />

            {/** 3D Canvas */}
            <Canvas camera={{ position: [0, 0, 16], fov: 45 }} style={{ paddingBottom: 20 }}>
                <Scene
                    data={displayData}
                    controlsRef={controlsRef}
                />
            </Canvas>
        </div>
    );
}
