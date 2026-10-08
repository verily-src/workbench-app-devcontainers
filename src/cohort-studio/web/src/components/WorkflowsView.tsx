import { useCallback, useEffect, useState } from "react";
import { api, WorkflowList } from "../api";

const TERMINAL = new Set(
  ["COMPLETED", "FAILED", "CANCELLED", "CANCELED", "DELETED"]);
const isRunning = (s: string) => !TERMINAL.has((s || "").toUpperCase());

function statusClass(status: string): string {
  const s = (status || "").toUpperCase();
  if (s === "COMPLETED") return "wf-ok";
  if (s === "FAILED") return "wf-fail";
  if (s === "CANCELLED" || s === "CANCELED" || s === "DELETED") return "wf-dim";
  return "wf-run";  // RUNNING, PENDING, STARTING, STOPPING…
}

const when = (iso: string | null) =>
  iso ? String(iso).replace("T", " ").slice(0, 16) : "—";

export function WorkflowsView() {
  const [data, setData] = useState<WorkflowList | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback((force = false) => {
    setLoading(true);
    api.workflows(force).then(setData).catch(() => setData(
      { available: false, jobs: [], running_count: 0 }))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => refresh(false), [refresh]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div className="hero">
          <span className="count">{data?.running_count ?? "…"}</span>
          <span className="detail">workflow job(s) running</span>
        </div>
        <div style={{ flex: 1 }} />
        {loading && <div className="activity"><span className="pulse" />Loading…</div>}
        <button onClick={() => refresh(true)}>Refresh</button>
      </div>
      <p className="settings-caption" style={{ margin: "6px 0 12px" }}>
        Workbench workflow runs (Nextflow / HealthOmics). Each job writes to
        an S3 output location — if you load a datasource that is a running
        job's output, the Explore tab flags that the data may be incomplete.
      </p>

      {data && !data.available ? (
        <div className="empty">
          <div className="title">Workflow jobs unavailable</div>
          <div className="caption">
            The workspace `wb workflow` command isn't reachable from this
            app build, or no workspace is configured.
          </div>
        </div>
      ) : data && data.jobs.length === 0 ? (
        <div className="empty">
          <div className="title">No workflow jobs</div>
          <div className="caption">Runs you submit in the workspace appear here.</div>
        </div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>status</th><th>name</th><th>engine</th><th>submitted by</th>
              <th>submitted</th><th>output location</th>
            </tr>
          </thead>
          <tbody>
            {data?.jobs.map((j) => (
              <tr key={j.run_id}>
                <td>
                  <span className={`wf-badge ${statusClass(j.status)}`}>
                    {isRunning(j.status) && <span className="wf-pulse" />}
                    {j.status}
                  </span>
                </td>
                <td title={j.status_message ?? undefined}>{j.name}</td>
                <td>{j.engine_type ?? "—"}</td>
                <td>{j.created_by ?? "—"}</td>
                <td>{when(j.created_date)}</td>
                <td>{j.output_bucket_path ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
