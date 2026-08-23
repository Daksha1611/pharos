/**
 * Display vocabulary: how each signal is allowed to look.
 *
 * Two rules, both accessibility-driven and both load-bearing for the pitch.
 *
 * Colour is never the only carrier. Every urgency band ships with a text
 * label, because a projector washes out amber-on-white and roughly one man in
 * twelve cannot separate the red band from the amber one.
 *
 * Urgency and trust do not share a palette. They are different signals and
 * they routinely disagree - a fabricated report can be maximally urgent and
 * minimally trustworthy, and that combination is precisely what this system
 * claims to catch. Colouring both on the same red-amber-blue scale would make
 * the claim invisible on the screen that is supposed to demonstrate it. Trust
 * is therefore a neutral slate badge with a shield, never a heat colour.
 */

import type { UrgencyBand } from "./api";

// --------------------------------------------------------------------------
// urgency: 1-10, banded, always labelled
// --------------------------------------------------------------------------

export interface BandStyle {
  label: string;
  text: string;
  bg: string;
  border: string;
  dot: string;
  /** For map geometry, which cannot use Tailwind classes. */
  hex: string;
}

export const URGENCY: Record<UrgencyBand, BandStyle> = {
  critical: {
    label: "Critical",
    text: "text-red-700",
    bg: "bg-red-50",
    border: "border-red-200",
    dot: "bg-red-600",
    hex: "#b91c1c",
  },
  moderate: {
    label: "Moderate",
    text: "text-amber-700",
    bg: "bg-amber-50",
    border: "border-amber-200",
    dot: "bg-amber-500",
    hex: "#b45309",
  },
  low: {
    label: "Low",
    text: "text-blue-700",
    bg: "bg-blue-50",
    border: "border-blue-200",
    dot: "bg-blue-600",
    hex: "#1d4ed8",
  },
};

export function band(score: number): UrgencyBand {
  if (score >= 8) return "critical";
  if (score >= 4) return "moderate";
  return "low";
}

// --------------------------------------------------------------------------
// trust: deliberately a different visual language
// --------------------------------------------------------------------------

export interface TrustStyle {
  label: string;
  /** Neutral slate throughout - never the urgency palette. */
  text: string;
  bg: string;
  border: string;
  percent: string;
}

export function trustStyle(score: number): TrustStyle {
  const percent = `${Math.round(score * 100)}%`;
  if (score >= 0.7) {
    return {
      label: "Corroborated",
      text: "text-slate-700",
      bg: "bg-slate-100",
      border: "border-slate-300",
      percent,
    };
  }
  if (score >= 0.4) {
    return {
      label: "Partly verified",
      text: "text-slate-600",
      bg: "bg-slate-50",
      border: "border-slate-200",
      percent,
    };
  }
  return {
    // Still slate. A suspect report is flagged by its label and its hatched
    // border, not by borrowing the critical-urgency red.
    label: "Unverified",
    text: "text-slate-500",
    bg: "bg-slate-50",
    border: "border-slate-400 border-dashed",
    percent,
  };
}

// --------------------------------------------------------------------------
// needs and locations
// --------------------------------------------------------------------------

export const NEED_LABEL: Record<string, string> = {
  evacuation: "Evacuation",
  medical: "Medical",
  water: "Drinking water",
  food: "Food",
  shelter: "Shelter",
  sanitation: "Sanitation",
  missing_person: "Missing person",
  infrastructure: "Infrastructure",
};

export const NEED_ICON: Record<string, string> = {
  evacuation: "⛵",
  medical: "✚",
  water: "💧",
  food: "🍚",
  shelter: "⌂",
  sanitation: "⚑",
  missing_person: "?",
  infrastructure: "⚡",
};

/** What each resolution level entitles the map to draw, in plain words. */
export const RESOLUTION_NOTE: Record<string, string> = {
  point: "GPS-accurate — shown as a pin",
  building: "Building-accurate — shown as a pin",
  street: "Street-level — shown as an area, not a pin",
  ward: "Ward-level only — shown as a zone",
  unknown: "Could not be located — listed, never mapped",
};

export const RESOLUTION_SHORT: Record<string, string> = {
  point: "GPS",
  building: "Building",
  street: "Street",
  ward: "Ward",
  unknown: "Not located",
};

// --------------------------------------------------------------------------
// map palette: a light basemap drawn from our own geometry
// --------------------------------------------------------------------------
//
// The brief asked for OpenStreetMap or CartoDB Positron tiles. Those are HTTP
// requests to a tile server, and this demo has a hard rule that nothing may
// need the network - a grey rectangle where the map should be is not a risk
// worth running on stage. These values reproduce the Positron look from
// geometry generated locally: near-white ground, soft grey roads, muted blue
// water. `VITE_PHAROS_TILES` switches real tiles on where connectivity is
// known-good.

export const MAP = {
  background: "#f8fafc",
  land: "#f1f5f9",
  roadOpen: "#cbd5e1",
  roadArterial: "#94a3b8",
  roadFlooded: "#f59e0b",
  roadDisabled: "#dc2626",
  water: "#bfdbfe",
  waterLine: "#93c5fd",
  route: "#2563eb",
  asset: "#475569",
  assetBusy: "#2563eb",
  depot: "#64748b",
  zoneLow: "#fecaca",
  zoneMid: "#fed7aa",
  zoneHigh: "#bbf7d0",
};

// --------------------------------------------------------------------------

export function clock(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `T+${h}:${String(m).padStart(2, "0")}`;
}

export function hhmm(iso: string): string {
  return new Date(iso).toISOString().slice(11, 16);
}

export function ago(minutes: number): string {
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${Math.round(minutes)} min ago`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return m ? `${h}h ${m}m ago` : `${h}h ago`;
}
