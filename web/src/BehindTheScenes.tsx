import { Activity, AlertTriangle, ChevronRight, Cpu, Radio } from "lucide-react";
import type { BridgeEvent, Health } from "./api";

const STATE_TONE: Record<string, string> = {
  STOPPED: "bg-alert text-white",
  SAFETY_RECHECK: "bg-amber-500 text-ink-900",
  SAFETY_CHECK: "bg-amber-500 text-ink-900",
  FIXED: "bg-sage text-white",
  HANDOFF: "bg-clay-600 text-white",
};

function compactArgs(args: Record<string, unknown>): string {
  const rest = Object.entries(args).filter(([key]) => key !== "session_id");
  if (!rest.length) return "";
  const text = rest.map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join(", ");
  return text.length > 70 ? `${text.slice(0, 67)}…` : text;
}

function Row({ event }: { event: BridgeEvent }) {
  switch (event.type) {
    case "turn_start":
      return (
        <li className="mt-2 flex gap-1 border-t border-clay-200 pt-2 text-ink-500 dark:border-ink-700 dark:text-clay-200/70">
          <ChevronRight size={14} className="mt-0.5 shrink-0" />
          <span className="min-w-0 break-words">
            <b>{event.member_id}</b> ({event.language}): {String(event.text).slice(0, 80)}
          </span>
        </li>
      );
    case "tool_call": {
      const bad = !event.ok || event.refused;
      return (
        <li
          data-testid="tool-row"
          data-name={event.name}
          data-refused={event.refused ? "1" : "0"}
          data-ok={event.ok ? "1" : "0"}
          className={`rounded-lg px-2 py-1 ${bad ? "bg-red-50 dark:bg-red-950/40" : "bg-white/60 dark:bg-ink-800/70"}`}
        >
          <div className="flex items-baseline justify-between gap-2">
            <code className="font-mono font-bold text-ink-900 dark:text-clay-50">{event.name}</code>
            <span className="shrink-0 text-ink-500 dark:text-clay-200/70">{event.ms} ms</span>
          </div>
          {compactArgs(event.arguments ?? {}) && (
            <div className="break-words font-mono text-[11px] text-ink-500 dark:text-clay-200/70">
              {compactArgs(event.arguments)}
            </div>
          )}
          <div className="mt-0.5 flex flex-wrap gap-1">
            {event.state && (
              <span className="rounded bg-clay-100 px-1.5 font-mono text-[10px] dark:bg-ink-700">→ {event.state}</span>
            )}
            {event.refused && (
              <span className="rounded bg-alert px-1.5 text-[10px] font-bold text-white">refused: {event.reason}</span>
            )}
            {event.error && !event.refused && (
              <span className="rounded bg-alert px-1.5 text-[10px] font-bold text-white">error</span>
            )}
          </div>
        </li>
      );
    }
    case "turn_end":
      return (
        <li className="text-[11px] text-sage dark:text-emerald-300">
          ✓ {event.model ?? "no model"} · {((event.elapsed_ms ?? 0) / 1000).toFixed(1)} s
          {event.error ? ` · ${event.error}` : ""}
        </li>
      );
    case "reset":
      return <li className="text-[11px] italic text-ink-500">demo reset</li>;
    default:
      return (
        <li className="flex items-center gap-1 text-[11px] text-amber-700 dark:text-amber-300">
          <AlertTriangle size={12} /> {event.type.replace("model_", "model ")} {event.model ?? ""}
          {event.next ? ` → ${event.next}` : ""}
        </li>
      );
  }
}

export function BehindTheScenes(props: {
  events: BridgeEvent[];
  state: string | null;
  sessionId: string | null;
  model: string | null;
  health: Health | null;
  connected: boolean;
}) {
  const { events, state, sessionId, model, health, connected } = props;
  return (
    <aside
      data-testid="panel"
      className="flex h-full min-h-0 w-full flex-col gap-3 rounded-3xl border border-clay-200 bg-clay-50/90 p-4 text-xs text-ink-800 dark:border-ink-700 dark:bg-ink-800/80 dark:text-clay-100"
    >
      <header className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest">
          <Activity size={16} /> Behind the scenes
        </h2>
        <span title={connected ? "live" : "reconnecting"} className="flex items-center gap-1">
          <Radio size={14} className={connected ? "text-sage" : "text-ink-500"} />
          {connected ? "live" : "offline"}
        </span>
      </header>
      <dl className="grid grid-cols-2 gap-2">
        <div className="col-span-2 rounded-xl bg-white/70 p-2 dark:bg-ink-900/60">
          <dt className="text-[10px] font-semibold uppercase tracking-wider text-ink-500">Repair engine state</dt>
          <dd>
            <span
              data-testid="engine-state"
              className={`mt-1 inline-block rounded-full px-3 py-0.5 font-mono text-sm font-bold ${
                STATE_TONE[state ?? ""] ?? "bg-clay-200 text-ink-900"
              }`}
            >
              {state ?? "NO REPAIR"}
            </span>
          </dd>
        </div>
        <div className="rounded-xl bg-white/70 p-2 dark:bg-ink-900/60">
          <dt className="text-[10px] font-semibold uppercase tracking-wider text-ink-500">Session</dt>
          <dd className="truncate font-mono">{sessionId ?? "none"}</dd>
        </div>
        <div className="rounded-xl bg-white/70 p-2 dark:bg-ink-900/60">
          <dt className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-ink-500">
            <Cpu size={11} /> Model
          </dt>
          <dd className="truncate font-mono">{model?.split(":").pop() ?? "none yet"}</dd>
        </div>
        <div className="col-span-2 rounded-xl bg-white/70 p-2 dark:bg-ink-900/60">
          <dt className="text-[10px] font-semibold uppercase tracking-wider text-ink-500">Kilta MCP server</dt>
          <dd data-testid="mcp-status">
            {health?.mcp.reachable
              ? `Streamable HTTP · spec ${health.mcp.protocol_version} · ${health.mcp.tools?.length} tools`
              : "not reachable"}
          </dd>
        </div>
      </dl>
      <ul
        data-testid="tool-log"
        className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1"
        ref={(node) => {
          if (node) node.scrollTop = node.scrollHeight;
        }}
      >
        {events.length === 0 && <li className="text-ink-500">Tool calls appear here as Kilta works.</li>}
        {events.map((event) => (
          <Row key={event.seq} event={event} />
        ))}
      </ul>
    </aside>
  );
}
