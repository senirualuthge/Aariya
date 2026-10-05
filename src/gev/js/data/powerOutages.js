import * as Cesium from 'cesium';
import {
  clearOverlaySource,
  setOverlayEntries,
  setOverlaySourceVisible,
} from '../overlays/worldOverlay.js';

/**
 * Power outage layer — major regional grid failures and blackouts.
 * Fetches from the GEV proxy backend (/api/gev/power-outages).
 *
 * Displays outage regions as semi-transparent red polygons with
 * affected-customer count labels.
 */

const OUTAGE_OVERLAY_SOURCE_ID = 'powerOutages';
const DEFAULT_OVERLAY_HOST = Object.freeze({
  setEntries: setOverlayEntries,
  setVisible: setOverlaySourceVisible,
  clearSource: clearOverlaySource,
});

const OUTAGE_COLOR = Cesium.Color.RED.withAlpha(0.35);
const OUTAGE_BORDER = Cesium.Color.RED.withAlpha(0.7);

function outageSeverity(customers) {
  if (customers > 100000) return { label: 'MASSIVE', priority: 1000 };
  if (customers > 50000) return { label: 'LARGE', priority: 800 };
  if (customers > 10000) return { label: 'MODERATE', priority: 500 };
  return { label: 'LOCAL', priority: 200 };
}

export function createPowerOutagesLayer({ overlayHost = DEFAULT_OVERLAY_HOST } = {}) {
  let _dataSource = null;
  let _count = 0;
  let _lastUpdate = null;
  let _lastError = null;
  let _enabled = false;

  const layer = {
    id: 'powerOutages',
    name: 'Power Outages',
    icon: '🔌',
    source: 'Grid Monitoring',
    updateInterval: 300000,

    init(viewer) {
      _dataSource = new Cesium.CustomDataSource('powerOutages');
      _dataSource.show = false;
      viewer.dataSources.add(_dataSource);
      overlayHost.setVisible(OUTAGE_OVERLAY_SOURCE_ID, false);
    },

    enable(viewer) {
      _enabled = true;
      if (_dataSource) _dataSource.show = true;
      overlayHost.setVisible(OUTAGE_OVERLAY_SOURCE_ID, true);
    },

    disable(viewer) {
      _enabled = false;
      if (_dataSource) _dataSource.show = false;
      overlayHost.clearSource(OUTAGE_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(OUTAGE_OVERLAY_SOURCE_ID, false);
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
        const url = `/api/gev/power-outages${params.toString() ? '?' + params : ''}`;
        const response = await fetch(url);
        if (!response.ok) { _lastError = `HTTP ${response.status}`; return false; }
        const data = await response.json();
        if (data.available === false) return false;

        _dataSource.entities.removeAll();
        const overlayEntries = [];
        let count = 0;

        const outages = data.outages || data.events || data.features || [];
        for (const outage of outages) {
          const lon = outage.lon || outage.longitude || outage.center?.lon;
          const lat = outage.lat || outage.latitude || outage.center?.lat;
          if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;

          count++;
          const position = Cesium.Cartesian3.fromDegrees(lon, lat);
          const customers = outage.customers || outage.affected || outage.count || 0;
          const severity = outageSeverity(customers);
          const region = outage.region || outage.name || outage.utility || `Outage ${count}`;
          const cause = outage.cause || outage.reason || 'Unknown';

          // Draw outage marker
          _dataSource.entities.add({
            id: `outage:${outage.id || count}`,
            position,
            point: {
              pixelSize: Math.min(20, Math.max(8, Math.sqrt(customers) / 100)),
              color: OUTAGE_COLOR,
              outlineColor: OUTAGE_BORDER,
              outlineWidth: 2,
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            },
            label: {
              text: `${(customers / 1000).toFixed(1)}k`,
              font: '10px JetBrains Mono, monospace',
              fillColor: Cesium.Color.WHITE,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.CENTER,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            properties: { region, customers, cause },
          });

          // Draw affected area polygon if coordinates provided
          const polygon = outage.polygon || outage.area || outage.bounds;
          if (Array.isArray(polygon) && polygon.length >= 3) {
            const positions = polygon.map((pt) => {
              const pLon = Array.isArray(pt) ? pt[0] : pt.lon || pt.longitude;
              const pLat = Array.isArray(pt) ? pt[1] : pt.lat || pt.latitude;
              return Cesium.Cartesian3.fromDegrees(pLon, pLat);
            });
            positions.push(positions[0]);
            _dataSource.entities.add({
              id: `outage-area:${outage.id || count}`,
              polygon: {
                hierarchy: new Cesium.PolygonHierarchy(positions),
                material: OUTAGE_COLOR,
                outline: true,
                outlineColor: OUTAGE_BORDER,
                heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
              },
            });
          }

          overlayEntries.push({
            id: `outage-label:${outage.id || count}`,
            position,
            variant: 'card',
            title: region,
            details: [severity.label, `${(customers / 1000).toFixed(1)}k affected`, cause],
            accent: OUTAGE_BORDER.toCssColorString(),
            priority: severity.priority,
            collisionGroup: 'ambient-card',
            paintLane: 'ambient-card',
            interactive: true,
            edgeFade: 'keyhole',
            horizonCull: true,
          });
        }

        if (_enabled && overlayEntries.length > 0) {
          overlayHost.setEntries(OUTAGE_OVERLAY_SOURCE_ID, overlayEntries.slice(0, 96), {
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
        console.warn('[Data:PowerOutages] Fetch error:', e);
        _lastError = 'Power outage network error';
        return false;
      }
    },

    destroy(viewer) {
      _enabled = false;
      overlayHost.clearSource(OUTAGE_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(OUTAGE_OVERLAY_SOURCE_ID, false);
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

const powerOutagesLayer = createPowerOutagesLayer();
export default powerOutagesLayer;
