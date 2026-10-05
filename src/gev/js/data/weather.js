import * as Cesium from 'cesium';
import {
  clearOverlaySource,
  setOverlayEntries,
  setOverlaySourceVisible,
} from '../overlays/worldOverlay.js';

/**
 * Weather layer — severe weather, storm tracking, hurricane/cyclone paths.
 * Fetches from the GEV proxy backend (/api/gev/weather).
 *
 * Displays:
 *   - Hurricane/cyclone paths as polylines with storm intensity colours
 *   - Tornado warnings as animated point markers
 *   - Severe weather alerts as region polygons
 */

const WEATHER_OVERLAY_SOURCE_ID = 'weather';
const DEFAULT_OVERLAY_HOST = Object.freeze({
  setEntries: setOverlayEntries,
  setVisible: setOverlaySourceVisible,
  clearSource: clearOverlaySource,
});

const SEVERITY_COLORS = Object.freeze({
  extreme: Cesium.Color.DARKRED.withAlpha(0.7),
  severe: Cesium.Color.RED.withAlpha(0.6),
  moderate: Cesium.Color.ORANGE.withAlpha(0.5),
  minor: Cesium.Color.YELLOW.withAlpha(0.4),
  info: Cesium.Color.CYAN.withAlpha(0.3),
});

function severityColor(severity) {
  return SEVERITY_COLORS[severity?.toLowerCase()] || SEVERITY_COLORS.info;
}

function createWeatherOverlayEntry({ id, position, title, detail, accent, priority }) {
  return {
    id: String(id),
    position,
    variant: 'card',
    title: String(title),
    details: Array.isArray(detail) ? detail : [String(detail || '')],
    accent: accent || '#6be8ff',
    priority: priority || 0,
    collisionGroup: 'ambient-card',
    paintLane: 'ambient-card',
    interactive: true,
    edgeFade: 'keyhole',
    horizonCull: true,
    terrainOcclusion: false,
  };
}

export function createWeatherLayer({ overlayHost = DEFAULT_OVERLAY_HOST } = {}) {
  let _dataSource = null;
  let _count = 0;
  let _lastUpdate = null;
  let _lastError = null;
  let _enabled = false;

  const layer = {
    id: 'weather',
    name: 'Weather Alerts',
    icon: '⛈️',
    source: 'NOAA/NWS',
    updateInterval: 120000, // 2 minutes

    init(viewer) {
      _dataSource = new Cesium.CustomDataSource('weather');
      _dataSource.show = false;
      viewer.dataSources.add(_dataSource);
      overlayHost.setVisible(WEATHER_OVERLAY_SOURCE_ID, false);
    },

    enable(viewer) {
      _enabled = true;
      if (_dataSource) _dataSource.show = true;
      overlayHost.setVisible(WEATHER_OVERLAY_SOURCE_ID, true);
    },

    disable(viewer) {
      _enabled = false;
      if (_dataSource) _dataSource.show = false;
      overlayHost.clearSource(WEATHER_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(WEATHER_OVERLAY_SOURCE_ID, false);
    },

    async update(viewer) {
      try {
        const params = new URLSearchParams();
        if (viewer.camera) {
          const carto = viewer.camera.positionCartographic;
          if (carto) {
            params.set('lat', Cesium.Math.toDegrees(carto.latitude).toFixed(4));
            params.set('lon', Cesium.Math.toDegrees(carto.longitude).toFixed(4));
          }
        }
        const url = `/api/gev/weather${params.toString() ? '?' + params : ''}`;
        const response = await fetch(url);
        if (!response.ok) {
          _lastError = `HTTP ${response.status}`;
          return false;
        }
        const data = await response.json();
        if (data.available === false) return false;

        _dataSource.entities.removeAll();
        const overlayEntries = [];
        let count = 0;

        // Process alerts
        const alerts = data.alerts || data.features || data.items || [];
        for (const alert of alerts) {
          const lon = alert.lon || alert.longitude || (alert.geometry?.coordinates?.[0]);
          const lat = alert.lat || alert.latitude || (alert.geometry?.coordinates?.[1]);
          if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;

          count++;
          const position = Cesium.Cartesian3.fromDegrees(lon, lat);
          const severity = alert.severity || alert.level || 'info';
          const color = severityColor(severity);
          const title = alert.event || alert.title || 'Weather Alert';
          const headline = alert.headline || alert.description || '';

          _dataSource.entities.add({
            id: `weather:${alert.id || alert.eventId || count}`,
            position,
            point: {
              pixelSize: 12,
              color,
              outlineColor: Cesium.Color.WHITE.withAlpha(0.6),
              outlineWidth: 2,
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            },
            label: {
              text: title,
              font: '11px JetBrains Mono, monospace',
              fillColor: Cesium.Color.WHITE,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
              pixelOffset: new Cesium.Cartesian2(0, -16),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            properties: { severity, event: title, headline },
          });

          overlayEntries.push(createWeatherOverlayEntry({
            id: alert.id || alert.eventId || `alert-${count}`,
            position,
            title,
            detail: [severity.toUpperCase(), headline.slice(0, 120)],
            accent: color.toCssColorString(),
            priority: severity === 'extreme' ? 1000 : severity === 'severe' ? 800 : 400,
          }));
        }

        // Process storm tracks
        const storms = data.storms || data.cyclones || [];
        for (const storm of storms) {
          const trackPoints = storm.track || storm.path || [];
          if (trackPoints.length < 2) continue;

          count++;
          const positions = trackPoints.map((pt) => {
            const sLon = pt.lon || pt.longitude;
            const sLat = pt.lat || pt.latitude;
            return Cesium.Cartesian3.fromDegrees(sLon, sLat);
          });

          const stormColor = severityColor(storm.category || storm.intensity || 'moderate');

          _dataSource.entities.add({
            id: `storm:${storm.id || storm.name || count}`,
            polyline: {
              positions,
              width: 3,
              material: new Cesium.PolylineGlowMaterialProperty({
                glowPower: 0.2,
                color: stormColor,
              }),
              clampToGround: true,
            },
            properties: { name: storm.name, category: storm.category },
          });

          // Add label at the storm's current position
          if (storm.current || trackPoints.length > 0) {
            const cp = storm.current || trackPoints[trackPoints.length - 1];
            const cpPos = Cesium.Cartesian3.fromDegrees(cp.lon || cp.longitude, cp.lat || cp.latitude);
            overlayEntries.push(createWeatherOverlayEntry({
              id: `storm-label:${storm.id || storm.name}`,
              position: cpPos,
              title: storm.name || 'Storm',
              detail: [storm.category || storm.intensity || 'Unknown', `Wind: ${storm.windSpeed || '?'} mph`],
              accent: stormColor.toCssColorString(),
              priority: 900,
            }));
          }
        }

        if (_enabled) {
          overlayHost.setEntries(WEATHER_OVERLAY_SOURCE_ID, overlayEntries, {
            cohortLimit: 64,
            collisionCapacity: 48,
            moving: false,
          });
        }

        _count = count;
        _lastUpdate = Date.now();
        _lastError = null;
        return true;
      } catch (e) {
        console.warn('[Data:Weather] Fetch error:', e);
        _lastError = 'Weather network error';
        return false;
      }
    },

    destroy(viewer) {
      _enabled = false;
      overlayHost.clearSource(WEATHER_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(WEATHER_OVERLAY_SOURCE_ID, false);
      if (_dataSource) {
        viewer.dataSources.remove(_dataSource, true);
        _dataSource = null;
      }
      _count = 0;
      _lastUpdate = null;
      _lastError = null;
    },

    getStats() {
      return { count: _count, lastUpdate: _lastUpdate, error: _lastError };
    },
  };
  return layer;
}

const weatherLayer = createWeatherLayer();
export default weatherLayer;
