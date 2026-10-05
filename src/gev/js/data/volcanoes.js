import * as Cesium from 'cesium';
import {
  clearOverlaySource,
  setOverlayEntries,
  setOverlaySourceVisible,
} from '../overlays/worldOverlay.js';

/**
 * Volcanic activity layer — active eruptions and ash advisories.
 * Fetches from the GEV proxy backend (/api/gev/volcanoes).
 *
 * Displays volcanic eruption plumes as cones and ash advisory regions.
 */

const VOLCANO_OVERLAY_SOURCE_ID = 'volcanoes';
const DEFAULT_OVERLAY_HOST = Object.freeze({
  setEntries: setOverlayEntries,
  setVisible: setOverlaySourceVisible,
  clearSource: clearOverlaySource,
});

const ERUPTION_COLOR = Cesium.Color.CRIMSON.withAlpha(0.65);
const ASH_COLOR = Cesium.Color.DARKGRAY.withAlpha(0.3);

export function createVolcanoesLayer({ overlayHost = DEFAULT_OVERLAY_HOST } = {}) {
  let _dataSource = null;
  let _count = 0;
  let _lastUpdate = null;
  let _lastError = null;
  let _enabled = false;

  const layer = {
    id: 'volcanoes',
    name: 'Volcanic Activity',
    icon: '🌋',
    source: 'USGS / VAAC',
    updateInterval: 300000,

    init(viewer) {
      _dataSource = new Cesium.CustomDataSource('volcanoes');
      _dataSource.show = false;
      viewer.dataSources.add(_dataSource);
      overlayHost.setVisible(VOLCANO_OVERLAY_SOURCE_ID, false);
    },

    enable(viewer) {
      _enabled = true;
      if (_dataSource) _dataSource.show = true;
      overlayHost.setVisible(VOLCANO_OVERLAY_SOURCE_ID, true);
    },

    disable(viewer) {
      _enabled = false;
      if (_dataSource) _dataSource.show = false;
      overlayHost.clearSource(VOLCANO_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(VOLCANO_OVERLAY_SOURCE_ID, false);
    },

    async update(viewer) {
      try {
        const response = await fetch('/api/gev/volcanoes');
        if (!response.ok) { _lastError = `HTTP ${response.status}`; return false; }
        const data = await response.json();
        if (data.available === false) return false;

        _dataSource.entities.removeAll();
        const overlayEntries = [];
        let count = 0;

        const volcanoes = data.volcanoes || data.features || data.items || [];
        for (const v of volcanoes) {
          const lon = v.lon || v.longitude || v.geometry?.coordinates?.[0];
          const lat = v.lat || v.latitude || v.geometry?.coordinates?.[1];
          if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;

          count++;
          const position = Cesium.Cartesian3.fromDegrees(lon, lat);
          const height = (v.elevation || v.height || 5000) * (v.erupting ? 1.2 : 1.0);
          const name = v.name || v.volcano || `Volcano ${count}`;
          const status = v.status || v.alertLevel || 'unspecified';
          const isErupting = v.erupting || status.toLowerCase().includes('erupt');

          _dataSource.entities.add({
            id: `volcano:${v.id || name}`,
            position,
            cylinder: {
              length: height,
              topRadius: isErupting ? 8000 : 4000,
              bottomRadius: 0,
              material: new Cesium.ColorMaterialProperty(
                isErupting ? ERUPTION_COLOR : Cesium.Color.DARKRED.withAlpha(0.4)
              ),
              outline: false,
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            },
            label: {
              text: name,
              font: '10px JetBrains Mono, monospace',
              fillColor: Cesium.Color.WHITE,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
              pixelOffset: new Cesium.Cartesian2(0, -10),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            properties: { name, status, erupting: isErupting, elevation: v.elevation },
          });

          overlayEntries.push({
            id: `volcano-label:${v.id || name}`,
            position,
            variant: 'label',
            title: name,
            details: [status.toUpperCase(), isErupting ? '🔴 ERUPTING' : 'Monitoring'],
            accent: isErupting ? ERUPTION_COLOR.toCssColorString() : Cesium.Color.DARKRED.toCssColorString(),
            priority: isErupting ? 900 : 300,
            collisionGroup: 'ambient-label',
            paintLane: 'ambient-label',
            interactive: false,
            edgeFade: 'keyhole',
            horizonCull: true,
            terrainOcclusion: false,
          });
        }

        // Process ash advisories
        const advisories = data.advisories || data.ash_advisories || [];
        for (const adv of advisories) {
          const polygon = adv.polygon || adv.coordinates;
          if (!Array.isArray(polygon) || polygon.length < 3) continue;

          count++;
          const positions = polygon.map((pt) => {
            const aLon = Array.isArray(pt) ? pt[0] : pt.lon || pt.longitude;
            const aLat = Array.isArray(pt) ? pt[1] : pt.lat || pt.latitude;
            return Cesium.Cartesian3.fromDegrees(aLon, aLat);
          });
          positions.push(positions[0]); // close polygon

          _dataSource.entities.add({
            id: `ash-adv:${adv.id || count}`,
            polygon: {
              hierarchy: new Cesium.PolygonHierarchy(positions),
              material: ASH_COLOR,
              outline: true,
              outlineColor: Cesium.Color.GRAY.withAlpha(0.5),
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            },
            properties: { type: 'ash_advisory', volcano: adv.volcano },
          });
        }

        if (_enabled && overlayEntries.length > 0) {
          overlayHost.setEntries(VOLCANO_OVERLAY_SOURCE_ID, overlayEntries, {
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
        console.warn('[Data:Volcanoes] Fetch error:', e);
        _lastError = 'Volcano network error';
        return false;
      }
    },

    destroy(viewer) {
      _enabled = false;
      overlayHost.clearSource(VOLCANO_OVERLAY_SOURCE_ID);
      overlayHost.setVisible(VOLCANO_OVERLAY_SOURCE_ID, false);
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

const volcanoesLayer = createVolcanoesLayer();
export default volcanoesLayer;
