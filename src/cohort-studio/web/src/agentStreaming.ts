import type { StudioAgentResponse } from "./api";

type SummaryValue = string | number | boolean | null | SummaryValue[] | { [key: string]: SummaryValue };

export interface AgentProgress {
  type: string;
  run_id?: string;
  stage?: string;
  tool_name?: string;
  turn?: number;
  reply?: string;
  session_id?: string;
  /** text_delta: a chunk of live model text for model step `turn`. */
  text?: string;
  error_code?: string;
  /** tool_start/tool_end: bounded, redacted view of the tool arguments. */
  args?: Record<string, SummaryValue>;
  /** tool_end: key facts from the result, or {error} for failures. */
  summary?: Record<string, SummaryValue>;
  usage?: Record<string, number>;
  step_usage?: Record<string, number>;
  tool_calls?: string[];
  /** runtime_limit: turn_budget | wall_clock | tool_calls. model_retry_start: overloaded | rate_limit | timeout | server_error | connection. */
  reason?: string;
  attempt?: number;
  wait_seconds?: number;
  final_summary?: boolean;
  message?: string;
}

/** A failure reported by the server's `error` event; its message is already user-safe. */
export class AgentRunError extends Error {}

export async function streamAgent(message: string, sessionId: string | undefined,
  newSession: boolean, onProgress: (event: AgentProgress) => void,
  signal: AbortSignal): Promise<StudioAgentResponse | null> {
  const response = await fetch("/api/agent/chat/stream", {
    method: "POST", headers: { "Content-Type": "application/json" }, signal,
    body: JSON.stringify({ message, ...(sessionId ? { session_id: sessionId } : {}),
      new_session: newSession }),
  });
  if (!response.ok || !response.body) throw new Error(`Agent request failed (${response.status}).`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let result: StudioAgentResponse | null = null;
  let ended = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      let newline: number;
      while ((newline = pending.indexOf("\n")) >= 0) {
        const line = pending.slice(0, newline);
        pending = pending.slice(newline + 1);
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === "error") {
          onProgress(event);
          throw new AgentRunError(typeof event.message === "string" && event.message
            ? event.message : "Agent request failed. Check provider settings or try again.");
        }
        if (event.type === "result") result = event.result;
        if (event.type === "end") ended = true;
        onProgress(event);
      }
    }
    if (!ended) throw new Error("Agent connection ended before completion.");
    return result;
  } finally {
    reader.releaseLock();
  }
}

export async function cancelAgent(runId: string) {
  const response = await fetch(`/api/agent/chat/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
  });
  if (!response.ok) throw new Error("Could not request cancellation. The run may have finished.");
}

// --- Step timeline -----------------------------------------------------------

export type TimelineStatus = "running" | "ok" | "failed" | "info";

export interface AgentTimelineEntry {
  kind: "model" | "tool" | "retry" | "limit" | "approval" | "stopped";
  turn?: number;
  label: string;
  detail?: string;
  status: TimelineStatus;
  toolName?: string;
}

export interface AgentRunTrace {
  entries: AgentTimelineEntry[];
  /** Live text of the most recent model step that produced text. */
  liveText: string;
  liveTurn?: number;
}

export const emptyTrace = (): AgentRunTrace => ({ entries: [], liveText: "" });

const MAX_ENTRIES = 80;
const MAX_DETAIL = 160;

function clip(text: string, limit = MAX_DETAIL): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
}

function formatValue(value: SummaryValue, key = ""): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return value.map((item) => formatValue(item, key)).join(", ");
  if (typeof value === "object") return Object.entries(value).map(([k, v]) => `${k} ${formatValue(v, k)}`).join(", ");
  // Identifiers (concept ids, run ids) are shown verbatim, counts with separators.
  if (typeof value === "number") return /(^|_)ids?$/i.test(key) ? String(value) : value.toLocaleString();
  return String(value);
}

/** One short line from an args/summary object, e.g. "row_count 40 · dataset_id ds-1". */
export function formatSummary(summary?: Record<string, SummaryValue>): string {
  if (!summary) return "";
  if (typeof summary.error === "string") return clip(summary.error);
  return clip(Object.entries(summary).map(([key, value]) =>
    `${key.replaceAll("_", " ")} ${formatValue(value, key)}`).join(" · "));
}

export function toolLabel(name?: string): string {
  return (name || "tool").replaceAll("_", " ");
}

function retryLabel(event: AgentProgress): string {
  const wait = typeof event.wait_seconds === "number" ? ` in ${Math.max(1, Math.round(event.wait_seconds))}s` : "";
  const cause = event.reason === "rate_limit" ? "Provider rate limit"
    : event.reason === "timeout" ? "Provider timed out"
    : event.reason === "connection" ? "Provider connection failed"
    : "Provider busy";
  return `${cause} — retrying${wait}`;
}

function limitLabel(reason?: string): string {
  if (reason === "wall_clock") return "Time limit reached";
  if (reason === "tool_calls") return "Tool-call limit reached";
  return "Step limit reached";
}

function lastIndex(entries: AgentTimelineEntry[], match: (entry: AgentTimelineEntry) => boolean): number {
  for (let i = entries.length - 1; i >= 0; i -= 1) if (match(entries[i])) return i;
  return -1;
}

/** Fold one stream event into the run trace (pure; returns a new trace when it changes). */
export function applyAgentEvent(trace: AgentRunTrace, event: AgentProgress): AgentRunTrace {
  if (event.type === "text_delta" && typeof event.text === "string") {
    const same = trace.liveTurn === event.turn;
    return { ...trace, liveTurn: event.turn, liveText: (same ? trace.liveText : "") + event.text };
  }
  if (event.type !== "progress") return trace;
  const entries = [...trace.entries];
  const push = (entry: AgentTimelineEntry) => {
    entries.push(entry);
    if (entries.length > MAX_ENTRIES) entries.splice(0, entries.length - MAX_ENTRIES);
  };
  switch (event.stage) {
    case "model_start":
      push({ kind: "model", turn: event.turn, status: "running",
        label: event.final_summary ? "Summarising completed steps" : `Model step ${event.turn ?? entries.length + 1}` });
      break;
    case "model_end": {
      const index = lastIndex(entries, (entry) => entry.kind === "model" && entry.turn === event.turn);
      if (index >= 0) {
        const calls = event.tool_calls ?? [];
        const narration = trace.liveTurn === event.turn && calls.length ? clip(trace.liveText, 120) : "";
        const requested = calls.length ? `Requested ${calls.map(toolLabel).join(", ")}` : "";
        entries[index] = { ...entries[index], status: "ok",
          detail: [narration, requested].filter(Boolean).join(" — ") || entries[index].detail };
      }
      break;
    }
    case "model_retry_start":
      push({ kind: "retry", turn: event.turn, status: "info", label: retryLabel(event),
        detail: event.attempt ? `Attempt ${event.attempt + 1}` : undefined });
      break;
    case "tool_start":
      push({ kind: "tool", turn: event.turn, status: "running", toolName: event.tool_name,
        label: toolLabel(event.tool_name), detail: formatSummary(event.args) || undefined });
      break;
    case "tool_end": {
      const index = lastIndex(entries, (entry) => entry.kind === "tool"
        && entry.toolName === event.tool_name && entry.status === "running");
      const failed = Boolean(event.error_code);
      const detail = formatSummary(event.summary) || (failed ? "Failed" : "");
      const entry: AgentTimelineEntry = { kind: "tool", turn: event.turn, toolName: event.tool_name,
        label: toolLabel(event.tool_name), status: failed ? "failed" : "ok",
        detail: detail || (index >= 0 ? entries[index].detail : undefined) };
      if (index >= 0) entries[index] = entry; else push(entry);
      break;
    }
    case "runtime_limit":
      push({ kind: "limit", turn: event.turn, status: "info", label: limitLabel(event.reason),
        detail: event.reason === "turn_budget" ? "The reply summarises the steps completed so far." : undefined });
      break;
    case "approval_required":
      push({ kind: "approval", turn: event.turn, status: "info", label: "Waiting for your approval",
        detail: event.tool_name ? toolLabel(event.tool_name) : undefined });
      break;
    default:
      return trace;
  }
  return { ...trace, entries };
}

/** Close a trace when the run ends: running steps become failed (error/cancel) or done. */
/** True when every tool step in the timeline reported its outcome. */
export function timelineComplete(entries: AgentTimelineEntry[]): boolean {
  return entries.every((entry) => entry.kind !== "tool" || entry.status === "ok" || entry.status === "failed");
}

export function finishTrace(trace: AgentRunTrace, outcome: "completed" | "cancelled" | "error",
  detail?: string): AgentTimelineEntry[] {
  const entries = trace.entries.map((entry): AgentTimelineEntry => {
    if (entry.status !== "running") return entry;
    // A completed run whose tool step never reported back: do not claim success.
    if (outcome === "completed" && entry.kind === "tool")
      return { ...entry, status: "info", detail: "Outcome not reported" };
    return { ...entry, status: outcome === "completed" ? "ok" : "failed",
      detail: entry.detail ?? (outcome === "cancelled" ? "Stopped" : undefined) };
  });
  if (outcome === "cancelled") entries.push({ kind: "stopped", status: "info", label: "Stopped by request" });
  if (outcome === "error") entries.push({ kind: "stopped", status: "failed", label: "Run failed",
    detail: detail ? clip(detail) : undefined });
  return entries;
}
