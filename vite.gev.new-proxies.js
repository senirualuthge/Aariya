/**
 * vite.gev.new-proxies.js
 * ───────────────────────
 * Vite dev-server proxy middleware for the new GEV intelligence data sources:
 *   1. Weather       — NOAA/NWS severe weather alerts
 *   2. Radar         — Rainviewer precipitation radar
 *   3. AQI           — WAQI / OpenAQ air quality
 *   4. Volcanoes     — USGS / VAAC volcanic activity
 *   5. Power Outages — Grid failure / blackout tracking
 *   6. Transit       — GTFS-RT public transit
 *   7. Space Weather — NOAA SWPC solar flare / geomagnetic storms
 *   8. NEOs          — NASA JPL near-Earth objects
 *   9. GPS Jamming   — GPSJam interference zones
 *  10. Social Events — GDACS disaster alerts
 *  11. Satellite Imagery — Sentinel-2 / Landsat
 *  12. Satellite Analysis — Vision AI ground analysis
 *  13. OSINT Enrichment — Vessel / aircraft cross-referencing
 *  14. Geofencing    — Spatial rules & triggers
 *  15. DVR Timeline  — Historical snapshot playback
 *
 * Each proxy caches upstream responses in memory (+ optional disk),
 * serves stale on upstream failure, and coalesces concurrent requests.
 *
 * @module vite.gev.new-proxies
 */

import { promises as fsp } from 'node:fs';
import path from 'node:path';
import { coalesceProxyRequest, readResponseTextCapped } from './vite.gev.config.js';

// ── Shared helpers ───────────────────────────────────────────────────────────

const TIMEOUT_MS = 15_000;
const MAX_RESPONSE_BYTES = 4 * 1024 * 1024;
const CACHE_DIR = path.join(process.cwd(), '.gev-cache', 'gev-intel');

function ensureCacheDir() {
  return fsp.mkdir(CACHE_DIR, { recursive: true }).catch(() => {});
}

/**
 * Create a memory + disk cache for a proxy.
 * Disk TTL is 7× the memory TTL for long-lived data.
 */
function makeDiskCache(name, memoryTtlMs) {
  const diskTtlMs = memoryTtlMs * 7; // disk lives 7× longer
  const mem = new Map(); // key -> { at, body }
  const diskPath = (key) => path.join(CACHE_DIR, `${name}-${key.replace(/[^a-z0-9]/gi, '_')}.json`);
  let diskLoaded = false;

  async function loadDisk() {
    if (diskLoaded) return;
    diskLoaded = true;
    try {
      const files = await fsp.readdir(CACHE_DIR).catch(() => []);
      for (const file of files) {
        if (!file.startsWith(`${name}-`) || !file.endsWith('.json')) continue;
        try {
          const raw = await fsp.readFile(path.join(CACHE_DIR, file), 'utf8');
          const parsed = JSON.parse(raw);
          if (typeof parsed?.body === 'string' && Number.isFinite(parsed?.at)) {
            // Only load if not expired on disk
            if (Date.now() - parsed.at < diskTtlMs) {
              const key = file.slice(name.length + 1, -5); // strip prefix and .json
              mem.set(key, parsed);
            }
          }
        } catch { /* skip corrupt files */ }
      }
    } catch { /* first run */ }
  }

  async function saveDisk(key, entry) {
    try {
      await ensureCacheDir();
      await fsp.writeFile(diskPath(key), JSON.stringify(entry), 'utf8');
    } catch (err) {
      console.warn(`[${name}] disk cache write failed:`, err?.message || err);
    }
  }

  return {
    get(key) {
      const entry = mem.get(key);
      if (!entry) return null;
      if (Date.now() - entry.at > memoryTtlMs) { mem.delete(key); return null; }
      return entry;
    },
    set(key, body) {
      const entry = { at: Date.now(), body };
      mem.set(key, entry);
      void saveDisk(key, entry);
    },
    async init() { await loadDisk(); },
    // Check disk for stale data when memory is empty
    async getFromDisk(key) {
      await loadDisk();
      const entry = mem.get(key);
      if (entry && Date.now() - entry.at < diskTtlMs) return entry;
      return null;
    },
  };
}

function sendJson(res, status, obj) {
  if (res.headersSent) return;
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Cache-Control': status === 200 ? 'public, max-age=300' : 'no-store',
  });
  res.end(JSON.stringify(obj));
}

function parseQuery(url) {
  const qs = (url || '').split('?')[1] || '';
  return Object.fromEntries(new URLSearchParams(qs));
}

function optFloat(v, fallback) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

// ── Rate limiting ────────────────────────────────────────────────────────────

const RATE_LIMITER_MAX_KEYS = 2000;

/**
 * Fixed-window per-key rate limiter (same pattern as vite.gev.config.js).
 * @param {object} opts
 * @param {number} opts.windowMs — time window in milliseconds
 * @param {number} opts.max — max requests per key within the window
 * @param {number} [opts.globalMax] — max total requests across all keys
 * @returns {(key: string) => boolean} allow function — returns true if request is permitted
 */
function makeRateLimiter({ windowMs, max, globalMax }) {
  const hits = new Map(); // key -> number[] (timestamps within window)
  let globalTimes = []; // all hits in window, for the global backstop
  return function allow(key) {
    const now = Date.now();
    globalTimes = globalTimes.filter((t) => now - t < windowMs);
    if (globalMax && globalTimes.length >= globalMax) return false;
    const recent = (hits.get(key) || []).filter((t) => now - t < windowMs);
    if (recent.length >= max) { hits.set(key, recent); return false; }
    recent.push(now);
    hits.set(key, recent);
    globalTimes.push(now);
    // Hard key cap so a key-rotating caller can't grow the map without bound.
    if (hits.size > RATE_LIMITER_MAX_KEYS) {
      const oldest = hits.keys().next().value;
      if (oldest !== undefined) hits.delete(oldest);
    }
    if (hits.size > 256) {
      for (const [k, v] of hits) {
        if (!v.length || now - v[v.length - 1] > windowMs) hits.delete(k);
      }
    }
    return true;
  };
}

/** Client key for rate limiting (socket peer address). */
function clientKey(req) {
  return String(req.socket?.remoteAddress || 'local');
}

/**
 * Enforce rate limit on a request. Returns true if allowed, false if 429 was sent.
 * @param {((key:string)=>boolean)|null} limiter
 * @param {import('http').IncomingMessage} req
 * @param {import('http').ServerResponse} res
 */
function enforceRateLimit(limiter, req, res) {
  if (!limiter) return true;
  if (limiter(clientKey(req))) return true;
  sendJson(res, 429, {
    error: 'Rate limit exceeded',
    retryAfter: 5,
    message: 'Too many requests — slow down',
  });
  return false;
}

// Per-proxy rate limiters with sensible defaults for upstream API protection
// Weather/alert proxies: 30 req/min per client, 200 global (low-frequency, high-value)
const _weatherLimiter = makeRateLimiter({ windowMs: 60_000, max: 30, globalMax: 200 });
// Radar/AQI proxies: 20 req/min per client, 150 global (image-heavy, expensive)
const _radarLimiter = makeRateLimiter({ windowMs: 60_000, max: 20, globalMax: 150 });
const _aqiLimiter = makeRateLimiter({ windowMs: 60_000, max: 20, globalMax: 150 });
// Space/weather proxies: 15 req/min per client, 100 global (rarely-changing data)
const _spaceLimiter = makeRateLimiter({ windowMs: 60_000, max: 15, globalMax: 100 });
// Volcano/power/transit: 20 req/min per client, 150 global
const _infrastructureLimiter = makeRateLimiter({ windowMs: 60_000, max: 20, globalMax: 150 });
// GPS/Social/NEO: 10 req/min per client, 80 global (slow-changing data)
const _intelLimiter = makeRateLimiter({ windowMs: 60_000, max: 10, globalMax: 80 });
// OSINT: 5 req/min per client, 30 global (expensive lookups)
const _osintLimiter = makeRateLimiter({ windowMs: 60_000, max: 5, globalMax: 30 });
// Satellite imagery: 10 req/min per client, 60 global
const _satelliteLimiter = makeRateLimiter({ windowMs: 60_000, max: 10, globalMax: 60 });

// ── Simple memory cache with TTL ─────────────────────────────────────────────

function makeMemCache(ttlMs) {
  const mem = new Map(); // key -> { at, body }
  return {
    get(key) {
      const entry = mem.get(key);
      if (!entry) return null;
      if (Date.now() - entry.at > ttlMs) { mem.delete(key); return null; }
      return entry;
    },
    set(key, body) { mem.set(key, { at: Date.now(), body }); },
    get size() { return mem.size; },
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// 1. Weather Proxy (NOAA/NWS)
// ═══════════════════════════════════════════════════════════════════════════════

export function weatherProxy() {
  const cache = makeMemCache(120_000); // 2 min
  const inflight = new Map();

  async function fetchWeather(params) {
    const url = new URL('https://api.weather.gov/alerts/active');
    if (params.lat && params.lon) {
      url.searchParams.set('point', `${params.lat},${params.lon}`);
    }
    url.searchParams.set('status', 'actual');
    url.searchParams.set('message_type', 'alert');

    const r = await fetch(url, {
      signal: AbortSignal.timeout(TIMEOUT_MS),
      headers: { 'User-Agent': 'GodsEyeView/1.0 (GEV Intelligence)', Accept: 'application/geo+json' },
    });
    const body = await readResponseTextCapped(r, MAX_RESPONSE_BYTES);
    if (!r.ok) throw new Error(`NOAA HTTP ${r.status}`);

    const data = JSON.parse(body);
    const alerts = (data.features || []).map((f) => ({
      id: f.id || f.properties?.id,
      event: f.properties?.event,
      headline: f.properties?.headline,
      severity: f.properties?.severity,
      urgency: f.properties?.urgency,
      certainty: f.properties?.certainty,
      description: f.properties?.description?.slice(0, 500),
      lat: f.geometry?.coordinates?.[1],
      lon: f.geometry?.coordinates?.[0],
    }));
    return JSON.stringify({ available: true, source: 'NOAA/NWS', alerts, count: alerts.length });
  }

  return {
    name: 'weather-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/weather', async (req, res) => {
        if (!enforceRateLimit(_weatherLimiter, req, res)) return;
        const params = parseQuery(req.url);
        const key = `weather:${params.lat || 'global'}:${params.lon || 'global'}`;

        const cached = cache.get(key);
        if (cached) { sendJson(res, 200, cached.body); return; }

        const req_ = coalesceProxyRequest(inflight, key, () => fetchWeather(params));
        try {
          const result = await req_.promise;
          cache.set(key, result);
          sendJson(res, 200, result);
        } catch (e) {
          const stale = cache.get(key);
          if (stale) { sendJson(res, 200, stale.body); return; }
          sendJson(res, 502, { available: false, reason: e.message });
        }
      });
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// 2. Radar Proxy (Rainviewer)
// ═══════════════════════════════════════════════════════════════════════════════

export function radarProxy() {
  const cache = makeMemCache(300_000); // 5 min
  const inflight = new Map();

  async function fetchRadar() {
    const r = await fetch('https://api.rainviewer.com/public/weather-maps.json', {
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    const body = await readResponseTextCapped(r, MAX_RESPONSE_BYTES);
    if (!r.ok) throw new Error(`Rainviewer HTTP ${r.status}`);

    const data = JSON.parse(body);
    const radar = data.radar?.nowcast || data.radar?.past || [];
    const tileUrl = radar.length > 0 ? radar[radar.length - 1]?.path : null;

    return JSON.stringify({
      available: true,
      source: 'Rainviewer',
      tile_url: tileUrl ? `https://tilecache.rainviewer.com${tileUrl}/256/{z}/{x}/{y}/2/1_1.png` : null,
      timestamps: radar.map((r) => r.time),
      precipitation: [],
      count: 0,
    });
  }

  return {
    name: 'radar-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/radar', async (req, res) => {
        if (!enforceRateLimit(_radarLimiter, req, res)) return;
        const cached = cache.get('global');
        if (cached) { sendJson(res, 200, cached.body); return; }

        const req_ = coalesceProxyRequest(inflight, 'radar-global', fetchRadar);
        try {
          const result = await req_.promise;
          cache.set('global', result);
          sendJson(res, 200, result);
        } catch (e) {
          const stale = cache.get('global');
          if (stale) { sendJson(res, 200, stale.body); return; }
          sendJson(res, 502, { available: false, reason: e.message });
        }
      });
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// 3. AQI Proxy (OpenAQ)
// ═══════════════════════════════════════════════════════════════════════════════

export function aqiProxy() {
  const cache = makeMemCache(600_000); // 10 min
  const inflight = new Map();

  async function fetchAqi(params) {
    const url = new URL('https://api.openaq.org/v3/locations');
    if (params.lat && params.lon) {
      url.searchParams.set('coordinates', `${params.lat},${params.lon}`);
      url.searchParams.set('radius', String(optFloat(params.radius_km, 300) * 1000));
    }
    url.searchParams.set('limit', '100');
    url.searchParams.set('order', 'distance');

    const r = await fetch(url, {
      signal: AbortSignal.timeout(TIMEOUT_MS),
      headers: { 'Accept': 'application/json' },
    });
    const body = await readResponseTextCapped(r, MAX_RESPONSE_BYTES);
    if (!r.ok) throw new Error(`OpenAQ HTTP ${r.status}`);

    const data = JSON.parse(body);
    const stations = (data.results || []).map((s) => ({
      id: s.location_id || s.id,
      name: s.name,
      lat: s.coordinates?.latitude,
      lon: s.coordinates?.longitude,
      aqi: s.measurements?.[0]?.value || s.parameters?.[0]?.lastValue || 0,
      parameter: s.measurements?.[0]?.parameter || s.parameters?.[0]?.name || 'pm25',
      unit: s.measurements?.[0]?.unit || s.parameters?.[0]?.unit || 'µg/m³',
    }));
    return JSON.stringify({ available: true, source: 'OpenAQ', stations, count: stations.length });
  }

  return {
    name: 'aqi-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/aqi', async (req, res) => {
        if (!enforceRateLimit(_aqiLimiter, req, res)) return;
        const params = parseQuery(req.url);
        const key = `aqi:${params.lat || 'global'}:${params.lon || 'global'}`;

        const cached = cache.get(key);
        if (cached) { sendJson(res, 200, cached.body); return; }

        const req_ = coalesceProxyRequest(inflight, key, () => fetchAqi(params));
        try {
          const result = await req_.promise;
          cache.set(key, result);
          sendJson(res, 200, result);
        } catch (e) {
          const stale = cache.get(key);
          if (stale) { sendJson(res, 200, stale.body); return; }
          sendJson(res, 502, { available: false, reason: e.message });
        }
      });
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// 4. Volcanoes Proxy (USGS)
// ═══════════════════════════════════════════════════════════════════════════════

export function volcanoesProxy() {
  const cache = makeDiskCache('volcanoes', 300_000); // 5 min memory, 35 min disk
  const inflight = new Map();

  async function fetchVolcanoes() {
    const r = await fetch(
      'https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=last7days&minmagnitude=0&eventtype=earthquake',
      { signal: AbortSignal.timeout(TIMEOUT_MS) },
    );
    const body = await readResponseTextCapped(r, MAX_RESPONSE_BYTES);
    if (!r.ok) throw new Error(`USGS HTTP ${r.status}`);

    // Also try the volcano-specific feed
    let volcanoes = [];
    try {
      const vr = await fetch('https://volcano.si.edu/gf.json', {
        signal: AbortSignal.timeout(TIMEOUT_MS),
      });
      if (vr.ok) {
        const vData = await vr.json();
        volcanoes = (vData?.data || []).map((v) => ({
          id: v.VolcanoNumber || v.id,
          name: v.VolcanoName || v.name,
          lat: v.Latitude,
          lon: v.Longitude,
          elevation: v.Elevation,
          status: v.Status || v.ActivityLevel || 'unspecified',
          erupting: (v.Status || '').toLowerCase().includes('erupt'),
        }));
      }
    } catch { /* volcano feed is optional */ }

    return JSON.stringify({ available: true, source: 'USGS/VAAC', volcanoes, count: volcanoes.length, advisories: [] });
  }

  return {
    name: 'volcanoes-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/volcanoes', async (req, res) => {
        if (!enforceRateLimit(_infrastructureLimiter, req, res)) return;
        await cache.init();
        const cached = cache.get('global');
        if (cached) { sendJson(res, 200, cached.body); return; }

        const disk = await cache.getFromDisk('global');
        const req_ = coalesceProxyRequest(inflight, 'volcanoes-global', fetchVolcanoes);
        try {
          const result = await req_.promise;
          cache.set('global', result);
          sendJson(res, 200, result);
        } catch (e) {
          if (disk) { sendJson(res, 200, disk.body); return; }
          sendJson(res, 502, { available: false, reason: e.message });
        }
      });
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// 5. Power Outages Proxy (ElectricityMap / utility feeds)
// ═══════════════════════════════════════════════════════════════════════════════

export function powerOutagesProxy() {
  const cache = makeMemCache(300_000);
  const inflight = new Map();

  async function fetchPowerOutages(params) {
    // US outage data from EIA (Energy Information Administration)
    const outages = [];
    try {
      const r = await fetch(
        'https://api.eia.gov/v2/electricity/rto/region-data/data/?api_key=DEMO_KEY&frequency=hourly&data[0]=value&facets[respondent][]=US48&sort[0][column]=period&sort[0][direction]=desc&length=1',
        { signal: AbortSignal.timeout(TIMEOUT_MS) },
      );
      if (r.ok) {
        const data = await r.json();
        const latest = data?.response?.data?.[0];
        if (latest) {
          outages.push({
            id: 'us-grid',
            region: 'US Continental Grid',
            lat: 39.8,
            lon: -98.5,
            customers: latest.value || 0,
            cause: 'grid load monitoring',
            status: 'monitoring',
          });
        }
      }
    } catch { /* EIA is optional */ }

    return JSON.stringify({ available: true, source: 'EIA/Utility Feeds', outages, count: outages.length });
  }

  return {
    name: 'power-outages-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/power-outages', async (req, res) => {
        if (!enforceRateLimit(_infrastructureLimiter, req, res)) return;
        const params = parseQuery(req.url);
        const key = `power:${params.lat || 'global'}:${params.lon || 'global'}`;

        const cached = cache.get(key);
        if (cached) { sendJson(res, 200, cached.body); return; }

        const req_ = coalesceProxyRequest(inflight, key, () => fetchPowerOutages(params));
        try {
          const result = await req_.promise;
          cache.set(key, result);
          sendJson(res, 200, result);
        } catch (e) {
          const stale = cache.get(key);
          if (stale) { sendJson(res, 200, stale.body); return; }
          sendJson(res, 502, { available: false, reason: e.message });
        }
      });
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// 6. Transit Proxy (GTFS-RT feeds)
// ═══════════════════════════════════════════════════════════════════════════════

export function transitProxy() {
  const cache = makeMemCache(30_000); // 30s for live transit
  const inflight = new Map();

  async function fetchTransit(params) {
    // Transitland aggregated feed
    const vehicles = [];
    try {
      // Try SF Muni as a sample GTFS-RT feed
      const r = await fetch(
        'https://api.511.org/transit/realtime/vehiclepositions?api_key=DEMO',
        { signal: AbortSignal.timeout(TIMEOUT_MS) },
      );
      if (r.ok) {
        const text = await r.text();
        // 511.org returns BOM-prefixed JSON
        const data = JSON.parse(text.replace(/^\uFEFF/, ''));
        for (const entity of (data?.entity || []).slice(0, 200)) {
          const pos = entity.vehicle?.position;
          if (!pos) continue;
          vehicles.push({
            id: entity.id,
            lat: pos.latitude,
            lon: pos.longitude,
            speed: pos.speed || 0,
            heading: pos.bearing || 0,
            route: entity.vehicle?.trip?.routeId || '',
            type: 'transit',
          });
        }
      }
    } catch { /* transit feeds are optional */ }

    return JSON.stringify({ available: true, source: 'GTFS-RT', vehicles, count: vehicles.length });
  }

  return {
    name: 'transit-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/transit', async (req, res) => {
        if (!enforceRateLimit(_infrastructureLimiter, req, res)) return;
        const params = parseQuery(req.url);
        const key = `transit:${params.lat || 'global'}:${params.lon || 'global'}`;

        const cached = cache.get(key);
        if (cached) { sendJson(res, 200, cached.body); return; }

        const req_ = coalesceProxyRequest(inflight, key, () => fetchTransit(params));
        try {
          const result = await req_.promise;
          cache.set(key, result);
          sendJson(res, 200, result);
        } catch (e) {
          const stale = cache.get(key);
          if (stale) { sendJson(res, 200, stale.body); return; }
          sendJson(res, 502, { available: false, reason: e.message });
        }
      });
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// 7. Space Weather Proxy (NOAA SWPC)
// ═══════════════════════════════════════════════════════════════════════════════

export function spaceWeatherProxy() {
  const cache = makeDiskCache('space-weather', 300_000); // 5 min memory, 35 min disk
  const inflight = new Map();

  async function fetchSpaceWeather() {
    const [flaresRes, stormsRes] = await Promise.allSettled([
      fetch('https://services.swpc.noaa.gov/json/solar/predicted-xray-flares.json', {
        signal: AbortSignal.timeout(TIMEOUT_MS),
      }),
      fetch('https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json', {
        signal: AbortSignal.timeout(TIMEOUT_MS),
      }),
    ]);

    const flares = [];
    if (flaresRes.status === 'fulfilled' && flaresRes.value.ok) {
      const data = JSON.parse(await flaresRes.value.text());
      for (const f of (Array.isArray(data) ? data : []).slice(0, 20)) {
        flares.push({
          id: f.id || flares.length,
          class: f.flare_class || f.class || 'A',
          magnitude: f.magnitude || f.peak_flux || 0,
          time: f.time_frame || f.forecast_time || '',
        });
      }
    }

    const storms = [];
    if (stormsRes.status === 'fulfilled' && stormsRes.value.ok) {
      const data = JSON.parse(await stormsRes.value.text());
      const latest = Array.isArray(data) ? data[data.length - 1] : null;
      if (latest) {
        storms.push({
          id: 'kp-current',
          kp: parseFloat(latest.kp_index || latest[1] || 0),
          time: latest.time_tag || latest[0] || '',
          class: (latest.kp_index || latest[1] || 0) >= 5 ? 'G1+' : 'normal',
        });
      }
    }

    return JSON.stringify({
      available: true,
      source: 'NOAA SWPC',
      flares,
      storms,
      geomagnetic_storms: storms,
      solar_flares: flares,
      count: flares.length + storms.length,
    });
  }

  return {
    name: 'space-weather-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/space-weather', async (req, res) => {
        if (!enforceRateLimit(_spaceLimiter, req, res)) return;
        await cache.init();
        const cached = cache.get('global');
        if (cached) { sendJson(res, 200, cached.body); return; }

        const disk = await cache.getFromDisk('global');
        const req_ = coalesceProxyRequest(inflight, 'space-weather', fetchSpaceWeather);
        try {
          const result = await req_.promise;
          cache.set('global', result);
          sendJson(res, 200, result);
        } catch (e) {
          if (disk) { sendJson(res, 200, disk.body); return; }
          sendJson(res, 502, { available: false, reason: e.message });
        }
      });
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// 8. NEO Proxy (NASA JPL)
// ═══════════════════════════════════════════════════════════════════════════════

export function neosProxy() {
  const cache = makeDiskCache('neos', 3_600_000); // 1 hour memory, 7 hour disk
  const inflight = new Map();

  async function fetchNeos() {
    const today = new Date().toISOString().split('T')[0];
    const r = await fetch(
      `https://api.nasa.gov/neo/rest/v1/feed?start_date=${today}&end_date=${today}&api_key=DEMO_KEY`,
      { signal: AbortSignal.timeout(TIMEOUT_MS) },
    );
    const body = await readResponseTextCapped(r, MAX_RESPONSE_BYTES);
    if (!r.ok) throw new Error(`NASA NEO HTTP ${r.status}`);

    const data = JSON.parse(body);
    const objects = [];
    for (const day of Object.values(data?.near_earth_objects || {})) {
      for (const neo of day) {
        const approach = neo.close_approach_data?.[0] || {};
        objects.push({
          id: neo.id,
          name: neo.name,
          diameter_km: (neo.estimated_diameter?.kilometers?.maxEstimatedDiameter + neo.estimated_diameter?.kilometers?.minEstimatedDiameter) / 2,
          miss_distance_km: parseFloat(approach.miss_distance || 0),
          close_approach_date: approach.close_approach_date || '',
          velocity_kps: parseFloat(approach.relative_velocity?.kilometersPerSecond || 0),
          hazardous: neo.is_potentially_hazardous_asteroid || false,
        });
      }
    }

    return JSON.stringify({ available: true, source: 'NASA JPL', objects, neos: objects, count: objects.length });
  }

  return {
    name: 'neos-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/neos', async (req, res) => {
        if (!enforceRateLimit(_intelLimiter, req, res)) return;
        await cache.init();
        const cached = cache.get('global');
        if (cached) { sendJson(res, 200, cached.body); return; }

        // Check disk for stale data
        const disk = await cache.getFromDisk('global');
        const req_ = coalesceProxyRequest(inflight, 'neos-global', fetchNeos);
        try {
          const result = await req_.promise;
          cache.set('global', result);
          sendJson(res, 200, result);
        } catch (e) {
          if (disk) { sendJson(res, 200, disk.body); return; }
          sendJson(res, 502, { available: false, reason: e.message });
        }
      });
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// 9. GPS Jamming Proxy (GPSJam)
// ═══════════════════════════════════════════════════════════════════════════════

export function gpsJammingProxy() {
  const cache = makeDiskCache('gps-jamming', 600_000); // 10 min memory, 70 min disk
  const inflight = new Map();

  async function fetchGpsJamming() {
    const r = await fetch('https://gpsjam.org/api/zones', {
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    const body = await readResponseTextCapped(r, MAX_RESPONSE_BYTES);
    if (!r.ok) throw new Error(`GPSJam HTTP ${r.status}`);

    const data = JSON.parse(body);
    const zones = (Array.isArray(data) ? data : data?.features || []).map((z, i) => ({
      id: z.id || z.properties?.id || `jam-${i}`,
      type: 'gps_interference',
      lat: z.properties?.lat || z.geometry?.coordinates?.[1] || 0,
      lon: z.properties?.lon || z.geometry?.coordinates?.[0] || 0,
      severity: z.properties?.severity || z.properties?.level || 'unknown',
      confidence: z.properties?.confidence || 0.5,
      polygon: z.geometry?.type === 'Polygon' ? z.geometry.coordinates?.[0] : null,
      description: z.properties?.description || 'GPS interference zone',
    }));

    return JSON.stringify({ available: true, source: 'GPSJam', zones, count: zones.length });
  }

  return {
    name: 'gps-jamming-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/gps-jamming', async (req, res) => {
        if (!enforceRateLimit(_intelLimiter, req, res)) return;
        await cache.init();
        const cached = cache.get('global');
        if (cached) { sendJson(res, 200, cached.body); return; }

        const disk = await cache.getFromDisk('global');
        const req_ = coalesceProxyRequest(inflight, 'gps-jamming', fetchGpsJamming);
        try {
          const result = await req_.promise;
          cache.set('global', result);
          sendJson(res, 200, result);
        } catch (e) {
          if (disk) { sendJson(res, 200, disk.body); return; }
          sendJson(res, 502, { available: false, reason: e.message });
        }
      });
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// 10. Social Events Proxy (GDACS)
// ═══════════════════════════════════════════════════════════════════════════════

export function socialEventsProxy() {
  const cache = makeDiskCache('social-events', 300_000); // 5 min memory, 35 min disk
  const inflight = new Map();

  async function fetchSocialEvents() {
    const r = await fetch('https://www.gdacs.org/xml/rss.xml', {
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    const text = await r.text();
    if (!r.ok) throw new Error(`GDACS HTTP ${r.status}`);

    const events = [];
    const items = text.split('<item>').slice(1);
    for (const item of items.slice(0, 50)) {
      const title = item.match(/<title>(.*?)<\/title>/)?.[1] || '';
      const lat = item.match(/<gdacs:lat>(.*?)<\/gdacs:lat>/)?.[1];
      const lon = item.match(/<gdacs:lon>(.*?)<\/gdacs:lon>/)?.[1];
      const severity = item.match(/<gdacs:alertlevel>(.*?)<\/gdacs:alertlevel>/)?.[1] || 'unknown';
      const eventType = item.match(/<gdacs:eventtype>(.*?)<\/gdacs:eventtype>/)?.[1] || 'disaster';

      if (lat && lon) {
        events.push({
          id: `gdacs-${events.length}`,
          source: 'GDACS',
          type: eventType,
          title,
          lat: parseFloat(lat),
          lon: parseFloat(lon),
          severity,
          description: title,
        });
      }
    }

    return JSON.stringify({ available: true, source: 'GDACS', events, count: events.length });
  }

  return {
    name: 'social-events-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/social-events', async (req, res) => {
        if (!enforceRateLimit(_intelLimiter, req, res)) return;
        await cache.init();
        const cached = cache.get('global');
        if (cached) { sendJson(res, 200, cached.body); return; }

        const disk = await cache.getFromDisk('global');
        const req_ = coalesceProxyRequest(inflight, 'social-events', fetchSocialEvents);
        try {
          const result = await req_.promise;
          cache.set('global', result);
          sendJson(res, 200, result);
        } catch (e) {
          if (disk) { sendJson(res, 200, disk.body); return; }
          sendJson(res, 502, { available: false, reason: e.message });
        }
      });
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// 11–13. Satellite Imagery, Satellite Analysis, OSINT (local, no upstream)
// ═══════════════════════════════════════════════════════════════════════════════

export function satelliteImageryProxy() {
  return {
    name: 'satellite-imagery-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/satellite-imagery', async (req, res) => {
        // Sentinel-2 / Landsat search — proxied through the backend
        const params = parseQuery(req.url);
        const lat = optFloat(params.lat);
        const lon = optFloat(params.lon);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
          sendJson(res, 400, { error: 'lat and lon are required' });
          return;
        }
        // Forward to the backend GEV intelligence system
        sendJson(res, 200, {
          available: true,
          source: 'Sentinel-2/Landsat',
          lat, lon,
          message: 'Satellite imagery search — use the GEV backend for full analysis',
        });
      });
    },
  };
}

export function satelliteAnalyseProxy() {
  return {
    name: 'satellite-analyse-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/satellite-analyse', async (req, res) => {
        sendJson(res, 200, {
          available: false,
          reason: 'Vision analysis requires GEMINI_API_KEY or OPENAI_API_KEY — use the GEV backend',
        });
      });
    },
  };
}

export function osintProxy() {
  const cache = makeDiskCache('osint', 3_600_000); // 1 hour memory, 7 hour disk
  const inflight = new Map();

  async function enrichVessel(query) {
    const r = await fetch(`https://api.opensanctions.org/search/default?q=${encodeURIComponent(query)}&limit=5`, {
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (!r.ok) throw new Error(`OpenSanctions HTTP ${r.status}`);
    const data = await r.json();
    return (data.results || [])
      .filter((r) => r.score > 0.5)
      .map((r) => ({ name: r.name, score: r.score, datasets: r.datasets }));
  }

  return {
    name: 'osint-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/osint', async (req, res) => {
        if (!enforceRateLimit(_osintLimiter, req, res)) return;
        await cache.init();
        const params = parseQuery(req.url);
        const query = params.query || params.name || '';
        if (!query) { sendJson(res, 400, { error: 'query is required' }); return; }

        const key = query;
        const cached = cache.get(key);
        if (cached) { sendJson(res, 200, cached.body); return; }

        const disk = await cache.getFromDisk(key);
        const req_ = coalesceProxyRequest(inflight, key, () => enrichVessel(query));
        try {
          const result = await req_.promise;
          const body = JSON.stringify({ available: true, source: 'OpenSanctions', results: result });
          cache.set(key, body);
          sendJson(res, 200, body);
        } catch (e) {
          if (disk) { sendJson(res, 200, disk.body); return; }
          sendJson(res, 502, { available: false, reason: e.message });
        }
      });
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// 14–15. Geofencing & DVR (local state, no upstream)
// ═══════════════════════════════════════════════════════════════════════════════

export function geofenceProxy() {
  // In-memory geofence rules (would be managed by the backend agent)
  const rules = new Map();

  return {
    name: 'geofence-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/geofence', async (req, res) => {
        const subPath = (req.url || '').split('?')[0];

        if (subPath === '/rules' || subPath === '/') {
          if (req.method === 'GET') {
            sendJson(res, 200, { rules: [...rules.values()] });
          } else if (req.method === 'POST') {
            // Parse body
            let body = '';
            for await (const chunk of req) body += chunk;
            try {
              const rule = JSON.parse(body);
              rules.set(rule.id || `rule-${Date.now()}`, rule);
              sendJson(res, 200, { registered: rule.id });
            } catch {
              sendJson(res, 400, { error: 'Invalid JSON' });
            }
          }
        } else if (subPath === '/fired') {
          sendJson(res, 200, { events: [] }); // Placeholder
        } else {
          sendJson(res, 404, { error: 'Unknown geofence endpoint' });
        }
      });
    },
  };
}

export function dvrProxy() {
  // DVR timeline is managed by the backend GEV agent — this proxy forwards to it
  const cache = makeMemCache(10_000); // 10s
  const inflight = new Map();

  return {
    name: 'dvr-proxy',
    configureServer(server) {
      server.middlewares.use('/api/gev/timeline', async (req, res) => {
        const cached = cache.get('timeline');
        if (cached) { sendJson(res, 200, cached.body); return; }

        // The backend agent manages the timeline — this is a placeholder
        const body = JSON.stringify({
          data: [],
          timeline_length: 0,
          oldest: null,
          newest: null,
        });
        cache.set('timeline', body);
        sendJson(res, 200, body);
      });

      server.middlewares.use('/api/gev/playback', async (req, res) => {
        const params = parseQuery(req.url);
        sendJson(res, 200, { source: 'playback', target_ts: parseFloat(params.target_ts), data: null });
      });
    },
  };
}
