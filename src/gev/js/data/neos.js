import * as Cesium from 'cesium';
import {
  clearOverlaySource,
  setOverlayEntries,
  setOverlaySourceVisible,
} from '../overlays/worldOverlay.js';

/**
 * Near-Earth Objects (NEOs) layer — asteroids and comets passing close to Earth.
 * Fetches from the GEV proxy backend (/api/gev/neos).
 *
 * Displays NEO positions as orbital markers with size and distance labels.
 * Objects are rendered at their approximate orbital position above the globe.
 */

const NEO_OVERLAY_SOURCE_ID = 'neos';
const DEFAULT_OVERLAY_HOST = Object.freeze({
  setEntries: setOverlayEntries,
  setVisible: setOverlaySourceVisible,
  clearSource: clearOverlaySource,
});

function neoSizeColor(diameterKm) {
  if (diameterKm > 1) return Cesium.Color.RED.withAlpha(0.8);       // City-killer
  if (diameterKm > 0.1) return Cesium.Color.ORANGE.withAlpha(0.7);  // Large
  if (diameterKm > 0.01) return Cesium.Color.YELLOW.withAlpha(0.6); // Medium
  return Cesium.Color.CYAN.withAlpha(0.5);                           // Small
}

function neoSizeLabel(diameterKm) {
  if (diameterKm > 1) return `${diameterKm.toFixed(1)} km`;
  if (diameterKm > 0.001) return `${(diameterKm * 1000).toFixed(0)} m`;
  return `${(diameterKm * 1000000).toFixed(0)} mm`;
}

export function createNeosLayer({ overlayHost = DEFAULT_OVERLAY_HOST } = {}) {
  let _dataSource = null;
  let _count = 0;
  let _lastUpdate = null;
  let _lastError = null;
  let _enabled = false;

  const layer = {
    id: 'neos',
    name: 'Near-Earth Objects',
    icon: '☄️',
    source: 'NASA JPL',
    updateInterval: 3600000, // 1 hour — NEOs don't move fast on screen

    init(viewer) {
      _dataSource = new Cesium.CustomDataSource('neos');
      _dataSource.show = false;
      viewer.dataSources.add(_dataSource);
      overlayHost.setVisible(NEO_OVERLAY_SOURCE_ID, false);
    },

    enable(viewer) {
      _enabled = true;
      if (_dataSource) _dataSource.show = true;
      overlayHost.setVisible(NEO_OVERLAY_SOURCE_ID, true);
    },

    disable(viewer) {
      _enabled = false;
      if (_dataSource) _dataSource.show = false;
      overlayHost.clearSource(NEO_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(NEO_OVERLAY_SOURCE_ID, false);
    },

    async update(viewer) {
      try {
        const response = await fetch('/api/gev/neos');
        if (!response.ok) { _lastError = `HTTP ${response.status}`; return false; }
        const data = await response.json();
        if (data.available === false) return false;

        _dataSource.entities.removeAll();
        const overlayEntries = [];
        let count = 0;

        const objects = data.objects || data.neos || data.elements || data.features || [];
        for (const neo of objects) {
          count++;

          // Position: use provided lat/lon or compute from orbital elements
          // For display, place NEOs above their sub-terrestrial point
          const lon = neo.lon || neo.longitude || neo.heliocentric?.lon || (count * 37 % 360 - 180);
          const lat = neo.lat || neo.latitude || neo.heliocentric?.lat || (Math.sin(count) * 60);
          const alt = (neo.distance_au || neo.distance || 0.01) * 150000000; // AU to approximate km

          if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;

          const position = Cesium.Cartesian3.fromDegrees(lon, lat, alt);
          const diameter = neo.diameter_km || neo.estimated_diameter_km || 0.01;
          const name = neo.name || neo.object_name || `NEO ${count}`;
          const missDist = neo.miss_distance_km || neo.close_approach?.miss_distance || 0;
          const approachDate = neo.close_approach_date || neo.close_approach?.date || '';
          const color = neoSizeColor(diameter);

          // Draw orbit trail
          if (neo.orbit_positions && neo.orbit_positions.length > 1) {
            const orbitPositions = neo.orbit_positions.map((pt) => {
              return Cesium.Cartesian3.fromDegrees(
                pt.lon || pt.longitude || 0,
                pt.lat || pt.latitude || 0,
                (pt.distance_au || 0.01) * 150000000,
              );
            });
            _dataSource.entities.add({
              id: `neo-orbit:${neo.id || count}`,
              polyline: {
                positions: orbitPositions,
                width: 1,
                material: new Cesium.PolylineGlowMaterialProperty({
                  glowPower: 0.1,
                  color: color.withAlpha(0.3),
                }),
              },
            });
          }

          _dataSource.entities.add({
            id: `neo:${neo.id || count}`,
            position,
            point: {
              pixelSize: Math.min(16, Math.max(4, diameter * 100)),
              color,
              outlineColor: Cesium.Color.WHITE.withAlpha(0.6),
              outlineWidth: 1,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            label: {
              text: name,
              font: '10px JetBrains Mono, monospace',
              fillColor: Cesium.Color.WHITE,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
              pixelOffset: new Cesium.Cartesian2(0, -12),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            properties: { name, diameter, missDistance: missDist, approachDate },
          });

          const distLabel = missDist > 1000000
            ? `${(missDist / 150000000).toFixed(4)} AU`
            : `${(missDist).toFixed(0)} km`;

          overlayEntries.push({
            id: `neo-label:${neo.id || count}`,
            position,
            variant: 'card',
            title: name,
            details: [
              neoSizeLabel(diameter),
              `Miss: ${distLabel}`,
              approachDate ? `Approach: ${approachDate}` : '',
            ],
            accent: color.toCssColorString(),
            priority: Math.round(diameter * 1000),
            collisionGroup: 'ambient-card',
            paintLane: 'ambient-card',
            interactive: true,
            edgeFade: 'keyhole',
            horizonCull: false,
            terrainOcclusion: false,
          });
        }

        if (_enabled && overlayEntries.length > 0) {
          overlayHost.setEntries(NEO_OVERLAY_SOURCE_ID, overlayEntries.slice(0, 64), {
            cohortLimit: 48,
            collisionCapacity: 32,
            moving: false,
          });
        }

        _count = count;
        _lastUpdate = Date.now();
        _lastError = null;
        return true;
      } catch (e) {
        console.warn('[Data:NEOs] Fetch error:', e);
        _lastError = 'NEO network error';
        return false;
      }
    },

    destroy(viewer) {
      _enabled = false;
      overlayHost.clearSource(NEO_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(NEO_OVERLAY_SOURCE_ID, false);
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

const neosLayer = createNeosLayer();
export default neosLayer;
