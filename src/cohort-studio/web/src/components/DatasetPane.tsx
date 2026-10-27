import { useEffect, useId, useState } from "react";
import { api } from "../api";
import type { ExportJob } from "../api";
import type { ChartSpec, Dataset, Filter, Source } from "../types";
import { ChartCard } from "./ChartCard";
import { ChatWidget } from "./ChatWidget";
import { GrainSettings } from "./GrainSettings";
import { ColumnSettings } from "./ColumnSettings";
import { ComparePanel } from "./ComparePanel";
import { DeriveColumn } from "./DeriveColumn";
import { AggregateFilter } from "./AggregateFilter";
import { GroupSummary } from "./GroupSummary";
import { LaunchWorkflow } from "./LaunchWorkflow";

interface Props {
  dataset: Dataset;
  palette: string;
  onUpdate: (changes: Partial<Dataset>) => void;
  onEditJoin: (datasetId: string) => void;
}

function describeFilter(f: Filter): string {
  if (f.kind === "categorical") {
    return (f.values ?? []).map((v) => `${f.column}: ${v}`).join("|");
  }
  return f.max === Number.MAX_VALUE ? `${f.column}: ≥ ${f.min}` : f.min === -Number.MAX_VALUE
    ? `${f.column}: ≤ ${f.max}` : `${f.column}: ${f.min}–${f.max}`;
}

function cacheAge(asOf: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(asOf)) / 1000));
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function cacheTime(asOf: string): string {
  const date = new Date(asOf);
  return Number.isNaN(date.valueOf()) ? asOf : date.toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

function safeFilterAskError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  if (/insufficient.*credit|credit balance|billing/i.test(message)) {
    return "The AI provider needs more credits. Check provider billing in Settings.";
  }
  if (/unauthori[sz]ed|invalid api.?key|authentication|\b401\b/i.test(message)) {
    return "The AI provider rejected its key. Check the saved key in Settings.";
  }
  if (/rate.?limit|\b429\b/i.test(message)) {
    return "The AI provider rate limit was reached. Wait a moment and try again.";
  }
  if (/timeout|timed out/i.test(message)) {
    return "The request timed out. Try again with a shorter question.";
  }
  if (/invalid.*filter|validation|\b400\b|unknown column/i.test(message)) {
    return "The filter request was not valid. Check the column and value, then try again.";
  }
  return "The request could not be completed. Check the connection and try again.";
}

export function DatasetPane({ dataset, palette, onUpdate, onEditJoin }: Props) {
  const { result, filters, charts } = dataset;
  const [exportJob, setExportJob] = useState<ExportJob | null>(null);
  const [exportError, setExportError] = useState("");
  const [cancelingExport, setCancelingExport] = useState(false);
  const [creatingExport, setCreatingExport] = useState(false);
  const cohorts = dataset.cohorts ?? [];
  const [showCompare, setShowCompare] = useState(false);
  const [showDerive, setShowDerive] = useState(false);
  const [showAggregate, setShowAggregate] = useState(false);
  const [showSummary, setShowSummary] = useState(Boolean(dataset.groupSummary));
  useEffect(() => { setShowSummary(Boolean(dataset.groupSummary)); }, [dataset.id]);
  const [showLaunch, setShowLaunch] = useState(false);
  const [cohortName, setCohortName] = useState("");
  const [chatDraft, setChatDraft] = useState<{ id: string; text: string; datasetId: string } | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatDraftNumber, setChatDraftNumber] = useState(0);

  useEffect(() => {
    setChatDraft(null);
    setChatOpen(false);
    setChatDraftNumber(0);
  }, [dataset.id]);

  const saveCohort = () => {
    const name = cohortName.trim();
    if (!name || filters.length === 0) return;
    const rest = cohorts.filter((c) => c.name !== name);
    onUpdate({ cohorts: [...rest, { name, filters }] });
    setCohortName("");
  };
  const removeCohort = (name: string) =>
    onUpdate({ cohorts: cohorts.filter((c) => c.name !== name) });

  const toggleCategory = (column: string, value: string) => {
    const existing = filters.find((f) => f.column === column);
    const current = existing?.values ?? [];
    const values = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    const rest = filters.filter((f) => f.column !== column);
    onUpdate({
      filters: values.length
        ? [...rest, { column, kind: "categorical", values }] : rest,
    });
  };

  const chips: { label: string; remove: () => void }[] = [];
  for (const f of filters) {
    if (f.kind === "categorical") {
      for (const v of f.values ?? []) {
        chips.push({
          label: `${f.column}: ${v}`,
          remove: () => toggleCategory(f.column, v),
        });
      }
    } else {
      chips.push({
        label: describeFilter(f),
        remove: () => onUpdate({
          filters: filters.filter((o) => o.column !== f.column) }),
      });
    }
  }

  const isNumeric = (name: string) =>
    dataset.columns.find((c) => c.name === name)?.filter_kind === "range";
  const allowedKinds = (spec: ChartSpec): ChartSpec["kind"][] => {
    let base: ChartSpec["kind"][];
    if (spec.y) {
      base = isNumeric(spec.x) && isNumeric(spec.y)
        ? ["scatter", "heatmap", "map"] : ["heatmap"];
    } else {
      base = isNumeric(spec.x) ? ["bar", "histogram"] : ["bar"];
    }

    return base.includes(spec.kind) ? base : [spec.kind, ...base];
  };

  const updateChart = (index: number, changes: Partial<ChartSpec> | null) => {
    const next = charts.flatMap((c, i) => {
      if (i !== index) return [c];
      return changes ? [{ ...c, ...changes }] : [];
    });
    onUpdate({ charts: next });
  };

  const pageCount = result
    ? Math.max(1, Math.ceil(result.filtered / result.rows.page_size)) : 1;
  const scope = result?.scope ?? dataset.queryScope ?? "loaded";
  const entityCount = result?.entity;
  const databaseScoped = scope === "database";
  const largeDataset = Boolean(result && (result.total >= 100_000 || result.sampled));
  const exportStatus = exportJob?.status.toLowerCase();
  const exportRunning = exportStatus === "queued" || exportStatus === "running";

  useEffect(() => {
    if (!exportJob?.id || !exportRunning) return;
    let stopped = false;
    let timer = 0;
    const poll = async () => {
      if (stopped) return;
      try {
        const next = await api.exportStatus(exportJob.id);
        if (stopped) return;
        setExportJob(next);
        if (["queued", "running"].includes(next.status.toLowerCase())) {
          timer = window.setTimeout(poll, 1000);
        }
      } catch (e) {
        if (!stopped) {
          setExportError(`Export status failed: ${(e as Error).message}`);
          setExportJob((job) => job ? { ...job, status: "failed" } : job);
        }
      }
    };
    timer = window.setTimeout(() => {
      void poll();
    }, 1000);
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [exportJob?.id, exportRunning]);

  const startExport = async () => {
    if (creatingExport || exportJob) return;
    setCreatingExport(true);
    setExportError("");
    try {
      if (databaseScoped) setExportJob(await api.createExport(dataset.id, filters));
      else await api.export(dataset.id, filters);
    } catch (e) {
      setExportError((e as Error).message);
    } finally {
      setCreatingExport(false);
    }
  };

  const cancelExport = async () => {
    if (!exportJob) return;
    setCancelingExport(true);
    try {
      await api.cancelExport(exportJob.id);
      setExportJob({ ...exportJob, status: "cancelled" });
    } catch (e) {
      setExportError(`Could not cancel export: ${(e as Error).message}`);
    } finally {
      setCancelingExport(false);
    }
  };

  const clearExport = async () => {
    if (!exportJob || exportRunning) return;
    setCancelingExport(true);
    try {
      await api.cancelExport(exportJob.id);
      setExportJob(null);
      setExportError("");
    } catch (e) {
      setExportError(`Could not clear export: ${(e as Error).message}`);
    } finally {
      setCancelingExport(false);
    }
  };

  return (
    <div>
      <div className="dataset-toolbar">
        <div className="hero">
          <span className="count">
            {result ? (dataset.entityColumn && entityCount
              ? entityCount.filtered.toLocaleString()
              : result.filtered.toLocaleString()) : "…"}
          </span>
          <span className="detail">
            {dataset.entityColumn && entityCount
              ? `of ${entityCount.total.toLocaleString()} unique ${dataset.columns.find((c) => c.name === entityCount.column)?.label || entityCount.column}`
              : `of ${result?.total.toLocaleString() ?? "…"} rows`}
            · {scope === "database" ? "counts cover the full database"
              : result?.sampled ? "capped loaded sample" : "loaded rows"}
            · {dataset.source}
          </span>
        </div>
        <label className="entity-select">Count unique
          <select value={dataset.entityColumn ?? ""}
                  onChange={(e) => onUpdate({
                    entityColumn: e.target.value || undefined,
                  })}>
            <option value="">Rows</option>
            {dataset.columns.map((c) => (
              <option key={c.name} value={c.name}>{c.label || c.name}</option>
            ))}
          </select>
        </label>
        <SaveToAurora dataset={dataset} />
        {dataset.sourceRef?.kind === "join" && <button className="quiet"
          onClick={() => onEditJoin(dataset.id)}>Edit join</button>}
        <ColumnSettings dataset={dataset} onUpdate={onUpdate} />
        <GrainSettings key={dataset.id} dataset={dataset} onUpdate={onUpdate} />
        <button onClick={startExport} disabled={exportRunning || creatingExport || Boolean(exportJob)}>
          {creatingExport ? "Starting export…" : "Export TSV"}
        </button>
        <button onClick={() => { void import("../pdf").then(({ captureCharts, exportDatasetPdf }) =>
          exportDatasetPdf(dataset, captureCharts())).catch(() => setExportError("Could not load PDF export. Try again.")); }}
                disabled={!result}>
          Export PDF
        </button>
      </div>

      {databaseScoped && exportJob && <div className="export-job" role="status">
        <span>{exportStatus === "complete"
          ? `Export ready · ${(exportJob.rows ?? 0).toLocaleString()} rows`
          : exportRunning
            ? `Preparing export · ${(exportJob.rows ?? 0).toLocaleString()} rows`
            : exportStatus === "cancelled" ? "Export cancelled"
              : exportStatus === "failed" ? `Export failed${exportJob.error ? `: ${exportJob.error}` : ""}`
                : "Export queued"}</span>
        {exportRunning && <>
          <progress />
          <button className="quiet" onClick={cancelExport} disabled={cancelingExport}>
            {cancelingExport ? "Cancelling…" : "Cancel export"}
          </button>
        </>}
        {exportStatus === "complete" && <a href={api.exportDownloadUrl(exportJob.id)}>
          Download TSV{exportJob.bytes ? ` · ${formatBytes(exportJob.bytes)}` : ""}
        </a>}
        {!exportRunning && <button className="quiet" onClick={clearExport}
                                    disabled={cancelingExport}>
          {cancelingExport ? "Clearing…" : "Clear export"}
        </button>}
      </div>}
      {exportError && <div className="settings-hint" role="alert">{exportError}</div>}

      {databaseScoped && <div className="query-cache-row">
        <span className="settings-hint" title={`Cache TTL: ${result?.cache?.ttl_seconds ?? 30} seconds`}>
          {result?.cache
            ? `${result.cache.hit ? "Cached" : "Fetched"} result · ${cacheAge(result.cache.as_of)} · ${cacheTime(result.cache.as_of)}`
            : "Database result status unavailable"}
        </span>
        <button className="quiet" disabled={dataset.refreshing}
                onClick={() => onUpdate({ refreshNonce: (dataset.refreshNonce ?? 0) + 1,
                  refreshing: true })}>
          {dataset.refreshing ? "Refreshing…" : "Refresh data"}
        </button>
      </div>}

      {largeDataset && <div className="large-data-warning" role="status">
        <div>{scope === "database"
          ? `This source has ${result!.total.toLocaleString()} rows. Counts cover the full database, but large queries may take longer. Add filters to narrow the result.`
          : result?.sampled
            ? `This loaded preview has ${result!.total.toLocaleString()} rows. Counts cover only the loaded preview, not the full source. Add filters to narrow the preview.`
            : `This dataset has ${result!.total.toLocaleString()} loaded rows. Large queries may take longer. Add filters to narrow the result.`}</div>
      </div>}

      {chips.length > 0 && (
        <div className="chips">
          {chips.map((chip) => (
            <span key={chip.label} className="chip" onClick={chip.remove}>
              {chip.label} ✕
            </span>
          ))}
          <span className="chip clear" onClick={() => onUpdate({ filters: [] })}>
            Clear all
          </span>
        </div>
      )}

      <div className="cohort-bar">
        <span className="cohort-label">Cohorts</span>
        {cohorts.map((c) => (
          <span key={c.name} className="cohort-chip"
                title={`${c.filters.length} filter(s) — click ✕ to remove`}>
            {c.name}
            <button className="quiet" onClick={() => removeCohort(c.name)}>
              ✕
            </button>
          </span>
        ))}
        <input type="text" className="cohort-name"
               placeholder={filters.length
                 ? "name current filters…" : "set filters to save a cohort"}
               value={cohortName} disabled={filters.length === 0}
               onChange={(e) => setCohortName(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") saveCohort(); }} />
        <button onClick={saveCohort}
                disabled={!cohortName.trim() || filters.length === 0}>
          Save cohort
        </button>
        <button onClick={() => setShowCompare((v) => !v)}>
          {showCompare ? "Hide compare" : "Compare groups"}
        </button>
        <button onClick={() => setShowDerive((v) => !v)}>
          {showDerive ? "Hide calculated field" : "+ Calculated field"}
        </button>
        <button onClick={() => setShowAggregate((v) => !v)}>
          {showAggregate ? "Hide aggregation" : "+ Aggregation filter"}
        </button>
        <button onClick={() => setShowSummary((v) => !v)}>{showSummary ? "Hide summary" : "+ Group summary"}</button>
        <button onClick={() => setShowLaunch((v) => !v)}>
          {showLaunch ? "Hide workflow" : "Run workflow ▸"}
        </button>
      </div>

      {databaseScoped && <div className="settings-hint">
        Chat uses loaded rows and is unavailable for this full-source dataset.
      </div>}

      {showCompare && (
        <ComparePanel dataset={dataset} onClose={() => setShowCompare(false)} />
      )}

      {showDerive && (
        <DeriveColumn dataset={dataset} onUpdate={onUpdate}
                      onClose={() => setShowDerive(false)} />
      )}

      {showSummary && <GroupSummary dataset={dataset} onUpdate={onUpdate} onClose={() => setShowSummary(false)} />}

      {showAggregate && <AggregateFilter dataset={dataset} onUpdate={onUpdate}
        onClose={() => setShowAggregate(false)} />}

      {showLaunch && (
        <LaunchWorkflow dataset={dataset} onClose={() => setShowLaunch(false)}
                        onSubmitted={() => undefined} />
      )}

      {(databaseScoped || !chatOpen) && <AskAI dataset={dataset} onUpdate={onUpdate}
        databaseScoped={databaseScoped} onOpenChatDraft={(text) => {
          const id = chatDraftNumber + 1;
          setChatDraftNumber(id);
          setChatDraft({ id: `${dataset.id}-${id}`, text, datasetId: dataset.id });
        }} />}

      {databaseScoped ? null : <ChatWidget key={dataset.id} dataset={dataset}
        onUpdate={onUpdate} draft={chatDraft?.datasetId === dataset.id ? chatDraft : null}
        onOpenChange={setChatOpen} />}

      <AddChart dataset={dataset} onUpdate={onUpdate} />

      {dataset.queryError && <div className="query-error" role="alert">
        <span>{dataset.queryError}{result ? " Showing the last successful result." : ""}</span>
        <button type="button" className="quiet" onClick={() => onUpdate({
          refreshNonce: (dataset.refreshNonce ?? 0) + 1, refreshing: true,
        })}>Retry query</button>
      </div>}
      {!result && dataset.queryLoading && <p className="query-state" role="status">
        Loading data and charts…
      </p>}

      {result && <div className="chart-grid">
        {charts.map((spec, i) => (
          <ChartCard
            key={`${spec.kind}-${spec.x}-${spec.y ?? ""}-${i}`}
            spec={spec}
            result={result?.charts[i]}
            columnLabels={Object.fromEntries(dataset.columns.map((c) =>
              [c.name, c.label || c.name]))}
            palette={palette}
            kinds={allowedKinds(spec)}
            onTapCategory={toggleCategory}
            onChangeKind={(kind) => updateChart(i, { kind })}
            onRename={(title) => updateChart(i, { title: title || undefined })}
            onAxesChange={(x_axis, y_axis) => updateChart(i, { x_axis, y_axis })}
            onToggleWide={() => updateChart(i, { wide: !spec.wide })}
            onClose={() => updateChart(i, null)}
          />
        ))}
      </div>}

      {result && (
        <>
          <div className="section-label">Rows</div>
          {result.sampled && <div className="settings-hint">
            Counts and rows use the capped loaded sample. They do not describe
            the full source population.
          </div>}
          <table className="data-table">
            <thead>
              <tr>
                {result.rows.columns.map((c) => (
                  <th key={c} aria-sort={dataset.sort?.column === c ? dataset.sort.direction === "asc" ? "ascending" : "descending" : "none"}>
                    <button className="table-sort" onClick={() => onUpdate({ page: 0, sort: {
                      column: c, direction: dataset.sort?.column === c && dataset.sort.direction === "asc" ? "desc" : "asc" } })}>
                      {dataset.columns.find((col) => col.name === c)?.label || c}{dataset.sort?.column === c ? dataset.sort.direction === "asc" ? " ↑" : " ↓" : ""}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.data.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td key={j}>{cell === null ? "–" : String(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pager">
            <button disabled={dataset.page === 0}
                    onClick={() => onUpdate({ page: dataset.page - 1 })}>
              Prev
            </button>
            <span>page {dataset.page + 1} / {pageCount}</span>
            <button disabled={dataset.page + 1 >= pageCount}
                    onClick={() => onUpdate({ page: dataset.page + 1 })}>
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function SaveToAurora({ dataset }: { dataset: Dataset }) {
  const [open, setOpen] = useState(false);
  const [sources, setSources] = useState<Source[]>([]);
  const [resourceId, setResourceId] = useState("");
  const [table, setTable] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    api.datasources().then((out) => {
      const aurora = out.sources.filter((s) => s.kind === "aurora");
      setSources(aurora);
      if (aurora[0]) setResourceId(aurora[0].id);
    }).catch(() => undefined);
    if (!table) {
      setTable(dataset.title.replace(/\.[^.]+$/, "")
        .replace(/[^A-Za-z0-9_]/g, "_").toLowerCase().slice(0, 48));
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!resourceId || !table) return;
    setBusy(true);
    setStatus("");
    try {
      const out = await api.materialize(dataset.id, resourceId, table);
      setStatus(`Saved ${out.rows.toLocaleString()} rows to ${out.table}.`);
    } catch (e) {
      setStatus(`Failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return <button onClick={() => setOpen(true)}>Save to Aurora</button>;
  }
  return (
    <div className="save-aurora">
      <select value={resourceId} onChange={(e) => setResourceId(e.target.value)}>
        {sources.length === 0 && <option value="">No Aurora resource</option>}
        {sources.map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
      </select>
      <input type="text" placeholder="table_name" value={table}
             onChange={(e) => setTable(e.target.value)} />
      <button className="primary" onClick={save}
              disabled={busy || !resourceId || !table}>
        {busy ? "Saving…" : "Save"}
      </button>
      <button className="quiet" onClick={() => setOpen(false)}>✕</button>
      {status && <span className="ask-note">{status}</span>}
    </div>
  );
}

function AskAI({ dataset, onUpdate, databaseScoped, onOpenChatDraft }:
    { dataset: Dataset; onUpdate: (c: Partial<Dataset>) => void;
      databaseScoped: boolean; onOpenChatDraft: (text: string) => void }) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(
    () => (dataset.filterAskHistory?.length ?? 0) > 0);
  const historyId = useId();
  const history = dataset.filterAskHistory ?? [];

  const ask = async () => {
    if (!question.trim()) return;
    if (!databaseScoped) {
      onOpenChatDraft(question.trim());
      setQuestion("");
      return;
    }
    setBusy(true);
    const asked = question.trim();
    try {
      const out = await api.ask(dataset.id, asked, dataset.filters);
      onUpdate({
        filters: out.filters,
        filterAskHistory: [...history, {
          question: asked,
          answer: (out.explanation || "Filters updated.").slice(0, 4000),
        }].slice(-25),
      });
      setHistoryOpen(true);
      setQuestion("");
    } catch (e) {
      onUpdate({
        filterAskHistory: [...history, {
          question: asked,
          error: safeFilterAskError(e),
        }].slice(-25),
      });
      setHistoryOpen(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ask-ai" style={databaseScoped ? { flexWrap: "wrap" } : undefined}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="2">
        <path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4L12 3z" />
      </svg>
      <input
        type="text"
        maxLength={2000}
        placeholder={databaseScoped
          ? 'Ask AI to filter — e.g. "liver samples with RIN above 7"'
          : "Ask the assistant…"}
        value={question}
        disabled={busy}
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") ask(); }}
      />
      <button className="primary" onClick={ask}
              disabled={busy || !question.trim()}>
        {databaseScoped ? (busy ? "Thinking…" : "Ask") : "Open chat"}
      </button>
      {databaseScoped && history.length > 0 && (
        <div className="filter-ask-history"
             style={{ flexBasis: "100%", color: "var(--ink)" }}>
          <button type="button" className="quiet"
                  aria-expanded={historyOpen} aria-controls={historyId}
                  onClick={() => setHistoryOpen((open) => !open)}>
            Question history ({history.length})
            <span>{historyOpen ? "Hide" : "Show"}</span>
          </button>
          {historyOpen && (
            <div id={historyId} role="log" aria-label="Question history">
              {history.map((entry, index) => (
                <article className="filter-ask-entry"
                         style={{ borderTop: "1px solid var(--border)", padding: "8px 0" }}
                         key={`${index}-${entry.question}`}>
                  <p><strong>Question</strong><br />{entry.question}</p>
                  {entry.answer && <p><strong>Answer</strong><br />{entry.answer}</p>}
                  {entry.error && <p role="alert"><strong>Could not apply filters</strong><br />{entry.error}</p>}
                </article>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AddChart({ dataset, onUpdate }:
    { dataset: Dataset; onUpdate: (c: Partial<Dataset>) => void }) {
  const numeric = dataset.columns
    .filter((c) => c.filter_kind === "range").map((c) => c.name);
  const all = dataset.columns.map((c) => c.name);
  const [error, setError] = useState("");
  const [chartKind, setChartKind] = useState("auto");

  const submit = (form: HTMLFormElement) => {
    const data = new FormData(form);
    const kind = data.get("kind") as ChartSpec["kind"] | "auto";
    const x = data.get("x") as string;
    const y = (data.get("y") as string) || undefined;
    if (!x) return;
    const col = dataset.columns.find((c) => c.name === x);
    const resolved: ChartSpec["kind"] = kind === "auto"
      ? (col?.filter_kind === "range" ? "histogram" : "bar") : kind;
    if (resolved === "map" && (!y || x === y || !numeric.includes(x) || !numeric.includes(y))) {
      setError("Map requires numeric longitude and latitude columns.");
      return;
    }
    setError("");
    const spec: ChartSpec = { kind: resolved, x, y,
      wide: resolved === "scatter" || resolved === "heatmap" || resolved === "map" };
    onUpdate({ charts: [...dataset.charts, spec] });
    form.reset();
    setChartKind("auto");
  };

  return (
    <form
      style={{ display: "flex", gap: 8, alignItems: "end", margin: "10px 0" }}
      onSubmit={(e) => { e.preventDefault(); submit(e.currentTarget); }}
    >
      <div style={{ width: 220 }}>
        <div className="field-label">{chartKind === "map" ? "Longitude" : "Add chart"}</div>
        <select name="x" defaultValue="">
          <option value="" disabled>Choose a column…</option>
          {all.map((c) => <option key={c}>{c}</option>)}
        </select>
      </div>
      <div style={{ width: 120 }}>
        <div className="field-label">Type</div>
        <select name="kind" value={chartKind} onChange={e => setChartKind(e.target.value)}>
          {["auto", "bar", "histogram", "scatter", "heatmap", "map"].map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
      </div>
      <div style={{ width: 160 }}>
        <div className="field-label">{chartKind === "map" ? "Latitude" : "Second field"}</div>
        <select name="y" defaultValue="">
          <option value="">—</option>
          {numeric.map((c) => <option key={c}>{c}</option>)}
        </select>
      </div>
      <button className="primary" type="submit">Add</button>
      {error && <span role="alert">{error}</span>}
    </form>
  );
}
