import React, { lazy, Suspense } from 'react';
import useStore from './store';
import Overlay from './components/Overlay';
import BuildWarningsBanner from './components/BuildWarningsBanner';

// ── Lazy-loaded heavy modules ────────────────────────────────────────────────
// These pull in three.js (OrbAvatar, BrainScene), TensorFlow (VisionSystem,
// DialogueSystem via NeuralEngine) and the large admin/analytics graph. They
// are split into separate chunks (see manualChunks in vite.config.js) and only
// fetched when first rendered, so the initial screen doesn't wait on ~1.5 MB
// of vendor JS.
const AnalyticsDashboard = lazy(() => import('./components/AnalyticsDashboard'));
const VoiceSystem = lazy(() => import('./systems/VoiceSystem'));
const EmotionSystem = lazy(() => import('./systems/EmotionRecognitionSystem'));
const VisionSystem = lazy(() => import('./systems/VisionSystem'));
const DialogueSystem = lazy(() => import('./systems/DialogueSystem'));
const OrbAvatar = lazy(() => import('./components/OrbAvatar'));
const BrainMonitor = lazy(() => import('./components/BrainMonitor'));
const NewsPanel = lazy(() => import('./components/NewsPanel'));
const AutonomyPanel = lazy(() => import('./components/AutonomyPanel'));

// Minimal fallback while a lazy chunk streams in — keep the UI non-blocking.
const PanelSuspense = ({ children }) => (
  <Suspense fallback={null}>{children}</Suspense>
);

function App() {
  const started = useStore((state) => state.started);
  
  const searchParams = new URLSearchParams(window.location.search);
  const isAnalyticsRoute = searchParams.get('route') === 'analytics' || window.location.hash.includes('analytics');

  // If we are in the analytics popup window, ONLY render the analytics dashboard
  if (isAnalyticsRoute) {
    console.log('[App] Rendering isolated AnalyticsDashboard');
    return (
      <div className="analytics-popup" style={{ width: '100vw', height: '100vh', backgroundColor: '#0a0e1a', overflow: 'auto' }}>
        <PanelSuspense>
          <AnalyticsDashboard isPopup={true} />
        </PanelSuspense>
      </div>
    );
  }

  return (
    <div className="app-container" style={{ width: '100vw', height: '100vh', position: 'relative', overflow: 'hidden' }}>
      {/* Main UI overlay and Draggable Panels */}
      <Overlay />

      {/* Oversized-JS-chunk warnings from the last --prod build */}
      <BuildWarningsBanner />

      {/* Avatar / Orb visualization — where the avatar belongs (center stage) */}
      <PanelSuspense>
        {started && <OrbAvatar />}

        {/* Background analytics WebSocket listener */}
        <AnalyticsDashboard />

        {/* Non-visual systems */}
        {started && (
          <>
            <VoiceSystem />
            <EmotionSystem />
            <VisionSystem />
            <DialogueSystem />
          </>
        )}

        {/* Extra floating panels */}
        {started && (
          <>
            <BrainMonitor />
            <NewsPanel />
            <AutonomyPanel />
          </>
        )}
      </PanelSuspense>
    </div>
  );
}

export default App;
