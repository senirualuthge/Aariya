import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

const THEMES = [
  { name: 'cosmic', stops: ['#33e6ff', '#5b6bff', '#9b3fff', '#ff2f8f', '#ff3b3b', '#ff8a2e', '#33e6ff'] },
  { name: 'ember', stops: ['#ffe08a', '#ffb23c', '#ff7a3c', '#ff3c5c', '#c23cff', '#ffb23c', '#ffe08a'] },
  { name: 'mono', stops: ['#ffffff', '#b9bde0', '#7a7fb0', '#b9bde0', '#ffffff', '#dfe1ff', '#ffffff'] },
];

function hexToRgb01(hex) {
  const v = parseInt(hex.slice(1), 16);
  return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
}

function ramp(t, stops) {
  const segs = stops.length - 1;
  const scaled = Math.min(0.999999, Math.max(0, t)) * segs;
  const i = Math.floor(scaled);
  const localT = scaled - i;
  const c0 = stops[i], c1 = stops[i + 1];
  return [
    c0[0] + (c1[0] - c0[0]) * localT,
    c0[1] + (c1[1] - c0[1]) * localT,
    c0[2] + (c1[2] - c0[2]) * localT,
  ];
}

function noise3(x, y, z) {
  return (
    Math.sin(x * 1.0 + z * 0.7) * Math.cos(y * 1.3 - z * 0.4) +
    Math.sin(x * 2.1 - y * 1.7 + z * 1.1) * 0.5 +
    Math.sin(x * 4.3 + y * 3.9 - z * 2.2) * 0.25
  ) / 1.75;
}

function makeSpriteTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, 'rgba(255,255,255,1)');
  grad.addColorStop(0.35, 'rgba(255,255,255,0.75)');
  grad.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grad; g.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}

export default function OrbAvatar() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // ================= Audio =================
    let audioCtx = null, analyser = null, freqData = null, timeData = null, source = null;
    let micLive = false;
    const sens = 1.4;

    async function enableMic() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioCtx.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.75;
        freqData = new Uint8Array(analyser.frequencyBinCount);
        timeData = new Uint8Array(analyser.fftSize);
        source = audioCtx.createMediaStreamSource(stream);
        source.connect(analyser);
        micLive = true;
      } catch (err) {
        /* mic blocked — fall back to idle animation */
      }
    }
    enableMic();

    const lerp = (a, b, t) => a + (b - a) * t;
    let volume = 0, bandLow = 0, bandMid = 0, bandHigh = 0;

    function sampleAudio(t) {
      if (!micLive) {
        volume = lerp(volume, 0.10 + Math.sin(t * 0.6) * 0.04, 0.05);
        bandLow = lerp(bandLow, 0.14 + Math.sin(t * 0.4) * 0.05, 0.05);
        bandMid = lerp(bandMid, 0.11 + Math.sin(t * 0.5 + 1) * 0.05, 0.05);
        bandHigh = lerp(bandHigh, 0.09 + Math.sin(t * 0.7 + 2) * 0.05, 0.05);
        return;
      }
      const sens = 1.4;
      analyser.getByteFrequencyData(freqData);
      analyser.getByteTimeDomainData(timeData);
      const n = freqData.length;
      const lowEnd = Math.floor(n * 0.12), midEnd = Math.floor(n * 0.45);
      let low = 0, mid = 0, high = 0;
      for (let i = 0; i < lowEnd; i++) low += freqData[i];
      for (let i = lowEnd; i < midEnd; i++) mid += freqData[i];
      for (let i = midEnd; i < n; i++) high += freqData[i];
      low /= (lowEnd * 255); mid /= ((midEnd - lowEnd) * 255); high /= ((n - midEnd) * 255);
      let sumSq = 0;
      for (let i = 0; i < timeData.length; i++) { const v = (timeData[i] - 128) / 128; sumSq += v * v; }
      const rms = Math.sqrt(sumSq / timeData.length) * sens;
      volume = lerp(volume, Math.min(1, rms * 2.4), 0.35);
      bandLow = lerp(bandLow, Math.min(1, low * sens), 0.3);
      bandMid = lerp(bandMid, Math.min(1, mid * sens), 0.3);
      bandHigh = lerp(bandHigh, Math.min(1, high * sens), 0.3);
    }

    // ================= Three.js scene =================
    const scene = new THREE.Scene();
    let W = window.innerWidth, H = window.innerHeight;
    const camera = new THREE.PerspectiveCamera(45, W / H, 0.1, 100);
    camera.position.set(0, 0, 6.0);

    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(W, H);
    renderer.setClearColor(0x000000, 0);

    function onResize() {
      W = window.innerWidth; H = window.innerHeight;
      camera.aspect = W / H; camera.updateProjectionMatrix();
      renderer.setSize(W, H);
    }
    window.addEventListener('resize', onResize);

    const spriteTex = makeSpriteTexture();

    // Core glow sphere (solid, lit from within)
    const glowGeo = new THREE.SphereGeometry(1, 48, 48);
    const glowMat = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      uniforms: { uColorA: { value: new THREE.Color(0xffffff) }, uColorB: { value: new THREE.Color(0x7c5cff) }, uIntensity: { value: 1.0 } },
      vertexShader: `
        varying vec3 vNormal;
        void main(){
          vNormal = normalize(normalMatrix * normal);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }`,
      fragmentShader: `
        varying vec3 vNormal;
        uniform vec3 uColorA; uniform vec3 uColorB; uniform float uIntensity;
        void main(){
          float rim = pow(1.0 - abs(vNormal.z), 2.2);
          vec3 col = mix(uColorA, uColorB, rim);
          float alpha = (0.15 + rim * 0.55) * uIntensity;
          gl_FragColor = vec4(col, alpha);
        }`,
    });
    const glowSphere = new THREE.Mesh(glowGeo, glowMat);

    // Particle shell
    const N = 6800;
    const baseDir = new Float32Array(N * 3);
    const positions = new Float32Array(N * 3);
    const colors = new Float32Array(N * 3);
    const seed = new Float32Array(N);
    const sparkleFlag = new Uint8Array(N);

    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2;
      const rad = Math.sqrt(Math.max(0, 1 - y * y));
      const th = golden * i;
      const x = Math.cos(th) * rad;
      const z = Math.sin(th) * rad;
      baseDir[i * 3] = x; baseDir[i * 3 + 1] = y; baseDir[i * 3 + 2] = z;
      seed[i] = Math.random() * 1000;
      sparkleFlag[i] = Math.random() < 0.02 ? 1 : 0;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const group = new THREE.Group();
    group.add(glowSphere);
    scene.add(group);

    const haloMat = new THREE.PointsMaterial({
      size: 0.075, map: spriteTex, vertexColors: true, transparent: true,
      opacity: 0.32, blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
    });
    const coreMat = new THREE.PointsMaterial({
      size: 0.032, map: spriteTex, vertexColors: true, transparent: true,
      opacity: 0.95, blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
    });
    group.add(new THREE.Points(geometry, haloMat));
    group.add(new THREE.Points(geometry, coreMat));

    const baseRadius = 1.55;
    const HALO_OPACITY = 0.32, CORE_OPACITY = 0.95;

    // Drag to rotate
    let rotY = 0.2, rotX = 0.08;
    let dragging = false, lastX = 0, lastY = 0;
    function onPointerDown(e) { dragging = true; lastX = e.clientX; lastY = e.clientY; }
    function onPointerUp() { dragging = false; }
    function onPointerMove(e) {
      if (!dragging) return;
      rotY += (e.clientX - lastX) * 0.005;
      rotX += (e.clientY - lastY) * 0.003;
      rotX = Math.max(-0.9, Math.min(0.9, rotX));
      lastX = e.clientX; lastY = e.clientY;
    }
    canvas.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointermove', onPointerMove);

    function updateParticles(t, dt, introEase) {
      const theme = THEMES[0];
      const stops = theme.stops.map(hexToRgb01);
      const turbAmp = 0.10 + volume * 0.45 + bandHigh * 0.28;
      const turbFreq = 1.4 + bandMid * 1.0;
      const timeScale = t * 0.14 + volume * 0.35;

      for (let i = 0; i < N; i++) {
        const ix = i * 3;
        const dx = baseDir[ix], dy = baseDir[ix + 1], dz = baseDir[ix + 2];
        const n = noise3(dx * turbFreq + timeScale, dy * turbFreq - timeScale * 0.7, dz * turbFreq + seed[i] * 0.001);
        const outward = 1 + n * turbAmp;
        const r = baseRadius * outward * (0.4 + 0.6 * introEase);
        positions[ix] = dx * r;
        positions[ix + 1] = dy * r;
        positions[ix + 2] = dz * r;

        let tt = (Math.atan2(dx, dy) / (Math.PI * 2) + 1) % 1;
        tt = (tt + n * 0.05 + 1) % 1;
        const [cr, cg, cb] = ramp(tt, stops);

        let bright = 0.42 + Math.max(0, n) * 0.9 + volume * 0.42;
        if (sparkleFlag[i]) bright += 0.4 + 0.4 * Math.sin(t * 3 + seed[i]);
        const mix = Math.min(1, Math.max(0, bright - 0.5)) * 0.62;

        colors[ix] = cr + (1 - cr) * mix;
        colors[ix + 1] = cg + (1 - cg) * mix;
        colors[ix + 2] = cb + (1 - cb) * mix;
      }
      geometry.attributes.position.needsUpdate = true;
      geometry.attributes.color.needsUpdate = true;

      const autoSpeed = 0.05 + volume * 0.15;
      if (!dragging) rotY += autoSpeed * dt;
      group.rotation.y = rotY;
      group.rotation.x = rotX;

      const pulse = baseRadius * 0.6 * (1 + volume * 0.35) * introEase;
      glowSphere.scale.setScalar(pulse);
      const [gr, gg, gb] = ramp((t * 0.03) % 1, stops);
      glowMat.uniforms.uColorB.value.setRGB(gr, gg, gb);
      glowMat.uniforms.uIntensity.value = (0.6 + volume * 0.8) * introEase;

      const breathe = 1 + Math.sin(t * 1.1) * 0.01 + volume * 0.03;
      group.scale.setScalar(breathe);
    }

    const clock = new THREE.Clock();
    const INTRO_DURATION = 1.6;
    let rafId = null;
    function animate() {
      rafId = requestAnimationFrame(animate);
      const dt = clock.getDelta();
      const t = clock.elapsedTime;
      const introEase = 1 - Math.pow(1 - Math.min(1, t / INTRO_DURATION), 3);

      sampleAudio(t);
      updateParticles(t, dt, introEase);

      haloMat.opacity = HALO_OPACITY * Math.min(1, t / 1.0);
      coreMat.opacity = CORE_OPACITY * Math.min(1, t / 1.0);

      renderer.render(scene, camera);
    }
    animate();

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener('resize', onResize);
      canvas.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointerup', onPointerUp);
      window.removeEventListener('pointermove', onPointerMove);
      if (source) source.disconnect();
      if (audioCtx && audioCtx.state !== 'closed') audioCtx.close();
      geometry.dispose();
      glowGeo.dispose();
      glowMat.dispose();
      haloMat.dispose();
      coreMat.dispose();
      spriteTex.dispose();
      renderer.dispose();
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      id="orb-stage"
      style={{
        position: 'fixed', inset: 0, display: 'block',
        cursor: 'grab', zIndex: 1, pointerEvents: 'auto',
      }}
    />
  );
}
