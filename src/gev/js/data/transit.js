import * as Cesium from 'cesium';
import {
  clearOverlaySource,
  setOverlayEntries,
  setOverlaySourceVisible,
} from '../overlays/worldOverlay.js';

/**
 * Public transit layer — live tracking of trains and transit via GTFS-RT feeds.
 * Fetches from the GEV proxy backend (/api/gev/transit).
 *
 * Displays transit vehicles as moving entity markers with route labels.
 */

const TRANSIT_OVERLAY_SOURCE_ID = 'transit';
const DEFAULT_OVERLAY_HOST = Object.freeze({
  setEntries: setOverlayEntries,
  setVisible: setOverlaySourceVisible,
  clearSource: clearOverlaySource,
});

const TRANSIT_COLORS = {
  train: Cesium.Color.DODGERBLUE,
  bus: Cesium.Color.LIMEGREEN,
  tram: Cesium.Color.GOLD,
  subway: Cesium.Color.HOTPINK,
  ferry: Cesium.Color.CYAN,
  default: Cesium.Color.WHITE,
};

function transitColor(type) {
  return TRANSIT_COLORS[type?.toLowerCase()] || TRANSIT_COLORS.default;
}

export function createTransitLayer({ overlayHost = DEFAULT_OVERLAY_HOST } = {}) {
  let _dataSource = null;
  let _count = 0;
  let _lastUpdate = null;
  let _lastError = null;
  let _enabled = false;

  const layer = {
    id: 'transit',
    name: 'Public Transit',
    icon: '🚆',
    source: 'GTFS-RT',
    updateInterval: 30000, // 30 seconds for live tracking

    init(viewer) {
      _dataSource = new Cesium.CustomDataSource('transit');
      _dataSource.show = false;
      viewer.dataSources.add(_dataSource);
      overlayHost.setVisible(TRANSIT_OVERLAY_SOURCE_ID, false);
    },

    enable(viewer) {
      _enabled = true;
      if (_dataSource) _dataSource.show = true;
      overlayHost.setVisible(TRANSIT_OVERLAY_SOURCE_ID, true);
    },

    disable(viewer) {
      _enabled = false;
      if (_dataSource) _dataSource.show = false;
      overlayHost.clearSource(TRANSIT_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(TRANSIT_OVERLAY_SOURCE_ID, false);
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
        const url = `/api/gev/transit${params.toString() ? '?' + params : ''}`;
        const response = await fetch(url);
        if (!response.ok) { _lastError = `HTTP ${response.status}`; return false; }
        const data = await response.json();
        if (data.available === false) return false;

        _dataSource.entities.removeAll();
        const overlayEntries = [];
        let count = 0;

        const vehicles = data.vehicles || data.entities || data.features || [];
        for (const vehicle of vehicles) {
          const lon = vehicle.lon || vehicle.longitude || vehicle.position?.lon || vehicle.position?.longitude;
          const lat = vehicle.lat || vehicle.latitude || vehicle.position?.lat || vehicle.position?.latitude;
          if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;

          count++;
          const position = Cesium.Cartesian3.fromDegrees(lon, lat);
          const type = vehicle.type || vehicle.route_type || 'default';
          const color = transitColor(type);
          const route = vehicle.route || vehicle.route_name || vehicle.trip_id || `Route ${count}`;
          const name = vehicle.name || vehicle.label || vehicle.vehicle_id || route;

          _dataSource.entities.add({
            id: `transit:${vehicle.id || vehicle.vehicle_id || count}`,
            position,
            point: {
              pixelSize: 8,
              color,
              outlineColor: Cesium.Color.WHITE.withAlpha(0.6),
              outlineWidth: 1,
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            },
            label: {
              text: route,
              font: '9px JetBrains Mono, monospace',
              fillColor: Cesium.Color.WHITE,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
              pixelOffset: new Cesium.Cartesian2(0, -10),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            properties: { route, name, type },
          });

          overlayEntries.push({
            id: `transit-label:${vehicle.id || vehicle.vehicle_id || count}`,
            position,
            variant: 'label',
            title: route,
            details: [name, type.toUpperCase()],
            accent: color.toCssColorString(),
            priority: 300,
            collisionGroup: 'ambient-label',
            paintLane: 'ambient-label',
            interactive: false,
            edgeFade: 'keyhole',
            horizonCull: true,
            terrainOcclusion: false,
            minDistance: 5000,
            maxDistance: 500000,
          });
        }

        if (_enabled && overlayEntries.length > 0) {
          overlayHost.setEntries(TRANSIT_OVERLAY_SOURCE_ID, overlayEntries.slice(0, 256), {
            cohortLimit: 128,
            collisionCapacity: 64,
            moving: true,
            solveIntervalMs: 200,
          });
        }

        _count = count;
        _lastUpdate = Date.now();
        _lastError = null;
        return true;
      } catch (e) {
        console.warn('[Data:Transit] Fetch error:', e);
        _lastError = 'Transit network error';
        return false;
      }
    },

    destroy(viewer) {
      _enabled = false;
      overlayHost.clearSource(TRANSIT_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(TRANSIT_OVERLAY_SOURCE_ID, false);
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

const transitLayer = createTransitLayer();
export default transitLayer;
