import { useEffect, useRef, useState } from "react";
import { pendingDataJobs, forgetDataJob } from "../api";
import { notifyDataReady } from "../notifications";
import type { DataJob, OpenResult } from "../api";

export function DataJobs({ onOpen }: { onOpen: (result: OpenResult) => void }) {
  const [recovered, setRecovered] = useState<Record<string, DataJob>>({});
  const [jobs, setJobs] = useState<Record<string, DataJob>>({});
  const [error, setError] = useState("");
  const notified = useRef(new Set<string>());
  useEffect(() => {
    const ids = pendingDataJobs();
    let stopped = false;
    const poll = async () => {
      for (const id of ids) {
        try {
          const response = await fetch(`/api/data-jobs/${id}`);
          if (!response.ok) { if (response.status === 404) forgetDataJob(id); continue; }
          const job = await response.json() as DataJob;
          if (!stopped && job.status === "complete" && !notified.current.has(id)) {
            notified.current.add(id);
            notifyDataReady(job.kind, id);
          }
          if (!stopped && pendingDataJobs().includes(id)) setRecovered(old => ({ ...old, [id]: job }));
        } catch { }
      }
    };
    void poll();
    const timer = setInterval(poll, 2000);
    return () => { stopped = true; clearInterval(timer); };
  }, []);
  useEffect(() => {
    const update = (event: Event) => {
      const { id, job } = (event as CustomEvent<{ id: string; job: DataJob | null }>).detail;
      setJobs(old => { const next = { ...old }; if (job) next[id] = job; else delete next[id]; return next; });
    };
    window.addEventListener("studio-data-job", update);
    return () => window.removeEventListener("studio-data-job", update);
  }, []);
  if (!Object.keys(jobs).length && !Object.keys(recovered).length) return null;
  return <section aria-label="Data operations" style={{ padding: "8px 16px" }}>
    {Object.values(recovered).map(job => <div key={job.job_id} role="status">
      {job.kind === "join" ? "Join" : "Load data"}: {job.status}
      {job.status === "complete" && job.result && <button onClick={() => {
        onOpen(job.result!); forgetDataJob(job.job_id);
        setRecovered(old => { const next = { ...old }; delete next[job.job_id]; return next; });
      }}>Open result</button>}
      {["failed", "interrupted", "cancelled"].includes(job.status) && <button onClick={() => {
        forgetDataJob(job.job_id);
        setRecovered(old => { const next = { ...old }; delete next[job.job_id]; return next; });
      }}>Dismiss</button>}
    </div>)}
    {Object.values(jobs).map(job => <div key={job.job_id} role="status">
      {job.kind === "join" ? "Join" : "Load data"}: {job.status === "cancelling" ? "Cancelling after the current operation…" : job.status}
      <button className="quiet" disabled={job.status === "cancelling"} onClick={async () => {
        setError("");
        try {
          const response = await fetch(`/api/data-jobs/${job.job_id}/cancel`, { method: "POST" });
          if (!response.ok) throw new Error("Could not cancel. Try again.");
          const next = await response.json() as DataJob;
          setJobs(old => ({ ...old, [job.job_id]: next }));
        } catch (e) { setError((e as Error).message); }
      }}>Cancel</button>
    </div>)}
    {error && <p role="alert">{error}</p>}
  </section>;
}
