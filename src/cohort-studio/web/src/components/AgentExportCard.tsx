import { useEffect, useState } from "react";

export interface AgentDownload {
  dataset_id: string;
  title: string;
  format: string;
}

interface Job {
  id: string;
  status: string;
  rows?: number;
  error?: string | null;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
  } catch { /* Response has no error body. */ }
  return `Export failed (${response.status}).`;
}

export function AgentExportCard({ download }: { download: AgentDownload }) {
  const [job, setJob] = useState<Job>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pollAttempt, setPollAttempt] = useState(0);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let stopped = false;
    let timer = 0;
    const poll = async () => {
      try {
        const response = await fetch(`/api/exports/${encodeURIComponent(job.id)}`);
        if (!response.ok) throw new Error(await errorMessage(response));
        const next = await response.json() as Job;
        if (!stopped) setJob(next);
      } catch (caught) {
        if (!stopped) setError(caught instanceof Error ? caught.message : "Export status failed.");
      }
    };
    timer = window.setTimeout(() => { void poll(); }, 1000);
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [job, pollAttempt]);
  const start = async () => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/agent/dashboards/${encodeURIComponent(download.dataset_id)}/download`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ format: download.format }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      if (!response.headers.get("content-disposition") && response.headers.get("content-type")?.includes("application/json")) {
        const body = await response.json() as { job: Job };
        setJob(body.job);
      } else {
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement("a");
        link.href = url;
        link.download = `cohort.${download.format}`;
        link.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 60000);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Export failed.");
    } finally { setBusy(false); }
  };
  return <div className="studio-agent-card">
    <strong>{download.title}</strong>
    <span>{download.format.toUpperCase()} · saved dashboard filters</span>
    {!job && <button type="button" className="primary" disabled={busy} onClick={() => void start()}>
      {busy ? "Preparing…" : `Download ${download.format.toUpperCase()}`}
    </button>}
    {job && !error && ["queued", "running"].includes(job.status) && <span role="status">
      Preparing export · {(job.rows ?? 0).toLocaleString()} rows
    </span>}
    {job?.status === "complete" && <a href={`/api/exports/${encodeURIComponent(job.id)}/download`}>
      Download {download.format.toUpperCase()}
    </a>}
    {job && ["failed", "cancelled"].includes(job.status) && <span role="alert">{job.error || "Export did not complete."}</span>}
    {error && <span role="alert">{error}</span>}
    {error && job && ["queued", "running"].includes(job.status) && <button type="button"
      onClick={() => { setError(""); setPollAttempt(value => value + 1); }}>Retry status</button>}
  </div>;
}
