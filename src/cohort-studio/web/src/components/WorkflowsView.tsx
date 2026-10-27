import { useCallback, useEffect, useState } from "react";
import { api, WorkflowJob, WorkflowList } from "../api";

interface Props {
  data: WorkflowList | null;
  onData: (data: WorkflowList) => void;
  isSubscribed: (runId: string) => boolean;
  onToggleSubscribe: (job: WorkflowJob) => void;
}

const TERMINAL = new Set(
  ["COMPLETED", "FAILED", "CANCELLED", "CANCELED", "DELETED"]);
const isRunning = (s: string) => !TERMINAL.has((s || "").toUpperCase());

function statusClass(status: string): string {
  const s = (status || "").toUpperCase();
  if (s === "COMPLETED") return "wf-ok";
  if (s === "FAILED") return "wf-fail";
  if (s === "CANCELLED" || s === "CANCELED" || s === "DELETED") return "wf-dim";
  return "wf-run";
}

const when = (iso: string | null) =>
  iso ? String(iso).replace("T", " ").slice(0, 16) : "—";

export function WorkflowsView({ data, onData, isSubscribed, onToggleSubscribe }: Props) {
  const [loading, setLoading] = useState(false);
  const [sort, setSort] = useState<{ key: keyof WorkflowJob; direction: "asc" | "desc" }>({ key: "created_date", direction: "desc" });
  const setColumnSort = (key: keyof WorkflowJob) => setSort(previous => ({ key,
    direction: previous.key === key && previous.direction === "asc" ? "desc" : "asc" }));
  const fields: { label: string; key: keyof WorkflowJob }[] = [
    { label: "Status", key: "status" }, { label: "Name", key: "name" },
    { label: "Engine", key: "engine_type" }, { label: "Submitted by", key: "created_by" },
    { label: "Submitted", key: "created_date" }, { label: "Output bucket", key: "output_bucket_name" },
    { label: "Output path", key: "output_bucket_path" },
  ];
  const sorted = [...(data?.jobs ?? [])].sort((a, b) => {
    const av = a[sort.key], bv = b[sort.key];
    if (av == null) return bv == null ? 0 : 1;
    if (bv == null) return -1;
    const order = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: "base" });
    return sort.direction === "asc" ? order : -order;
  });

  const refresh = useCallback((force = false) => {
    setLoading(true);
    api.workflows(force).then(onData).catch(() => onData(
      { available: false, jobs: [], running_count: 0 }))
      .finally(() => setLoading(false));
  }, [onData]);

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

      {!data ? <div className="empty" role="status"><div className="title">Loading workflow jobs…</div></div> : !data.available ? (
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
              {fields.map(field => <th key={field.key} aria-sort={sort.key === field.key ? sort.direction === "asc" ? "ascending" : "descending" : "none"}>
                <button className="table-sort" onClick={() => setColumnSort(field.key)}>{field.label}{sort.key === field.key ? sort.direction === "asc" ? " ↑" : " ↓" : ""}</button>
              </th>)}<th>Alert</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((j) => (
              <tr key={j.run_id}>
                <td>
                  {data?.monitor_base && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(j.run_id) ?
                    <a href={`${data.monitor_base}${encodeURIComponent(j.run_id)}`} target="_blank" rel="noopener noreferrer" aria-label={`${j.status}: Open workflow ${j.name} in Workbench`} className={`wf-badge ${statusClass(j.status)}`}>
                      {isRunning(j.status) && <span className="wf-pulse" />}{j.status}
                    </a> : <span className={`wf-badge ${statusClass(j.status)}`}>
                      {isRunning(j.status) && <span className="wf-pulse" />}{j.status}
                    </span>}
                </td>
                <td title={j.status_message ?? undefined}>{j.name}</td>
                <td>{j.engine_type ?? "—"}</td>
                <td>{j.created_by ?? "—"}</td>
                <td>{when(j.created_date)}</td>
                <td title={j.output_bucket_resource ?? undefined}>
                  {j.output_bucket_name
                    ?? j.output_bucket_resource ?? "—"}
                </td>
                <td>{j.output_bucket_path ?? "—"}</td>
                <td>
                  {isRunning(j.status) ? (
                    <button className="wf-sub"
                            onClick={() => onToggleSubscribe(j)}>
                      {isSubscribed(j.run_id) ? "🔔 Subscribed" : "Notify me"}
                    </button>
                  ) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
