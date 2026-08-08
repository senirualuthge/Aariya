import React, { useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Line } from '@react-three/drei';

function BrainNode({ position, color, scaleVal }) {
  const meshRef = useRef();

  useFrame(() => {
    if (meshRef.current) {
      // Gentle pulsing effect
      const time = Date.now() * 0.002;
      const pulsing = scaleVal + (Math.sin(time) * 0.05);
      meshRef.current.scale.set(pulsing, pulsing, pulsing);
    }
  });

  return (
    <mesh position={position} ref={meshRef}>
      <sphereGeometry args={[0.3, 32, 32]} />
      <meshStandardMaterial emissive={color} emissiveIntensity={0.8} />
    </mesh>
  );
}

function Synapse({ start, end, active }) {
  return (
    <Line
      points={[start, end]}
      color={active ? '#00ffff' : '#444444'}
      lineWidth={active ? 2 : 1}
    />
  );
}

export default function BrainScene({ metrics }) {
  // Use metrics to drive colors and sizes
  const trustScale = 1 + (metrics?.trust || 0.5) * 1.5;
  const valence = metrics?.valence || 0.0;
  
  // Map valence to color: positive=green, neutral=yellow, negative=red
  let coreColor = 'yellow';
  if (valence > 0.3) coreColor = 'green';
  if (valence < -0.3) coreColor = 'red';

  return (
    <div style={{ height: '400px', width: '100%', background: '#111', borderRadius: '12px' }}>
      <Canvas camera={{ position: [0, 0, 5] }}>
        <ambientLight intensity={0.5} />
        <pointLight position={[10, 10, 10]} />
        
        {/* Core Identity Node */}
        <BrainNode position={[0, 0, 0]} color={coreColor} scaleVal={trustScale} />

        {/* Emotion Agent Node */}
        <BrainNode position={[-2, 1, 0]} color={"hotpink"} scaleVal={1} />
        
        {/* Reasoning/Planner Node */}
        <BrainNode position={[2, 1, 0]} color={"cyan"} scaleVal={1} />
        
        {/* Critic Node */}
        <BrainNode position={[0, -2, 0]} color={"purple"} scaleVal={1} />

        {/* Synapse Lines joining the Swarm */}
        <Synapse start={[0, 0, 0]} end={[-2, 1, 0]} active={true} />
        <Synapse start={[0, 0, 0]} end={[2, 1, 0]} active={true} />
        <Synapse start={[0, 0, 0]} end={[0, -2, 0]} active={true} />

        <OrbitControls enableZoom={false} />
      </Canvas>
    </div>
  );
}
