/**
 * useSystemHealth — live system_health snapshot (WS frame + REST fallback).
 *
 * The server broadcasts a `system_health` frame every ~2 s on the shared
 * /ws/brain_metrics socket. If that socket is quiet (or the dashboard was
 * opened before the monitor started), poll GET /api/system/health instead.
 *
 * `stale` is honest: true only when both feeds have been silent long enough
 * that showing the last snapshot as "live" would be a lie.
 */

import { useEffect, useRef, useState } from 'react';
import { subscribeMetrics } from '../systems/metricsClient';
import { apiBase } from '../utils/apiHost';
import { personalFetch } from '../utils/deviceAuth';

const REST_URL = () => `${apiBase()}/api/system/health`;

export default function useSystemHealth() {
  const [snapshot, setSnapshot] = useState(null);
  const [source, setSource] = useState('offline'); // 'ws' | 'api' | 'offline' (label only)
  const [stale, setStale] = useState(true);        // true when both feeds are quiet
  const lastFrameAtRef = useRef(0);
  const inFlightRef = useRef(false);

  // Fallback fetch (stable across renders so a REFRESH button can call it).
  const fetchRestRef = useRef(null);

  useEffect(() => {
    let mounted = true;

    // Live path: server broadcasts a frame every ~2 s on the shared socket.
    const unsub = subscribeMetrics(
      (m) => m.type === 'system_health',
      (m) => {
        if (!mounted) return;
        lastFrameAtRef.current = Date.now();
        setStale(false);
        setSnapshot(m.data);
        setSource('ws');
      }
    );

    async function fetchRest() {
      if (inFlightRef.current || !mounted) return;
      inFlightRef.current = true;
      try {
        const res = await personalFetch(REST_URL());
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (mounted) {
          lastFrameAtRef.current = Date.now();
          setStale(false);
          setSnapshot(data);
          setSource('api');
        }
      } catch { /* offline — stay silent */ } finally {
        inFlightRef.current = false;
      }
    }
    fetchRestRef.current = fetchRest;

    fetchRest(); // immediate first paint
    const timer = setInterval(() => {
      const quietFor = Date.now() - lastFrameAtRef.current;
      if (quietFor > 6000) fetchRest();            // WS quiet → REST fallback
      setStale((prev) => {                          // both dead → honest offline
        const isStale = lastFrameAtRef.current === 0 || quietFor > 12000;
        return isStale === prev ? prev : isStale;
      });
    }, 3000);

    return () => { mounted = false; clearInterval(timer); unsub(); };
  }, []);

  return { snapshot, source, stale, refetch: () => fetchRestRef.current?.() };
}
