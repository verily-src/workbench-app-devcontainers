/** Data Builder → Connections: the picked table's details and "Open in Explore"
 *  (Live, or Extract: save every row as a database table, then open it). */
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { OpenResult } from "../api";
import type { Source, SourceRef, TableInfo } from "../types";
import { TableDetails } from "./TableDetails";

const SCHEMA_KINDS = new Set<string>(["aurora", "postgres", "athena"]);

/** Open one listed table or file; schema-qualified kinds open by source ref. */
export function openTable(source: Source, info: TableInfo): Promise<OpenResult> {
  return SCHEMA_KINDS.has(source.kind) && info.schema && info.table
    ? api.openSourceRef({ kind: source.kind, resource_id: source.id, table: info.table,
                          schema: info.schema } as SourceRef)
    : api.openDataset(source.kind, source.id, info.name);
}

export const tableTitle = (info: TableInfo) => info.name.split("/").filter(Boolean).pop() || info.name;

const extractName = (info: TableInfo) =>
  `${(info.table ?? tableTitle(info)).replace(/\.[a-z0-9.]+$/i, "")}_extract`
    .replace(/[^A-Za-z0-9_]/g, "_").toLowerCase().slice(0, 63);

interface Props {
  source: Source;
  info: TableInfo;
  /** Writable Aurora / PostgreSQL datasources an extract can be saved to. */
  targets: Source[];
  /** Why Extract is unavailable, if it is. */
  extractReason: string | null;
  busy: boolean;
  onOpenLive: () => void;
  onOpenResult: (opened: OpenResult, title: string, sourceRef?: SourceRef) => void;
}

export function OpenTableCard({ source, info, targets, extractReason, busy, onOpenLive, onOpenResult }: Props) {
  const [mode, setMode] = useState<"live" | "extract">("live");
  const [target, setTarget] = useState(targets[0]?.id ?? "");
  const [name, setName] = useState(() => extractName(info));
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const extract = mode === "extract" && !extractReason;
  const destination = targets.find((t) => t.id === target) ?? targets[0];
  const reason = extract && (!destination || !name.trim()) ? "Choose where to save the extract." : null;
  const card = useRef<HTMLElement>(null);
  // The Connections pane scrolls on short screens; keep the picked table's actions in view.
  useEffect(() => {
    const pane = card.current?.closest(".jc-connections");
    if (!card.current || !pane) return;
    const below = card.current.getBoundingClientRect().bottom - pane.getBoundingClientRect().bottom;
    if (below > 0) pane.scrollTop += below + 8;
  }, []);

  const open = async () => {
    if (!extract) { onOpenLive(); return; }
    if (!destination || reason) return;
    const title = tableTitle(info);
    const table = name.trim();
    setRunning(true); setError(""); setStatus(`Opening ${title}…`);
    let openedId = "";
    try {
      const opened = await openTable(source, info);
      openedId = opened.dataset_id;
      setStatus(`Saving every row to ${destination.id}…`);
      const out = await api.extract(openedId, destination.kind, destination.id, table, title, (job) => {
        const rows = job.detail?.rows;
        if (typeof rows === "number" && rows > 0) setStatus(`Saving every row to ${destination.id}… ${rows.toLocaleString()} written`);
      });
      setStatus("");
      onOpenResult(out, title, { kind: destination.kind, resource_id: destination.id, table } as SourceRef);
    } catch (e) {
      setStatus("");
      setError(`Extract failed: ${(e as Error).message}`);
    } finally {
      if (openedId) void api.closeDataset(openedId).catch(() => undefined);
      setRunning(false);
    }
  };

  return (
    <section ref={card} className="jc-open-card" aria-label="Selected table">
      <div className="jc-open-title" title={info.name}>{info.table ?? tableTitle(info)}</div>
      <TableDetails info={info} />
      {extract && (
        <div className="jc-open-extract">
          <select aria-label="Save extract to" value={destination?.id ?? ""} onChange={(e) => setTarget(e.target.value)}>
            {targets.map((t) => <option key={t.id} value={t.id}>{t.label || t.id}</option>)}
          </select>
          <input type="text" aria-label="Extract table" value={name} maxLength={63}
                 onChange={(e) => setName(e.target.value)} />
        </div>
      )}
      {status && <div className="picker-status" role="status"><span className="spinner small" aria-hidden="true" />{status}</div>}
      {error && <div className="join-error" role="alert">{error}</div>}
      <div className="jc-open-row">
        <div className="jc-open-mode" role="radiogroup" aria-label="Open as">
          <label title="The tab queries the source directly.">
            <input type="radio" name="jc-open-mode" checked={!extract} onChange={() => setMode("live")} /> Live
          </label>
          <label title={extractReason ?? "Save every row as a database table you can refresh, then open it."}
                 className={extractReason ? "disabled" : undefined}>
            <input type="radio" name="jc-open-mode" checked={extract} disabled={Boolean(extractReason)}
                   onChange={() => setMode("extract")} /> Extract
          </label>
        </div>
        <button type="button" className="primary" data-tutorial-target="open-table"
                disabled={busy || running || Boolean(reason)} title={reason ?? undefined}
                onClick={() => void open()}>
          {running ? "Working…" : "Open in Explore"}
        </button>
      </div>
    </section>
  );
}
