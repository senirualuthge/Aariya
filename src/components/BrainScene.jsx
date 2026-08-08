import React, { useRef, useMemo, useState, useEffect } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { OrbitControls, Line, Text, Stars, Html } from '@react-three/drei';
import * as THREE from 'three';

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
    
    // Physics targets for lerping
    const targetRadius = useRef(data.radius || 0.25);
    const targetSpeed = useRef(data.orbit_speed || 0.5);
    const targetGlow = useRef(data.glow || 0.5);
    
    useEffect(() => {
        targetRadius.current = data.radius || 0.25;
        targetSpeed.current = data.orbit_speed || 0.5;
        targetGlow.current = data.glow || 0.5;
    }, [data.radius, data.orbit_speed, data.glow]);

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

// ── Inner Scene (inside Canvas) ────────────────────────────────────────────────
function Scene({ data, controlsRef }) {
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
        </div>
    );
}

// ── Global Metrics Strip ───────────────────────────────────────────────────────
function MetricsStrip({ trust, valence, arousal }) {
    const metrics = [
        { label: 'TRUST',    value: trust,   color: '#9d6bff' },
        { label: 'VALENCE',  value: valence, color: '#00d2ff' },
        { label: 'AROUSAL',  value: arousal, color: '#ff6b9d' },
    ];

    return (
        <div style={{
            position: 'absolute', bottom: 0, left: 0, right: 0,
            display: 'flex', background: 'rgba(0,0,0,0.6)',
            borderTop: '1px solid rgba(255,255,255,0.06)',
            backdropFilter: 'blur(8px)', zIndex: 10
        }}>
            {metrics.map(m => (
                <div key={m.label} style={{
                    flex: 1, padding: '10px 16px',
                    borderRight: '1px solid rgba(255,255,255,0.05)',
                    display: 'flex', flexDirection: 'column', gap: 4
                }}>
                    <div style={{ fontSize: 9, letterSpacing: 2, color: 'rgba(255,255,255,0.3)', fontFamily: 'monospace' }}>
                        {m.label}
                    </div>
                    <div style={{ height: 3, background: 'rgba(255,255,255,0.07)', borderRadius: 2 }}>
                        <div style={{
                            width: `${(m.value || 0) * 100}%`, height: '100%',
                            background: m.color,
                            boxShadow: `0 0 10px ${m.color}`,
                            borderRadius: 2, transition: 'width 0.4s ease'
                        }} />
                    </div>
                    <div style={{ fontSize: 13, color: '#fff', fontFamily: 'monospace', fontWeight: 700 }}>{((m.value || 0) * 100).toFixed(0)}%</div>
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

function ViewToolbar({ controlsRef }) {
    const [active, setActive] = useState('reset');

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

export default function BrainScene({ data }) {
    const controlsRef = useRef();

    if (!data) return null;

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
            <SynopticPanel synoptic={data.synoptic} />

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

            <MetricsStrip trust={data.trust} valence={data.valence} arousal={data.arousal} />

            {/* View-preset toolbar */}
            <ViewToolbar controlsRef={controlsRef} />

            {/** 3D Canvas */}
            <Canvas camera={{ position: [0, 0, 16], fov: 45 }} style={{ paddingBottom: 20 }}>
                <Scene
                    data={data}
                    controlsRef={controlsRef}
                />
            </Canvas>
        </div>
    );
}
