import * as Cesium from 'cesium';
import {
  clearOverlaySource,
  setOverlayEntries,
  setOverlaySourceVisible,
} from '../overlays/worldOverlay.js';

/**
 * Air Quality Index (AQI) layer — real-time global air quality.
 * Fetches from the GEV proxy backend (/api/gev/aqi).
 *
 * Displays AQI stations as colour-coded points with value labels.
 * Colour scheme follows US EPA AQI categories.
 */

const AQI_OVERLAY_SOURCE_ID = 'aqi';
const DEFAULT_OVERLAY_HOST = Object.freeze({
  setEntries: setOverlayEntries,
  setVisible: setOverlaySourceVisible,
  clearSource: clearOverlaySource,
});

function aqiColor(aqi) {
  if (aqi > 300) return Cesium.Color.MAGENTA.withAlpha(0.7);     // Hazardous
  if (aqi > 200) return Cesium.Color.PURPLE.withAlpha(0.65);     // Very Unhealthy
  if (aqi > 150) return Cesium.Color.RED.withAlpha(0.6);         // Unhealthy for Sensitive Groups
  if (aqi > 100) return Cesium.Color.ORANGE.withAlpha(0.55);     // Unhealthy
  if (aqi > 50)  return Cesium.Color.YELLOW.withAlpha(0.5);      // Moderate
  return Cesium.Color.GREEN.withAlpha(0.45);                      // Good
}

function aqiLabel(aqi) {
  if (aqi > 300) return 'Hazardous';
  if (aqi > 200) return 'Very Unhealthy';
  if (aqi > 150) return 'USG';
  if (aqi > 100) return 'Unhealthy';
  if (aqi > 50)  return 'Moderate';
  return 'Good';
}

export function createAqiLayer({ overlayHost = DEFAULT_OVERLAY_HOST } = {}) {
  let _dataSource = null;
  let _count = 0;
  let _lastUpdate = null;
  let _lastError = null;
  let _enabled = false;

  const layer = {
    id: 'aqi',
    name: 'Air Quality (AQI)',
    icon: '💨',
    source: 'WAQI / OpenAQ',
    updateInterval: 600000, // 10 minutes

    init(viewer) {
      _dataSource = new Cesium.CustomDataSource('aqi');
      _dataSource.show = false;
      viewer.dataSources.add(_dataSource);
      overlayHost.setVisible(AQI_OVERLAY_SOURCE_ID, false);
    },

    enable(viewer) {
      _enabled = true;
      if (_dataSource) _dataSource.show = true;
      overlayHost.setVisible(AQI_OVERLAY_SOURCE_ID, true);
    },

    disable(viewer) {
      _enabled = false;
      if (_dataSource) _dataSource.show = false;
      overlayHost.clearSource(AQI_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(AQI_OVERLAY_SOURCE_ID, false);
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
        const url = `/api/gev/aqi${params.toString() ? '?' + params : ''}`;
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

        const stations = data.stations || data.data || data.features || [];
        for (const station of stations) {
          const lon = station.lon || station.longitude || station.location?.lon;
          const lat = station.lat || station.latitude || station.location?.lat;
          if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;

          const aqi = Number(station.aqi || station.value || station.index);
          if (!Number.isFinite(aqi)) continue;

          count++;
          const position = Cesium.Cartesian3.fromDegrees(lon, lat);
          const color = aqiColor(aqi);
          const label = aqiLabel(aqi);

          _dataSource.entities.add({
            id: `aqi:${station.id || station.station || count}`,
            position,
            point: {
              pixelSize: 8,
              color,
              outlineColor: Cesium.Color.WHITE.withAlpha(0.5),
              outlineWidth: 1,
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            },
            label: {
              text: `${Math.round(aqi)}`,
              font: '10px JetBrains Mono, monospace',
              fillColor: Cesium.Color.WHITE,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.CENTER,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            properties: { aqi, label, station: station.name || station.station },
          });

          if (aqi > 50) {
            overlayEntries.push({
              id: `aqi-label:${station.id || station.station || count}`,
              position,
              variant: 'label',
              title: `AQI ${Math.round(aqi)}`,
              details: [label, station.name || ''],
              accent: color.toCssColorString(),
              priority: Math.round(aqi * 2),
              collisionGroup: 'ambient-label',
              paintLane: 'ambient-label',
              interactive: false,
              edgeFade: 'keyhole',
              horizonCull: true,
              terrainOcclusion: false,
            });
          }
        }

        if (_enabled && overlayEntries.length > 0) {
          overlayHost.setEntries(AQI_OVERLAY_SOURCE_ID, overlayEntries.slice(0, 128), {
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
        console.warn('[Data:AQI] Fetch error:', e);
        _lastError = 'AQI network error';
        return false;
      }
    },

    destroy(viewer) {
      _enabled = false;
      overlayHost.clearSource(AQI_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(AQI_OVERLAY_SOURCE_ID, false);
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

const aqiLayer = createAqiLayer();
export default aqiLayer;
