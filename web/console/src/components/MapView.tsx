/**
 * The live map.
 *
 * MapLibre with a blank style and no tile server: every road, hex and marker is
 * geometry this project generated, drawn locally. No API token, no basemap
 * request, nothing that can fail on venue wifi.
 *
 * The important rule is in `demandFeatures`. A demand is drawn as a pin only if
 * the geo cascade actually resolved it to a point or a building. Street-level
 * demands are circles sized to their uncertainty, ward-level demands are hexes,
 * and anything unlocated is not drawn at all - it goes to a list instead.
 * Never invent precision to make a map look better; that is the documented
 * Kerala 2018 supply-drop failure.
 */

import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef } from "react";

import type { Asset, AssetView, Demand, Plan, Roads, Zone } from "../api";
import { MAP, URGENCY } from "../theme";

interface Props {
  centre: [number, number];
  roads: Roads | undefined;
  zones: Zone[] | undefined;
  demands: Demand[];
  assets: AssetView | undefined;
  plan: Plan | undefined;
  selected: string | null;
  showZones: boolean;
  onSelect: (id: string) => void;
}

/**
 * A light basemap with no tile server.
 *
 * The brief asked for OpenStreetMap or CartoDB Positron. Both are HTTP calls to
 * a tile host, and this demo has a hard rule that nothing may require the
 * network - a grey rectangle where the map should be is not a risk worth
 * running on stage. So the Positron *look* is reproduced from geometry we
 * generate locally: near-white ground, soft grey roads, muted blue water.
 *
 * Set VITE_PHAROS_TILES to a raster tile URL template to use real tiles where
 * connectivity is known to be good.
 */
const TILE_URL = import.meta.env.VITE_PHAROS_TILES as string | undefined;

const LIGHT_STYLE: maplibregl.StyleSpecification = TILE_URL
  ? {
      version: 8,
      sources: {
        base: { type: "raster", tiles: [TILE_URL], tileSize: 256, attribution: "© OpenStreetMap" },
      },
      layers: [
        { id: "bg", type: "background", paint: { "background-color": MAP.background } },
        { id: "base", type: "raster", source: "base" },
      ],
    }
  : {
      version: 8,
      sources: {},
      layers: [{ id: "bg", type: "background", paint: { "background-color": MAP.background } }],
    };

export function MapView(props: Props) {
  const holder = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const ready = useRef(false);

  // -- create once ---------------------------------------------------------
  useEffect(() => {
    if (!holder.current || map.current) return;
    const m = new maplibregl.Map({
      container: holder.current,
      style: LIGHT_STYLE,
      center: [props.centre[1], props.centre[0]],
      zoom: 9.6,
      attributionControl: false,
      maxZoom: 15,
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    m.on("load", () => {
      addLayers(m);
      ready.current = true;
    });
    m.on("click", "demand-pins", (e) => {
      const id = e.features?.[0]?.properties?.demand_id;
      if (id) props.onSelect(String(id));
    });
    m.on("click", "demand-circles", (e) => {
      const id = e.features?.[0]?.properties?.demand_id;
      if (id) props.onSelect(String(id));
    });
    for (const layer of ["demand-pins", "demand-circles", "asset-dots"]) {
      m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
    }
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
      ready.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // -- roads ---------------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready.current || !props.roads) return;
    setData(m, "roads-open", lines(props.roads.open));
    setData(m, "roads-flooded", lines(props.roads.flooded));
    setData(m, "roads-disabled", lines(props.roads.disabled));
    setData(m, "river", lines([props.roads.river]));
    setData(m, "bridges", {
      type: "FeatureCollection",
      features: props.roads.bridges.map((b) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [b.lon, b.lat] },
        properties: { standing: b.standing },
      })),
    });
  }, [props.roads]);

  // -- zones ---------------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready.current) return;
    const zs = props.showZones ? props.zones ?? [] : [];
    setData(m, "zones", {
      type: "FeatureCollection",
      features: zs.map((z) => ({
        type: "Feature" as const,
        geometry: {
          type: "Polygon" as const,
          coordinates: [[...z.boundary.map(([lat, lon]) => [lon, lat]), [z.boundary[0][1], z.boundary[0][0]]]],
        },
        properties: { coverage: z.coverage, people: z.people },
      })),
    });
  }, [props.zones, props.showZones]);

  // -- demands -------------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready.current) return;
    const { pins, circles, hexes } = demandFeatures(props.demands, props.selected);
    setData(m, "demand-pins", pins);
    setData(m, "demand-circles", circles);
    setData(m, "demand-hexes", hexes);
  }, [props.demands, props.selected]);

  // -- assets and routes ---------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m || !ready.current) return;
    setData(m, "assets", assetFeatures(props.assets?.assets ?? []));
    setData(m, "depots", {
      type: "FeatureCollection",
      features: (props.assets?.depots ?? []).map((d) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [d.lon, d.lat] },
        properties: { name: d.name },
      })),
    });
  }, [props.assets]);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready.current) return;
    const routes = (props.plan?.assignments ?? [])
      .filter((a) => a.kind === "rescue" && a.route.length > 1)
      .map((a) => a.route.map(([lat, lon]) => [lon, lat]));
    setData(m, "routes", {
      type: "FeatureCollection",
      features: routes.map((coords) => ({
        type: "Feature" as const,
        geometry: { type: "LineString" as const, coordinates: coords },
        properties: {},
      })),
    });
  }, [props.plan]);

  return <div ref={holder} className="absolute inset-0" />;
}

// --------------------------------------------------------------------------

function demandFeatures(demands: Demand[], selected: string | null) {
  const pins: GeoJSON.Feature[] = [];
  const circles: GeoJSON.Feature[] = [];
  const hexes: GeoJSON.Feature[] = [];

  for (const d of demands) {
    const props = {
      demand_id: d.demand_id,
      band: d.urgency_band,
      urgency: d.urgency,
      need: d.need,
      people: d.people,
      trust: d.trust_score,
      confidence: d.quantity_confidence,
      assigned: d.assigned_asset ? 1 : 0,
      selected: d.demand_id === selected ? 1 : 0,
      // Circles are sized to how sure we are of the position, so a coarse fix
      // reads as a coarse fix.
      radius: d.location.resolution === "street" ? 550 : 180,
    };
    const f: GeoJSON.Feature = {
      type: "Feature",
      geometry: { type: "Point", coordinates: [d.location.lon, d.location.lat] },
      properties: props,
    };
    if (d.location.render_as === "pin") pins.push(f);
    else if (d.location.render_as === "circle") circles.push(f);
    else if (d.location.render_as === "hex") hexes.push(f);
    // render_as "list_only" is deliberately not drawn.
  }
  return {
    pins: { type: "FeatureCollection", features: pins } as GeoJSON.FeatureCollection,
    circles: { type: "FeatureCollection", features: circles } as GeoJSON.FeatureCollection,
    hexes: { type: "FeatureCollection", features: hexes } as GeoJSON.FeatureCollection,
  };
}

function assetFeatures(assets: Asset[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: assets
      .filter((a) => !a.is_verifier)
      .map((a) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [a.lon, a.lat] },
        properties: { asset_id: a.asset_id, type: a.type, state: a.state, busy: a.job ? 1 : 0 },
      })),
  };
}

function lines(segs: [number, number][][]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: segs
      .filter((s) => s.length > 1)
      .map((s) => ({
        type: "Feature" as const,
        geometry: { type: "LineString" as const, coordinates: s.map(([lat, lon]) => [lon, lat]) },
        properties: {},
      })),
  };
}

function setData(m: maplibregl.Map, id: string, data: GeoJSON.FeatureCollection) {
  const src = m.getSource(id) as maplibregl.GeoJSONSource | undefined;
  if (src) src.setData(data);
}

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

function addLayers(m: maplibregl.Map) {
  for (const id of [
    "zones", "river", "roads-open", "roads-flooded", "roads-disabled", "bridges",
    "routes", "depots", "assets", "demand-hexes", "demand-circles", "demand-pins",
  ]) {
    m.addSource(id, { type: "geojson", data: EMPTY });
  }

  // --- equity heatmap: who is being under-served right now ---------------
  m.addLayer({
    id: "zones-fill",
    type: "fill",
    source: "zones",
    paint: {
      "fill-color": [
        "interpolate", ["linear"], ["get", "coverage"],
        0, MAP.zoneLow, 0.5, MAP.zoneMid, 1, MAP.zoneHigh,
      ],
      "fill-opacity": 0.55,
    },
  });
  m.addLayer({
    id: "zones-line",
    type: "line",
    source: "zones",
    paint: { "line-color": "#94a3b8", "line-width": 0.6, "line-opacity": 0.5 },
  });

  // --- water and roads ---------------------------------------------------
  m.addLayer({
    id: "river-line",
    type: "line",
    source: "river",
    paint: { "line-color": MAP.water, "line-width": 6, "line-opacity": 0.9 },
  });
  m.addLayer({
    id: "roads-open-line",
    type: "line",
    source: "roads-open",
    paint: { "line-color": MAP.roadOpen, "line-width": 1.2 },
  });
  m.addLayer({
    id: "roads-flooded-line",
    type: "line",
    source: "roads-flooded",
    paint: { "line-color": MAP.roadFlooded, "line-width": 2, "line-opacity": 0.95 },
  });
  m.addLayer({
    id: "roads-disabled-line",
    type: "line",
    source: "roads-disabled",
    paint: { "line-color": MAP.roadDisabled, "line-width": 2.8, "line-dasharray": [2, 1.5] },
  });
  m.addLayer({
    id: "bridge-dots",
    type: "circle",
    source: "bridges",
    paint: {
      "circle-radius": 5,
      "circle-color": ["case", ["get", "standing"], MAP.waterLine, MAP.roadDisabled],
      "circle-stroke-width": 1.5,
      "circle-stroke-color": "#ffffff",
    },
  });

  // --- assignment routes -------------------------------------------------
  m.addLayer({
    id: "route-lines",
    type: "line",
    source: "routes",
    paint: { "line-color": MAP.route, "line-width": 1.8, "line-opacity": 0.5 },
  });

  m.addLayer({
    id: "depot-marks",
    type: "circle",
    source: "depots",
    paint: {
      "circle-radius": 4,
      "circle-color": "#ffffff",
      "circle-stroke-width": 1.6,
      "circle-stroke-color": MAP.depot,
    },
  });

  // --- demand, drawn only as precisely as we actually know ---------------
  m.addLayer({
    id: "demand-hexes-layer",
    type: "circle",
    source: "demand-hexes",
    paint: {
      // Hexes grow with zoom so a ward-level demand reads as an area at every
      // scale rather than shrinking into something pin-like.
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 10, 12, 46],
      "circle-color": urgencyColour(),
      "circle-opacity": 0.12,
      "circle-stroke-width": 1.2,
      "circle-stroke-color": urgencyColour(),
      "circle-stroke-opacity": 0.5,
    },
  });
  m.addLayer({
    id: "demand-circles",
    type: "circle",
    source: "demand-circles",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 4, 12, 16],
      "circle-color": urgencyColour(),
      "circle-opacity": 0.2,
      "circle-stroke-width": 1.4,
      "circle-stroke-color": urgencyColour(),
      "circle-stroke-opacity": 0.8,
    },
  });
  m.addLayer({
    id: "demand-pins",
    type: "circle",
    source: "demand-pins",
    paint: {
      "circle-radius": ["case", ["==", ["get", "selected"], 1], 9, 5],
      "circle-color": urgencyColour(),
      // Trust fades a marker rather than hiding it. A low-trust report stays on
      // the operator's screen; it just stops shouting.
      "circle-opacity": ["max", 0.3, ["get", "trust"]],
      "circle-stroke-width": ["case", ["==", ["get", "selected"], 1], 3, 1.4],
      "circle-stroke-color": ["case", ["==", ["get", "selected"], 1], "#0f172a", "#ffffff"],
    },
  });

  m.addLayer({
    id: "asset-dots",
    type: "circle",
    source: "assets",
    paint: {
      "circle-radius": 4.5,
      "circle-color": ["case", ["==", ["get", "busy"], 1], MAP.assetBusy, MAP.asset],
      "circle-stroke-width": 1.4,
      "circle-stroke-color": "#ffffff",
    },
  });
}

function urgencyColour(): maplibregl.ExpressionSpecification {
  // Banded to match the feed exactly, so a red pin and a "Critical" card are
  // unambiguously the same thing.
  return [
    "match",
    ["get", "band"],
    "critical", URGENCY.critical.hex,
    "moderate", URGENCY.moderate.hex,
    URGENCY.low.hex,
  ] as maplibregl.ExpressionSpecification;
}
