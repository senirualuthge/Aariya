import * as Cesium from 'cesium';
import {
  clearOverlaySource,
  setOverlayEntries,
  setOverlaySourceVisible,
} from '../overlays/worldOverlay.js';

/**
 * Space weather layer — solar flare alerts and geomagnetic storm tracking.
 * Fetches from the GEV proxy backend (/api/gev/space-weather).
 *
 * Displays solar events as positioned markers and geomagnetic storm
 * intensity as a global overlay.
 */

const SPACE_WEATHER_OVERLAY_SOURCE_ID = 'spaceWeather';
const DEFAULT_OVERLAY_HOST = Object.freeze({
  setEntries: setOverlayEntries,
  setVisible: setOverlaySourceVisible,
  clearSource: clearOverlaySource,
});

const FLARE_COLORS = {
  X: Cesium.Color.RED.withAlpha(0.8),
  M: Cesium.Color.ORANGE.withAlpha(0.7),
  C: Cesium.Color.YELLOW.withAlpha(0.6),
  B: Cesium.Color.CYAN.withAlpha(0.5),
  A: Cesium.Color.GREEN.withAlpha(0.4),
};

const STORM_COLORS = {
  G5: Cesium.Color.MAGENTA.withAlpha(0.6),
  G4: Cesium.Color.PURPLE.withAlpha(0.55),
  G3: Cesium.Color.RED.withAlpha(0.5),
  G2: Cesium.Color.ORANGE.withAlpha(0.45),
  G1: Cesium.Color.YELLOW.withAlpha(0.4),
};

function flareColor(class_) {
  return FLARE_COLORS[class_] || FLARE_COLORS.A;
}

function stormColor(kp) {
  if (kp >= 9) return STORM_COLORS.G5;
  if (kp >= 7) return STORM_COLORS.G4;
  if (kp >= 6) return STORM_COLORS.G3;
  if (kp >= 5) return STORM_COLORS.G2;
  if (kp >= 4) return STORM_COLORS.G1;
  return Cesium.Color.WHITE.withAlpha(0.3);
}

export function createSpaceWeatherLayer({ overlayHost = DEFAULT_OVERLAY_HOST } = {}) {
  let _dataSource = null;
  let _count = 0;
  let _lastUpdate = null;
  let _lastError = null;
  let _enabled = false;

  const layer = {
    id: 'spaceWeather',
    name: 'Space Weather',
    icon: '☀️',
    source: 'NOAA SWPC',
    updateInterval: 300000,

    init(viewer) {
      _dataSource = new Cesium.CustomDataSource('spaceWeather');
      _dataSource.show = false;
      viewer.dataSources.add(_dataSource);
      overlayHost.setVisible(SPACE_WEATHER_OVERLAY_SOURCE_ID, false);
    },

    enable(viewer) {
      _enabled = true;
      if (_dataSource) _dataSource.show = true;
      overlayHost.setVisible(SPACE_WEATHER_OVERLAY_SOURCE_ID, true);
    },

    disable(viewer) {
      _enabled = false;
      if (_dataSource) _dataSource.show = false;
      overlayHost.clearSource(SPACE_WEATHER_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(SPACE_WEATHER_OVERLAY_SOURCE_ID, false);
    },

    async update(viewer) {
      try {
        const response = await fetch('/api/gev/space-weather');
        if (!response.ok) { _lastError = `HTTP ${response.status}`; return false; }
        const data = await response.json();
        if (data.available === false) return false;

        _dataSource.entities.removeAll();
        const overlayEntries = [];
        let count = 0;

        // Solar flares — position at the Sun's sub-point (approximate)
        const flares = data.flares || data.solar_flares || [];
        for (const flare of flares) {
          count++;
          // Flares are typically at the Sun's position; approximate as sub-solar point
          const lon = flare.lon || flare.heliographic_lon || 0;
          const lat = flare.lat || flare.heliographic_lat || 0;
          const position = Cesium.Cartesian3.fromDegrees(lon, lat, 36000000); // ~36M km
          const class_ = flare.class || flare.class_type || 'A';
          const color = flareColor(class_);

          _dataSource.entities.add({
            id: `flare:${flare.id || count}`,
            position,
            point: {
              pixelSize: 12,
              color,
              outlineColor: Cesium.Color.WHITE.withAlpha(0.7),
              outlineWidth: 2,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            label: {
              text: `${class_}${flare.magnitude || ''}`,
              font: '11px JetBrains Mono, monospace',
              fillColor: Cesium.Color.WHITE,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.CENTER,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            properties: { type: 'flare', class: class_, magnitude: flare.magnitude },
          });

          overlayEntries.push({
            id: `flare-label:${flare.id || count}`,
            position,
            variant: 'label',
            title: `${class_}${flare.magnitude || ''} Flare`,
            details: [flare.region || '', flare.time || ''],
            accent: color.toCssColorString(),
            priority: class_ === 'X' ? 1000 : class_ === 'M' ? 800 : 400,
            collisionGroup: 'ambient-label',
            paintLane: 'ambient-label',
            interactive: false,
            edgeFade: 'keyhole',
            horizonCull: false,
            terrainOcclusion: false,
          });
        }

        // Geomagnetic storms — display at relevant observatory locations
        const storms = data.storms || data.geomagnetic_storms || [];
        for (const storm of storms) {
          count++;
          // Approximate position for geomagnetic activity
          const lon = storm.lon || storm.longitude || 0;
          const lat = storm.lat || storm.latitude || 50; // Auroral zone
          const kp = storm.kp || storm.kp_index || 0;
          const position = Cesium.Cartesian3.fromDegrees(lon, lat, 200000);
          const color = stormColor(kp);

          _dataSource.entities.add({
            id: `storm:${storm.id || count}`,
            position,
            point: {
              pixelSize: 10,
              color,
              outlineColor: Cesium.Color.WHITE.withAlpha(0.5),
              outlineWidth: 1,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            label: {
              text: `Kp=${kp}`,
              font: '10px JetBrains Mono, monospace',
              fillColor: Cesium.Color.WHITE,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
              pixelOffset: new Cesium.Cartesian2(0, -12),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            properties: { type: 'geomagnetic_storm', kp },
          });

          overlayEntries.push({
            id: `storm-label:${storm.id || count}`,
            position,
            variant: 'label',
            title: `Kp ${kp}`,
            details: [storm.class || storm['等级'] || '', storm.effect || ''],
            accent: color.toCssColorString(),
            priority: kp >= 7 ? 1000 : kp >= 5 ? 800 : kp >= 4 ? 500 : 200,
            collisionGroup: 'ambient-label',
            paintLane: 'ambient-label',
            interactive: false,
            edgeFade: 'keyhole',
            horizonCull: false,
            terrainOcclusion: false,
          });
        }

        if (_enabled && overlayEntries.length > 0) {
          overlayHost.setEntries(SPACE_WEATHER_OVERLAY_SOURCE_ID, overlayEntries, {
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
        console.warn('[Data:SpaceWeather] Fetch error:', e);
        _lastError = 'Space weather network error';
        return false;
      }
    },

    destroy(viewer) {
      _enabled = false;
      overlayHost.clearSource(SPACE_WEATHER_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(SPACE_WEATHER_OVERLAY_SOURCE_ID, false);
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

const spaceWeatherLayer = createSpaceWeatherLayer();
export default spaceWeatherLayer;
