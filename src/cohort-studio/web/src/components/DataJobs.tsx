import { useEffect, useRef, useState } from "react";
import { pendingDataJobs, forgetDataJob } from "../api";
import { notifyDataReady } from "../notifications";
import type { DataJob, OpenResult } from "../api";
import type { TableInfo } from "../types";
import { formatCount, formatElapsed, tableStats } from "../format";
import "./DataJobs.css";

const ACTIVE = new Set(["queued", "running", "cancelling"]);
const DONE_VISIBLE_MS = 8000;

interface Tracked { job: DataJob; receivedAt: number; firstSeen?: number; firstElapsed?: number }

/** Seconds elapsed: server value, advanced locally from the first poll so the
 * timer keeps moving between polls and never depends on clock skew. */
function elapsedNow(tracked: Tracked, now: number): number | null {
  const { job, receivedAt, firstSeen, firstElapsed } = tracked;
  if (job.elapsed == null) return null;
  if (!ACTIVE.has(job.status)) return job.elapsed;
  const latest = job.elapsed + (now - receivedAt) / 1000;
  const sinceFirst = firstSeen != null && firstElapsed != null
    ? firstElapsed + (now - firstSeen) / 1000 : latest;
  return Math.max(latest, sinceFirst);
}

const DONE_LABEL: Record<string, string> = { join: "Joined", extract: "Saved extract", refresh_extract: "Refreshed extract" };
const JOB_LABEL: Record<string, string> = { join: "Join", extract: "Extract", refresh_extract: "Refresh extract" };

function verb(job: DataJob): string {
  if (job.kind === "join") return "Joining";
  if (job.kind === "join_preview") return "Previewing join";
  if (job.kind === "extract") return "Saving extract";
  if (job.kind === "refresh_extract") return "Refreshing extract";
  return "Loading";
}

function statusText(job: DataJob): string {
  if (job.status === "cancelling") return "Cancelling after the current operation…";
  if (job.status === "queued") return "queued";
  return job.status;
}

function phaseFacts(job: DataJob): string[] {
  const facts: string[] = [];
  const detail = job.detail ?? {};
  if (detail.rows != null) {
    facts.push(`${formatCount(detail.rows)} rows${detail.columns != null ? ` × ${detail.columns} columns` : ""}`);
  }
  if (detail.engine === "aurora") facts.push("runs in the database");
  else if (detail.engine === "duckdb") facts.push("runs in DuckDB");
  return facts;
}

/** Inline progress for one job; reused by the join panel for previews. */
export function JobProgress({ job, receivedAt, expected, onCancel }: {
  job: DataJob; receivedAt: number; expected?: TableInfo | null; onCancel?: () => void;
}) {
  const first = useRef<{ id: string; at: number; elapsed: number } | null>(null);
  if (job.elapsed != null && first.current?.id !== job.job_id) {
    first.current = { id: job.job_id, at: receivedAt, elapsed: job.elapsed };
  }
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!ACTIVE.has(job.status)) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [job.status]);
  const elapsed = elapsedNow({ job, receivedAt, firstSeen: first.current?.at,
    firstElapsed: first.current?.elapsed }, Math.max(now, receivedAt));
  const stats = expected ? tableStats(expected) : "";
  const facts = phaseFacts(job);
  return (
    <div className="data-job" data-status={job.status}>
      <span className="spinner" aria-hidden="true" />
      <div className="data-job-body">
        <div className="data-job-title">
          <strong>{verb(job)}</strong>{job.label ? <> <span className="data-job-label">{job.label}</span></> : null}
        </div>
        <div className="data-job-phase">
          {job.phase ?? (job.status === "queued" ? "Waiting for a free worker" : "Starting")}
          {facts.length > 0 && <span className="data-job-facts"> · {facts.join(" · ")}</span>}
        </div>
        <div className="data-job-meta">
          <span>{statusText(job)}</span>
          {elapsed != null && <span aria-label="Elapsed time">{formatElapsed(elapsed)}</span>}
          {stats && <span title="From database statistics or S3 listing">Source: {stats}</span>}
        </div>
      </div>
      {onCancel && <button className="quiet" disabled={job.status === "cancelling"} onClick={onCancel}>Cancel</button>}
    </div>
  );
}

function DoneSummary({ job, onHide }: { job: DataJob; onHide: () => void }) {
  const result = job.result;
  const columns = Array.isArray(result?.columns) ? result!.columns.length : null;
  const inDatabase = result?.query_scope === "database";
  const shape = result?.rows != null
    ? `${result.rows.toLocaleString("en")} rows${inDatabase ? " in memory" : ""}${columns != null ? ` × ${columns} columns` : ""}`
    : "";
  return (
    <div className="data-job data-job-done" data-status="complete">
      <span className="data-job-check" aria-hidden="true">✓</span>
      <div className="data-job-body">
        <div className="data-job-title">
          <strong>{DONE_LABEL[job.kind] ?? "Loaded"}</strong>{job.label ? <> <span className="data-job-label">{job.label}</span></> : null}
        </div>
        <div className="data-job-meta">
          {shape && <span>{shape}</span>}
          {job.elapsed != null && <span>in {formatElapsed(job.elapsed)}</span>}
          {inDatabase && <span>Filters and charts query the full table in the database</span>}
        </div>
      </div>
      <button className="quiet" onClick={onHide}>Hide</button>
    </div>
  );
}

export function DataJobs({ onOpen, expected, showDone = true }: {
  onOpen: (result: OpenResult) => void;
  /** Show the "Loaded …" completion cards (Explore only); progress always shows. */
  showDone?: boolean;
  /** Listing metadata for the table being opened, shown while it loads. */
  expected?: TableInfo | null;
}) {
  const [recovered, setRecovered] = useState<Record<string, DataJob>>({});
  const [jobs, setJobs] = useState<Record<string, Tracked>>({});
  const [done, setDone] = useState<Record<string, DataJob>>({});
  const [error, setError] = useState("");
  const notified = useRef(new Set<string>());
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
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
    const pending = timers.current;
    const hide = (id: string) => {
      setDone(old => { const next = { ...old }; delete next[id]; return next; });
      clearTimeout(pending.get(id));
      pending.delete(id);
    };
    const update = (event: Event) => {
      const { id, job } = (event as CustomEvent<{ id: string; job: DataJob | null }>).detail;
      setJobs(old => {
        const next = { ...old };
        if (job && ACTIVE.has(job.status)) next[id] = { job, receivedAt: Date.now() };
        else delete next[id];
        return next;
      });
      if (job?.status === "complete") {
        setDone(old => ({ ...old, [id]: job }));
        clearTimeout(pending.get(id));
        pending.set(id, setTimeout(() => hide(id), DONE_VISIBLE_MS));
      }
    };
    window.addEventListener("studio-data-job", update);
    return () => {
      window.removeEventListener("studio-data-job", update);
      pending.forEach(clearTimeout);
      pending.clear();
    };
  }, []);
  const active = Object.values(jobs);
  const openJobs = active.filter(({ job }) => job.kind === "open").length;
  const doneJobs = showDone ? Object.values(done) : [];
  if (!active.length && !Object.keys(recovered).length && !doneJobs.length && !error) return null;
  return <section aria-label="Data operations" className="data-jobs">
    {Object.values(recovered).map(job => <div key={job.job_id} role="status" className="data-job" data-status={job.status}>
      <div className="data-job-body">
        <div className="data-job-title">
          <strong>{JOB_LABEL[job.kind] ?? "Load data"}</strong>{job.label ? <> <span className="data-job-label">{job.label}</span></> : null}
        </div>
        <div className="data-job-meta"><span>{job.status}</span></div>
      </div>
      {job.status === "complete" && job.result && <button onClick={() => {
        onOpen(job.result!); forgetDataJob(job.job_id);
        setRecovered(old => { const next = { ...old }; delete next[job.job_id]; return next; });
      }}>Open result</button>}
      {["failed", "interrupted", "cancelled"].includes(job.status) && <button onClick={() => {
        forgetDataJob(job.job_id);
        setRecovered(old => { const next = { ...old }; delete next[job.job_id]; return next; });
      }}>Dismiss</button>}
    </div>)}
    {active.map(({ job, receivedAt }) => <div key={job.job_id} role="status">
      <JobProgress job={job} receivedAt={receivedAt}
        expected={job.kind === "open" && openJobs === 1 ? expected : null}
        onCancel={async () => {
          setError("");
          try {
            const response = await fetch(`/api/data-jobs/${job.job_id}/cancel`, { method: "POST" });
            if (!response.ok) throw new Error("Could not cancel. Try again.");
            const next = await response.json() as DataJob;
            setJobs(old => old[job.job_id] ? { ...old, [job.job_id]: { job: next, receivedAt: Date.now() } } : old);
          } catch (e) { setError((e as Error).message); }
        }} />
    </div>)}
    {doneJobs.map(job => <div key={job.job_id}>
      <DoneSummary job={job} onHide={() => setDone(old => { const next = { ...old }; delete next[job.job_id]; return next; })} />
    </div>)}
    {error && <p role="alert">{error}</p>}
  </section>;
}
