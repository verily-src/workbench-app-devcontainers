import { useEffect, useRef, useState } from "react";
import "./ReportIssue.css";

type Diagnostics = { generated_at: string; version: string; recipient: string | null; events: object[] };

export function ReportIssue() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [details, setDetails] = useState("");
  const [downloaded, setDownloaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    const keys = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
      if (event.key !== "Tab") return;
      const focusable = dialog.current?.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), textarea:not(:disabled), a[href]");
      if (!focusable?.length) return;
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", keys);
    return () => { window.removeEventListener("keydown", keys); trigger.current?.focus(); };
  }, [open]);

  const download = async () => {
    setBusy(true); setError(""); setDownloaded(false);
    try {
      const response = await fetch("/api/support/diagnostics", { cache: "no-store" });
      if (!response.ok) throw new Error("Could not prepare diagnostics. Try again.");
      const { recipient, ...report } = await response.json() as Diagnostics;
      if (recipient) setEmail((current) => current || recipient);
      const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url; link.download = "cohort-browser-diagnostics.json";
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      setDownloaded(true);
    } catch {
      setError("Could not prepare diagnostics. Try again.");
    } finally { setBusy(false); }
  };

  const validEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && email.length <= 254;
  const body = `${details.trim()}\n\nI will attach cohort-browser-diagnostics.json.`.trim();
  const draft = `mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent("Cohort Browser issue")}&body=${encodeURIComponent(body)}`;
  return <>
    <button ref={trigger} type="button" className="corner-tool" aria-label="Report issue" title="Report issue" onClick={() => setOpen(true)}>!</button>
    {open && <div className="report-issue-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <section ref={dialog} className="report-issue" role="dialog" aria-modal="true" aria-labelledby="report-issue-title">
        <div className="report-issue-heading"><h2 id="report-issue-title">Report issue</h2>
          <button type="button" className="quiet" aria-label="Close report issue" onClick={() => setOpen(false)}>✕</button></div>
        <p>Download diagnostics, then attach the file to your email and send it.</p>
        <p>Diagnostics contain this session’s recent request IDs, status and timings. They do not include raw logs, data, SQL or filters.</p>
        <label>Email to <input autoFocus type="email" value={email} onChange={(event) => setEmail(event.target.value)} maxLength={254} /></label>
        <label>What happened? <textarea value={details} onChange={(event) => setDetails(event.target.value)} maxLength={2000} /></label>
        {error && <p role="alert">{error}</p>}
        <div className="report-issue-actions">
          <button type="button" onClick={download} disabled={busy}>{busy ? "Preparing…" : "Download diagnostics"}</button>
          {downloaded && validEmail && <a className="button" href={draft}>Open email draft</a>}
        </div>
        {downloaded && <p role="status">Downloaded cohort-browser-diagnostics.json. Attach it to the draft before sending.</p>}
      </section>
    </div>}
  </>;
}
