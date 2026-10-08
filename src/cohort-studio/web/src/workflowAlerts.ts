import { useCallback, useEffect, useRef, useState } from "react";
import { api, WorkflowJob } from "./api";

// Subscribe to a running workflow job and get a browser notification +
// in-app toast when it reaches a terminal state. Subscriptions persist in
// localStorage so they survive reloads and view switches; while any are
// active we poll /api/workflows so completion is caught even if the user
// is on another tab.

const TERMINAL = new Set(
  ["COMPLETED", "FAILED", "CANCELLED", "CANCELED", "DELETED"]);
const STORE_KEY = "cohort-studio.workflow-subs";
const POLL_MS = 20000;

export interface Toast { id: string; title: string; body: string;
                         tone: "ok" | "fail" }

interface Sub { run_id: string; name: string }

function load(): Sub[] {
  try { return JSON.parse(localStorage.getItem(STORE_KEY) || "[]"); }
  catch { return []; }
}
function save(subs: Sub[]) {
  localStorage.setItem(STORE_KEY, JSON.stringify(subs));
}

export function useWorkflowAlerts() {
  const [subs, setSubs] = useState<Sub[]>(load);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const subsRef = useRef(subs);
  subsRef.current = subs;
  const toastSeq = useRef(0);

  const pushToast = useCallback((t: Omit<Toast, "id">) => {
    const id = `t${toastSeq.current++}`;
    setToasts((prev) => [...prev, { ...t, id }]);
    // Auto-dismiss after 8s; the user can also close it.
    window.setTimeout(() =>
      setToasts((prev) => prev.filter((x) => x.id !== id)), 8000);
  }, []);

  const dismissToast = (id: string) =>
    setToasts((prev) => prev.filter((x) => x.id !== id));

  const isSubscribed = useCallback(
    (runId: string) => subs.some((s) => s.run_id === runId), [subs]);

  const toggle = useCallback((job: WorkflowJob) => {
    setSubs((prev) => {
      const next = prev.some((s) => s.run_id === job.run_id)
        ? prev.filter((s) => s.run_id !== job.run_id)
        : [...prev, { run_id: job.run_id, name: job.name }];
      save(next);
      return next;
    });
    // Ask for OS notification permission on first opt-in (best effort —
    // through the Workbench proxy this may be denied; the toast still works).
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission().catch(() => undefined);
    }
  }, []);

  const fire = useCallback((sub: Sub, status: string) => {
    const ok = status === "COMPLETED";
    const title = ok ? "Workflow finished" : "Workflow ended";
    const body = `${sub.name} — ${status}`;
    pushToast({ title, body, tone: ok ? "ok" : "fail" });
    if ("Notification" in window && Notification.permission === "granted") {
      try { new Notification(title, { body }); } catch { /* ignore */ }
    }
  }, [pushToast]);

  // Poll only while there is something to watch for.
  useEffect(() => {
    if (subs.length === 0) return;
    let cancelled = false;
    const check = async () => {
      let list: WorkflowJob[];
      // No force: ride the backend's 45s TTL so N subscribed tabs don't
      // each shell out `wb workflow job list` every poll. Worst-case
      // notify latency ~65s, fine for minutes-to-hours jobs.
      try { list = (await api.workflows()).jobs; }
      catch { return; }
      if (cancelled) return;
      const byId = new Map(list.map((j) => [j.run_id, j]));
      const done: Sub[] = [];
      for (const s of subsRef.current) {
        const job = byId.get(s.run_id);
        if (job && TERMINAL.has((job.status || "").toUpperCase())) {
          fire(s, job.status.toUpperCase());
          done.push(s);
        }
      }
      if (done.length) {
        setSubs((prev) => {
          const next = prev.filter(
            (s) => !done.some((d) => d.run_id === s.run_id));
          save(next);
          return next;
        });
      }
    };
    const handle = window.setInterval(check, POLL_MS);
    check();  // check immediately so a since-finished job notifies at once
    return () => { cancelled = true; window.clearInterval(handle); };
  }, [subs.length, fire]);

  return { isSubscribed, toggle, toasts, dismissToast,
           subscribedCount: subs.length };
}
