import type { AgentTimelineEntry, TimelineStatus } from "../agentStreaming";

const STATUS_TEXT: Record<TimelineStatus, string> = {
  running: "In progress", ok: "Completed", failed: "Failed", info: "Note",
};
const STATUS_MARK: Record<TimelineStatus, string> = {
  running: "…", ok: "✓", failed: "✕", info: "•",
};

interface Props {
  entries: AgentTimelineEntry[];
  /** The run is still in progress: open by default. */
  live?: boolean;
}

/** Persistent, collapsible list of the model, tool, retry and limit steps of one agent run. */
export function AgentTimeline({ entries, live = false }: Props) {
  if (!entries.length) return null;
  const tools = entries.filter((entry) => entry.kind === "tool");
  const failed = tools.filter((entry) => entry.status === "failed").length;
  const models = entries.filter((entry) => entry.kind === "model").length;
  const counts = [`${models} model step${models === 1 ? "" : "s"}`,
    `${tools.length} tool call${tools.length === 1 ? "" : "s"}`,
    ...(failed ? [`${failed} failed`] : [])].join(", ");
  return (
    <details className="studio-agent-timeline" open={live || undefined}>
      <summary>{live ? "Steps so far" : "Steps"} ({counts})</summary>
      <ol aria-label="Agent steps">
        {entries.map((entry, index) => (
          <li key={index} className={`studio-agent-step ${entry.kind} ${entry.status}`}>
            <span className="studio-agent-step-mark" aria-hidden="true">{STATUS_MARK[entry.status]}</span>
            <span className="studio-agent-step-label">{entry.label}</span>
            {entry.kind === "tool" && entry.status !== "info" && (
              <span className="studio-agent-step-status">{STATUS_TEXT[entry.status]}</span>
            )}
            {entry.kind !== "tool" && entry.status === "failed" && (
              <span className="studio-agent-step-status">{STATUS_TEXT.failed}</span>
            )}
            {entry.detail && <span className="studio-agent-step-detail">{entry.detail}</span>}
          </li>
        ))}
      </ol>
    </details>
  );
}
