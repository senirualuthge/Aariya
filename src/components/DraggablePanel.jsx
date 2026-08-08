import React, { useState, useRef, useEffect, useCallback } from 'react';

// ── Shared panel state cache ──────────────────────────────────────────────────
// All DraggablePanel instances share this cache so they don't fight over IPC.
// It is populated once on first mount, then kept in sync locally.
let panelStateCache = null;          // null = not yet loaded
let cacheLoadPromise = null;         // deduplicate concurrent loads
const cacheListeners = new Set();    // panels waiting for the load

async function loadPanelStateCache() {
  if (panelStateCache !== null) return panelStateCache;
  if (cacheLoadPromise) return cacheLoadPromise;

  cacheLoadPromise = (async () => {
    try {
      console.log('[DraggablePanel] Starting cache load...');
      if (window.electronAPI?.loadPanelState) {
        const data = await window.electronAPI.loadPanelState();
        console.log('[DraggablePanel] Got IPC data keys:', data ? Object.keys(data) : 'null');
        panelStateCache = data || {};
      } else {
        console.warn('[DraggablePanel] Fallback: window.electronAPI missing! Loading from localStorage');
        panelStateCache = {};
        for (let i = 0; i < localStorage.length; i++) {
          const k = localStorage.key(i);
          if (k?.startsWith('panel_')) {
            try { panelStateCache[k] = JSON.parse(localStorage.getItem(k)); } catch { /* skip */ }
          }
        }
      }
    } catch (err) {
      console.error('[DraggablePanel] Failed to load panel state:', err);
      panelStateCache = {};
    }
    // Notify all waiting panels
    cacheListeners.forEach(fn => fn());
    cacheListeners.clear();
    return panelStateCache;
  })();

  return cacheLoadPromise;
}

// Debounced flush — batches rapid drags into one disk write
let saveTimer = null;
function scheduleSave() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    if (!panelStateCache) return;
    try {
      if (window.electronAPI?.savePanelState) {
        // Synchronous write on the main-process side via IPC invoke
        window.electronAPI.savePanelState(panelStateCache);
      } else {
        // localStorage fallback
        Object.entries(panelStateCache).forEach(([k, v]) => {
          localStorage.setItem(k, JSON.stringify(v));
        });
      }
    } catch (err) {
      console.error('[DraggablePanel] Failed to save panel state:', err);
    }
  }, 150); // 150ms debounce — fast enough, batches rapid drags
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function DraggablePanel({ id, defaultPosition, defaultSize, children, style, className }) {
  const posKey  = `panel_pos_${id}`;
  const sizeKey = `panel_size_${id}`;

  // Start with the default; swap in the persisted value once cache is ready
  const [position, setPosition] = useState(() => {
    if (panelStateCache?.[posKey]) return panelStateCache[posKey];
    return defaultPosition || { x: 0, y: 0 };
  });

  const [size, setSize] = useState(() => {
    if (panelStateCache?.[sizeKey]) return panelStateCache[sizeKey];
    return defaultSize || {};
  });

  const [cacheReady, setCacheReady] = useState(panelStateCache !== null);

  const [isDragging, setIsDragging]   = useState(false);
  const [isResizing, setIsResizing]   = useState(false);

  const dragOffset  = useRef({ x: 0, y: 0 });
  const resizeStart = useRef({ x: 0, y: 0, width: 0, height: 0 });
  const panelRef    = useRef(null);

  // On first mount: load cache (or wait for it) then apply saved position
  useEffect(() => {
    // Also apply directly to ref just in case React state batching gets lost
    const applyToRef = (pos, sz) => {
      if (panelRef.current) {
        if (pos) {
          panelRef.current.style.left = `${pos.x}px`;
          panelRef.current.style.top = `${pos.y}px`;
        }
        if (sz) {
          if (sz.width) panelRef.current.style.width = sz.width;
          if (sz.height) panelRef.current.style.height = sz.height;
        }
      }
    };

    if (panelStateCache !== null) {
      console.log(`[DraggablePanel - ${id}] Cache already present on mount. Applying:`, panelStateCache[posKey]);
      // Cache already loaded — apply immediately
      if (panelStateCache[posKey]) {
        setPosition(panelStateCache[posKey]);
        applyToRef(panelStateCache[posKey], null);
      }
      if (panelStateCache[sizeKey]) {
        setSize(panelStateCache[sizeKey]);
        applyToRef(null, panelStateCache[sizeKey]);
      }
      setCacheReady(true);
      return;
    }

    // Register a listener to apply values once load completes
    const onCacheReady = () => {
      console.log(`[DraggablePanel - ${id}] Cache load completed! Applying cached values for ${id}:`, panelStateCache[posKey] || 'NONE (default)');
      if (panelStateCache[posKey]) {
        setPosition(panelStateCache[posKey]);
        applyToRef(panelStateCache[posKey], null);
      }
      if (panelStateCache[sizeKey]) {
        setSize(panelStateCache[sizeKey]);
        applyToRef(null, panelStateCache[sizeKey]);
      }
      setCacheReady(true);
    };
    cacheListeners.add(onCacheReady);

    loadPanelStateCache();

    return () => cacheListeners.delete(onCacheReady);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Save initial default so it's available next launch (only if nothing saved yet)
  useEffect(() => {
    if (!cacheReady) return;
    // Using an arrow function to ensure we capture the current position from the useState
    setPosition(currentPos => {
      let madeChanges = false;
      if (!panelStateCache[posKey]) {
        console.log(`[DraggablePanel - ${id}] Writing initial default position:`, currentPos);
        panelStateCache[posKey] = currentPos;
        madeChanges = true;
      }
      
      // Since setting size uses a separate state, we just pull the current ref's size if missing
      if (!panelStateCache[sizeKey] && defaultSize) {
        console.log(`[DraggablePanel - ${id}] Writing initial default size:`, defaultSize);
        panelStateCache[sizeKey] = defaultSize;
        madeChanges = true;
      }

      if (madeChanges) scheduleSave();
      
      return currentPos;
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cacheReady, id]);

  // ── Dragging ────────────────────────────────────────────────────────────────
  const handleMouseDown = useCallback((e) => {
    const hasDragHandle = panelRef.current?.querySelector('.drag-handle');
    if (hasDragHandle && !e.target.closest('.drag-handle')) return;
    if (!hasDragHandle) {
      if (['INPUT', 'BUTTON', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
      if (e.target.closest('button') || e.target.closest('.resize-handle')) return;
    }

    setIsDragging(true);
    const rect = panelRef.current.getBoundingClientRect();
    dragOffset.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    if (!e.target.closest('input')) e.preventDefault();
  }, []);

  const handleMouseMove = useCallback((e) => {
    if (!isDragging) return;
    const newPos = { x: e.clientX - dragOffset.current.x, y: e.clientY - dragOffset.current.y };
    setPosition(newPos);
    if (panelStateCache) { panelStateCache[posKey] = newPos; scheduleSave(); }
  }, [isDragging, posKey]);

  const handleMouseUp = useCallback(() => setIsDragging(false), []);

  useEffect(() => {
    if (!isDragging) return;
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, handleMouseMove, handleMouseUp]);

  // ── Resizing ────────────────────────────────────────────────────────────────
  const startResize = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsResizing(true);
    const rect = panelRef.current.getBoundingClientRect();
    resizeStart.current = { x: e.clientX, y: e.clientY, width: rect.width, height: rect.height };
  }, []);

  const handleResizeMove = useCallback((e) => {
    if (!isResizing) return;
    const newWidth  = Math.max(150, resizeStart.current.width  + (e.clientX - resizeStart.current.x));
    const newHeight = Math.max(50,  resizeStart.current.height + (e.clientY - resizeStart.current.y));
    const sizeObj = { width: `${newWidth}px`, height: `${newHeight}px` };
    setSize(sizeObj);
    if (panelStateCache) { panelStateCache[sizeKey] = sizeObj; scheduleSave(); }
  }, [isResizing, sizeKey]);

  const handleResizeEnd = useCallback(() => setIsResizing(false), []);

  useEffect(() => {
    if (!isResizing) return;
    window.addEventListener('mousemove', handleResizeMove);
    window.addEventListener('mouseup', handleResizeEnd);
    return () => {
      window.removeEventListener('mousemove', handleResizeMove);
      window.removeEventListener('mouseup', handleResizeEnd);
    };
  }, [isResizing, handleResizeMove, handleResizeEnd]);

  return (
    <div
      ref={panelRef}
      className={className}
      onMouseDown={handleMouseDown}
      style={{
        ...style,
        position: 'absolute',
        left: position.x,
        top: position.y,
        width: size?.width,
        height: size?.height,
        userSelect: 'none',
        zIndex: isDragging || isResizing ? 100 : style?.zIndex || 10,
        pointerEvents: 'auto',
        overflow: 'auto',
      }}
    >
      {children}

      {/* Resize Handle */}
      <div
        className="resize-handle"
        onMouseDown={startResize}
        style={{
          position: 'absolute',
          bottom: '0',
          right: '0',
          width: '16px',
          height: '16px',
          cursor: 'nwse-resize',
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'flex-end',
          padding: '3px',
          opacity: 0.5,
          zIndex: 1000
        }}
      >
        <svg width="10" height="10" viewBox="0 0 10 10">
          <line x1="6" y1="10" x2="10" y2="6" stroke="rgba(255,255,255,0.7)" strokeWidth="1.5" />
          <line x1="2" y1="10" x2="10" y2="2" stroke="rgba(255,255,255,0.7)" strokeWidth="1.5" />
        </svg>
      </div>
    </div>
  );
}
