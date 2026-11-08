import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./ReportIssue.css";

export function ReportIssue() {
  const [open, setOpen] = useState(false);
  const [details, setDetails] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const keys = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
      if (event.key !== "Tab") return;
      const focusable = dialog.current?.querySelectorAll<HTMLElement>("button:not(:disabled), textarea:not(:disabled)");
      if (!focusable?.length) return;
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", keys);
    return () => { window.removeEventListener("keydown", keys); trigger.current?.focus(); };
  }, [open]);

  const send = async () => {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/support/report", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ details }),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(typeof result.detail === "string" ? result.detail : "Could not send the report. Try again.");
      }
      setSent(true);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Could not send the report. Try again.");
    } finally { setBusy(false); }
  };

  return <>
    <button ref={trigger} type="button" className="corner-tool" aria-label="Report issue" title="Report issue" onClick={() => { setOpen(true); setSent(false); setError(""); }}>!</button>
    {open && createPortal(<div className="report-issue-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <section ref={dialog} className="report-issue" role="dialog" aria-modal="true" aria-labelledby="report-issue-title">
        <div className="report-issue-heading"><h2 id="report-issue-title">Report issue</h2>
          <button type="button" className="quiet" aria-label="Close report issue" onClick={() => setOpen(false)}>✕</button></div>
        {sent ? <p role="status">Report sent.</p> : <>
          <p>Recent session diagnostics are attached automatically. They include request IDs, status and timings, but not raw logs, SQL, filters or data.</p>
          <label>What happened? <textarea autoFocus value={details} onChange={(event) => setDetails(event.target.value)} maxLength={2000} /></label>
          {error && <p role="alert">{error}</p>}
          <div className="report-issue-actions"><button className="primary" type="button" onClick={send} disabled={busy || !details.trim()}>{busy ? "Sending…" : "Send"}</button></div>
        </>}
      </section>
    </div>, document.body)}
  </>;
}
