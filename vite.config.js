import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { getGevPlugins } from './vite.gev.config.js'
import { resolve } from 'path'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const gevConfig = getGevPlugins(mode);
  return {
  base: './',
  plugins: [react(), ...gevConfig.plugins],
  // Only VITE_-prefixed vars reach the renderer's import.meta.env by default.
  // Adding the BUILD_WARN_ prefix exposes BUILD_WARN_MAX_AGE_HOURS (set in the
  // shell when starting the dev server, or in a .env file) to client code in
  // BOTH dev and build — unlike a `define`, which Vite only applies at build
  // time for import.meta.env.* keys.
  // Note: any FUTURE BUILD_WARN_* var (or an accidental secret under that
  // prefix) also becomes client-visible in the bundle — keep the prefix narrow.
  envPrefix: ['VITE_', 'BUILD_WARN_'],
  build: {
    rollupOptions: {
      input: {
          main: resolve(__dirname, 'index.html'),
          gev: resolve(__dirname, 'src/gev/index.html')
        },
        output: {
        // Split the two giant vendor libraries (TensorFlow + three.js, together
        // ~1.5 MB min) out of the app chunk so they load in parallel and cache
        // independently, and so React stays in its own cached chunk. The heavy
        // libs are only pulled in by the lazy-loaded components in App.jsx
        // (OrbAvatar → three, VisionSystem/DialogueSystem → @tensorflow), so
        // the initial screen no longer waits on them.
        manualChunks(id) {
          if (!id.includes('node_modules')) return;
          if (
            id.includes('@tensorflow') ||
            id.includes('@mediapipe') ||
            id.includes('face-api.js')
          ) return 'tf';
          if (id.includes('/three') || id.includes('three-stdlib')) return 'three';
          if (
            id.includes('/react/') ||
            id.includes('react-dom') ||
            id.includes('react-is') ||
            id.includes('/scheduler/')
          ) return 'react';
          return 'vendor';
        },
      },
    },
    // tf (~1.1 MB) and three (~490 KB) are isolated vendor chunks that
    // legitimately exceed the default 500 kB threshold — that's the point of
    // splitting them out. Warn only at a realistic size; keep it in sync with
    // CHUNK_WARN_KB in scripts/dev.mjs (which feeds the GUI warnings banner).
    chunkSizeWarningLimit: 1500,
  },
  server: gevConfig.server,
  define: gevConfig.define
};
})
