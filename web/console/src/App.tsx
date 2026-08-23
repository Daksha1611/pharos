/**
 * The operations console.
 *
 * One screen: a sorted queue on the left, the live map in the middle, the full
 * record of whatever is selected on the right, and the numbers along the
 * bottom. No tabs, no hunting across channels.
 *
 * Replans arrive over a WebSocket rather than a timer. The live replan is the
 * best thing this system does, and a poll makes it look like a page refresh.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";
import { ControlBar } from "./components/ControlBar";
import { DemandQueue, EMPTY_FILTERS, type Filters } from "./components/DemandQueue";
import { DetailPanel } from "./components/DetailPanel";
import { MapView } from "./components/MapView";
import { MetricsStrip } from "./components/MetricsStrip";

export default function App() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [busy, setBusy] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [showZones, setShowZones] = useState(false);

  const status = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    refetchInterval: (q) => (q.state.data?.phase === "ready" ? false : 1200),
  });
  const ready = status.data?.phase === "ready";

  const scenario = useQuery({ queryKey: ["scenario"], queryFn: api.scenario, enabled: ready });
  const plan = useQuery({ queryKey: ["plan"], queryFn: api.plan, enabled: ready });
  const assets = useQuery({ queryKey: ["assets"], queryFn: api.assets, enabled: ready });
  const roads = useQuery({ queryKey: ["roads"], queryFn: api.roads, enabled: ready });
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: api.metrics, enabled: ready });
  const events = useQuery({ queryKey: ["events"], queryFn: api.events, enabled: ready });
  const zones = useQuery({
    queryKey: ["zones"],
    queryFn: api.zones,
    enabled: ready && showZones,
  });

  const demands = useQuery({
    queryKey: ["demands", filters],
    queryFn: () => api.demands(queryFor(filters)),
    enabled: ready,
  });

  const detail = useQuery({
    queryKey: ["demand", selected],
    queryFn: () => api.demand(selected!),
    enabled: ready && !!selected,
  });

  // -- live replan over the socket ----------------------------------------
  const invalidate = useCallback(() => {
    for (const k of ["status", "plan", "assets", "demands", "metrics", "events", "zones", "demand"]) {
      qc.invalidateQueries({ queryKey: [k] });
    }
  }, [qc]);

  useEffect(() => {
    if (!ready) return;
    const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
    const sock = new WebSocket(url);
    sock.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "plan" || msg.type === "roads") {
        // Invalidate on the event, not on a timer. A poll would make the
        // replan look like a refresh instead of a decision.
        invalidate();
        if (msg.type === "roads") qc.invalidateQueries({ queryKey: ["roads"] });
      }
    };
    return () => sock.close();
  }, [ready, invalidate, qc]);

  // -- controls ------------------------------------------------------------
  const act = useCallback(
    async (name: string, fn: () => Promise<unknown>) => {
      setBusy(name);
      try {
        await fn();
        invalidate();
      } finally {
        setBusy(null);
      }
    },
    [invalidate],
  );

  const playRef = useRef(false);
  useEffect(() => {
    playRef.current = playing;
    if (!playing) return;
    let cancelled = false;
    (async () => {
      // Sequential, not on an interval: a replan takes a couple of seconds and
      // stacking them would queue solves faster than they finish.
      while (!cancelled && playRef.current) {
        const s = await api.status();
        if ((s.clock_minutes ?? 0) >= (s.horizon_minutes ?? 0)) break;
        await api.tick();
        invalidate();
        await new Promise((r) => setTimeout(r, 400));
      }
      if (!cancelled) setPlaying(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [playing, invalidate]);

  // -- loading -------------------------------------------------------------
  if (!ready) {
    return <Loading detail={status.data?.detail} progress={status.data?.progress ?? 0} error={status.data?.phase === "error"} />;
  }

  const visible = demands.data?.demands ?? [];
  const centre = scenario.data?.centre ?? [9.9312, 76.2673];

  return (
    <div className="flex h-screen flex-col bg-ink-900 text-slate-200">
      <ControlBar
        status={status.data}
        plan={plan.data}
        busy={busy}
        playing={playing}
        showZones={showZones}
        onToggleZones={() => setShowZones((v) => !v)}
        onTick={() => act("tick", api.tick)}
        onPlay={() => setPlaying((v) => !v)}
        onEquity={(w) => act("equity", () => api.setEquity(w))}
        onBridge={() => act("bridge", api.breakBridge)}
        onRedteam={(a) => act("redteam", () => api.redteam(a))}
        onConfidence={(c) => act("confidence", () => api.confidence(c))}
        onReset={() => act("reset", api.reset)}
      />

      <div className="grid min-h-0 flex-1 grid-cols-[320px_1fr_380px]">
        <DemandQueue
          page={demands.data}
          selected={selected}
          onSelect={setSelected}
          filters={filters}
          setFilters={setFilters}
        />

        <div className="relative min-w-0">
          <MapView
            centre={centre as [number, number]}
            roads={roads.data}
            zones={zones.data?.zones}
            demands={visible}
            assets={assets.data}
            plan={plan.data}
            selected={selected}
            showZones={showZones}
            onSelect={setSelected}
          />
          <Legend counts={demands.data?.counts} roads={roads.data?.counts} />
        </div>

        <DetailPanel
          detail={detail.data}
          loading={detail.isLoading}
          onClose={() => setSelected(null)}
        />
      </div>

      <MetricsStrip
        metrics={metrics.data}
        plan={plan.data}
        assets={assets.data}
        events={events.data}
      />
    </div>
  );
}

// --------------------------------------------------------------------------

function queryFor(f: Filters): string {
  const p = new URLSearchParams({ limit: "250" });
  if (f.status) p.set("status", f.status);
  if (f.need) p.set("need", f.need);
  if (f.search) p.set("search", f.search);
  if (f.band === "lowconf") p.set("max_confidence", "0.55");
  if (f.band === "lowtrust") p.set("min_trust", "0");
  if (f.band === "unlocated") p.set("resolution", "unknown");
  return p.toString();
}

function Legend({
  counts,
  roads,
}: {
  counts: { by_resolution: Record<string, number>; unlocatable: number } | undefined;
  roads: { open: number; flooded: number; disabled: number } | undefined;
}) {
  return (
    <div className="pointer-events-none absolute left-3 top-3 space-y-2 rounded border border-ink-700
                    bg-ink-900/85 p-2.5 text-[10px] backdrop-blur">
      <div>
        <div className="mb-1 font-semibold uppercase tracking-wider text-slate-500">
          Location precision
        </div>
        <Row swatch={<span className="h-2 w-2 rounded-full bg-signal-low" />}
             label="pin — GPS or building" n={(counts?.by_resolution.point ?? 0) + (counts?.by_resolution.building ?? 0)} />
        <Row swatch={<span className="h-2.5 w-2.5 rounded-full border border-signal-low bg-signal-low/25" />}
             label="circle — street-level" n={counts?.by_resolution.street} />
        <Row swatch={<span className="h-3 w-3 rounded-full border border-signal-low/60 bg-signal-low/10" />}
             label="hex — ward only" n={counts?.by_resolution.ward} />
        <Row swatch={<span className="h-2 w-2 rounded-sm border border-slate-600" />}
             label="not drawn — no location" n={counts?.unlocatable} />
      </div>
      <div className="border-t border-ink-700 pt-1.5">
        <div className="mb-1 font-semibold uppercase tracking-wider text-slate-500">Roads</div>
        <Row swatch={<span className="h-px w-3 bg-[#2b3448]" />} label="passable" n={roads?.open} />
        <Row swatch={<span className="h-px w-3 bg-[#c96a1f]" />} label="flooded — boats only" n={roads?.flooded} />
        <Row swatch={<span className="h-px w-3 bg-[#ff3b3b]" />} label="collapsed" n={roads?.disabled} />
      </div>
    </div>
  );
}

function Row({ swatch, label, n }: { swatch: React.ReactNode; label: string; n?: number }) {
  return (
    <div className="flex items-center gap-1.5 text-slate-400">
      <span className="flex w-3 justify-center">{swatch}</span>
      <span>{label}</span>
      {n !== undefined && <span className="ml-auto pl-2 font-mono text-slate-600">{n}</span>}
    </div>
  );
}

function Loading({
  detail,
  progress,
  error,
}: {
  detail?: string;
  progress: number;
  error?: boolean;
}) {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-4 bg-ink-900 text-slate-300">
      <div className="text-center">
        <h1 className="text-2xl font-bold tracking-tight text-slate-100">PHAROS</h1>
        <p className="mt-1 text-xs uppercase tracking-[0.2em] text-slate-600">
          Prioritization and Hazard-Aware Resource Orchestration
        </p>
      </div>
      {error ? (
        <p className="max-w-md text-center text-xs text-signal-critical">{detail}</p>
      ) : (
        <>
          <div className="h-1 w-64 overflow-hidden rounded-full bg-ink-700">
            <div
              className="h-full rounded-full bg-signal-info transition-all duration-500"
              style={{ width: `${Math.max(4, progress * 100)}%` }}
            />
          </div>
          <p className="text-xs text-slate-500">{detail || "starting"}</p>
          <p className="max-w-sm text-center text-[11px] leading-relaxed text-slate-700">
            Generating the scenario and running every message through intake. This runs once, on
            this machine, with no network.
          </p>
        </>
      )}
    </div>
  );
}
