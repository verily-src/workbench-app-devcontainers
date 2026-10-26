import { useState } from "react";
import { api } from "../api";
import type { PerformanceSummary } from "../types";

export function PerformancePanel() {
  const [data, setData] = useState<PerformanceSummary | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = async () => {
    setBusy(true); setError("");
    try {setData(await api.performance());} catch (e) {setError((e as Error).message);}
    finally {setBusy(false);}
  };
  const labels: Record<string, string> = {"operation.started": "Queue wait", "operation.finished": "Execution", "http.finished": "API", "sql.finished": "SQL", "operation.rejected": "Admission rejected"};
  return <section className="settings-card" aria-label="Performance">
    <h3>Performance</h3>
    <button onClick={refresh} disabled={busy}>{busy ? "Loading…" : "Refresh performance"}</button>
    {error && <p role="alert">{error}</p>}
    {data && <>
      <p>This session · up to {data.retention_days} days · {data.max_events.toLocaleString()} events retained across the app</p>
      {data.dropped_events_since_restart > 0 && <p role="alert">Some metrics were not recorded. Counts may be incomplete.</p>}
      <div style={{overflowX: "auto"}}><table className="performance-table">
        <thead><tr><th>Stage</th><th>Operation</th><th>Calls</th><th>Failures</th><th>p95 (ms)</th></tr></thead>
        <tbody>{data.groups.map(row => <tr key={row.event + row.name}>
          <td>{labels[row.event] || row.event}</td><td>{row.name}</td><td>{row.count}</td><td>{row.failed}</td><td>{row.p95_ms?.toLocaleString() ?? "—"}</td>
        </tr>)}</tbody>
      </table></div>
      {!data.groups.length && <p>No metrics recorded for this session.</p>}
    </>}
  </section>;
}
