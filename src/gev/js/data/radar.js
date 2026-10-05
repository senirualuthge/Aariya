import * as Cesium from 'cesium';
import {
  clearOverlaySource,
  setOverlayEntries,
  setOverlaySourceVisible,
} from '../overlays/worldOverlay.js';

/**
 * Precipitation radar layer — live rain/snow radar from Rainviewer API.
 * Fetches from the GEV proxy backend (/api/gev/radar).
 *
 * Displays radar intensity as a colour-coded overlay on the globe.
 */

const RADAR_OVERLAY_SOURCE_ID = 'radar';
const DEFAULT_OVERLAY_HOST = Object.freeze({
  setEntries: setOverlayEntries,
  setVisible: setOverlaySourceVisible,
  clearSource: clearOverlaySource,
});

function intensityColor(intensity) {
  // dBZ-based colour mapping
  if (intensity > 55) return Cesium.Color.PURPLE.withAlpha(0.6);   // Extreme
  if (intensity > 45) return Cesium.Color.RED.withAlpha(0.55);     // Heavy
  if (intensity > 35) return Cesium.Color.ORANGE.withAlpha(0.5);   // Moderate-heavy
  if (intensity > 25) return Cesium.Color.YELLOW.withAlpha(0.45);  // Moderate
  if (intensity > 15) return Cesium.Color.GREEN.withAlpha(0.4);    // Light
  if (intensity > 5)  return Cesium.Color.CYAN.withAlpha(0.3);     // Very light
  return Cesium.Color.BLUE.withAlpha(0.2);                          // Trace
}

export function createRadarLayer({ overlayHost = DEFAULT_OVERLAY_HOST } = {}) {
  let _dataSource = null;
  let _count = 0;
  let _lastUpdate = null;
  let _lastError = null;
  let _enabled = false;
  let _tileImagery = null;

  const layer = {
    id: 'radar',
    name: 'Precipitation Radar',
    icon: '🌧️',
    source: 'Rainviewer',
    updateInterval: 300000, // 5 minutes

    init(viewer) {
      _dataSource = new Cesium.CustomDataSource('radar');
      _dataSource.show = false;
      viewer.dataSources.add(_dataSource);
      overlayHost.setVisible(RADAR_OVERLAY_SOURCE_ID, false);
    },

    enable(viewer) {
      _enabled = true;
      if (_dataSource) _dataSource.show = true;
      overlayHost.setVisible(RADAR_OVERLAY_SOURCE_ID, true);
      // Add radar tile imagery layer if available
      if (_tileImagery) {
        viewer.scene.imageryLayers.add(_tileImagery);
      }
    },

    disable(viewer) {
      _enabled = false;
      if (_dataSource) _dataSource.show = false;
      overlayHost.clearSource(RADAR_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(RADAR_OVERLAY_SOURCE_ID, false);
      if (_tileImagery && viewer.scene.imageryLayers.contains(_tileImagery)) {
        viewer.scene.imageryLayers.remove(_tileImagery);
      }
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
        const url = `/api/gev/radar${params.toString() ? '?' + params : ''}`;
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

        // Radar cells / precipitation points
        const cells = data.cells || data.precipitation || data.features || [];
        for (const cell of cells) {
          const lon = cell.lon || cell.longitude;
          const lat = cell.lat || cell.latitude;
          if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;

          count++;
          const dbz = cell.intensity || cell.dbz || cell.value || 0;
          const color = intensityColor(dbz);
          const position = Cesium.Cartesian3.fromDegrees(lon, lat);
          const radius = (cell.radius_km || 5) * 1000;

          _dataSource.entities.add({
            id: `radar:${cell.id || count}`,
            position,
            ellipse: {
              semiMajorAxis: radius,
              semiMinorAxis: radius,
              material: new Cesium.ColorMaterialProperty(color),
              outline: false,
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            },
            properties: { dbz },
          });

          if (dbz > 25) {
            overlayEntries.push({
              id: `radar-label:${cell.id || count}`,
              position,
              variant: 'label',
              title: `${dbz.toFixed(0)} dBZ`,
              accent: color.toCssColorString(),
              priority: Math.round(dbz * 10),
              collisionGroup: 'ambient-label',
              paintLane: 'ambient-label',
              interactive: false,
              edgeFade: 'keyhole',
              horizonCull: true,
              terrainOcclusion: false,
            });
          }
        }

        // Update radar tile imagery if URL provided
        if (data.tile_url && viewer.scene) {
          // Remove old imagery
          if (_tileImagery && viewer.scene.imageryLayers.contains(_tileImagery)) {
            viewer.scene.imageryLayers.remove(_tileImagery);
          }
          // Add new radar imagery
          try {
            _tileImagery = new Cesium.ImageryLayer(
              new Cesium.UrlTemplateImageryProvider({ url: data.tile_url }),
              { alpha: 0.5 },
            );
            viewer.scene.imageryLayers.add(_tileImagery);
          } catch {
            // Tile imagery is optional — fall back to point markers
          }
        }

        if (_enabled && overlayEntries.length > 0) {
          overlayHost.setEntries(RADAR_OVERLAY_SOURCE_ID, overlayEntries.slice(0, 128), {
            cohortLimit: 64,
            collisionCapacity: 32,
            moving: false,
          });
        }

        _count = count;
        _lastUpdate = Date.now();
        _lastError = null;
        return true;
      } catch (e) {
        console.warn('[Data:Radar] Fetch error:', e);
        _lastError = 'Radar network error';
        return false;
      }
    },

    destroy(viewer) {
      _enabled = false;
      overlayHost.clearSource(RADAR_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(RADAR_OVERLAY_SOURCE_ID, false);
      if (_tileImagery && viewer.scene.imageryLayers.contains(_tileImagery)) {
        viewer.scene.imageryLayers.remove(_tileImagery);
        _tileImagery = null;
      }
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

const radarLayer = createRadarLayer();
export default radarLayer;
