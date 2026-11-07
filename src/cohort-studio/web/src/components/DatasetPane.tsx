import { useEffect, useId, useState } from "react";
import { api } from "../api";
import type { ExportJob, OpenResult } from "../api";
import type { ChartMeasure, ChartSpec, ChartStyle, Dataset, Filter, MarkType, MeasureAgg, Source } from "../types";
import { ChartCard } from "./ChartCard";
import { isMeasured, MEASURE_LABEL, measureFields, resolveMark, seriesFields } from "./MarksMenu";
import { ChatWidget } from "./ChatWidget";
import { Popover } from "./Popover";
import { CriteriaGroups } from "./CriteriaGroups";
import { useAiFeatures, usePlink } from "../features";
import { extractTarget } from "../extract";
import { describeFilter } from "../filterText";
import { DatasetSettings } from "./DatasetSettings";
import { ComparePanel } from "./ComparePanel";
import { DeriveColumn } from "./DeriveColumn";
import { AggregateFilter } from "./AggregateFilter";
import { GroupSummary } from "./GroupSummary";
import { LaunchWorkflow } from "./LaunchWorkflow";
import { PlinkExport } from "./PlinkExport";

const NO_FILTERS: Filter[] = [];

interface Props {
  dataset: Dataset;
  /** Dashboard filters that apply to this tab; the query adds them to the tab's own filters. */
  dashboardFilters?: Filter[];
  palette: string;
  onUpdate: (changes: Partial<Dataset>) => void;
  /** Reopens a joined tab's recipe on the visual join canvas. */
  onEditJoinCanvas?: (datasetId: string) => void;
  /** Opens a result (e.g. a full group summary) as a new dataset tab. */
  onOpenTable?: (opened: OpenResult, title: string) => void;
  /** Reruns this extract tab's recipe and replaces its rows. */
  onRefreshExtract?: (datasetId: string) => void;
  /** Opens this extract's recipe in Data Builder to change and rewrite it. */
  onEditExtract?: (datasetId: string) => void;
}


function ExtractBar({ dataset, onUpdate, onRefresh, onEdit }: {
  dataset: Dataset; onUpdate: (changes: Partial<Dataset>) => void; onRefresh?: (id: string) => void;
  onEdit?: (id: string) => void;
}) {
  const target = extractTarget(dataset);
  const key = target ? `${target.resource_id}/${target.table}` : "";
  useEffect(() => {
    if (!target || dataset.extract !== undefined) return;
    let stale = false;
    api.extractInfo(target.resource_id, target.table)
      .then((out) => { if (!stale) onUpdate({ extract: out.extract }); })
      .catch(() => { if (!stale) onUpdate({ extract: null }); });
    return () => { stale = true; };
  }, [key, dataset.extract === undefined]); // eslint-disable-line react-hooks/exhaustive-deps
  const info = dataset.extract;
  if (!target || !info) return null;
  const refreshed = new Date(info.refreshed_at);
  return (
    <div className="extract-bar" role="group" aria-label="Extract"
         title={`Extract of ${info.rows.toLocaleString()} rows, refreshed ${refreshed.toLocaleString()}`}>
      <span className="extract-chip">Extract</span>
      <span>refreshed <time dateTime={info.refreshed_at}>{cacheAge(info.refreshed_at)}</time></span>
      <button type="button" className="quiet" disabled={!info.refreshable || dataset.extractRefreshing || !onRefresh}
              title={info.refreshable ? "Rerun the join and replace every row of this table"
                : "This extract's inputs (for example an uploaded file) can't be reopened, so it can't be refreshed."}
              onClick={() => onRefresh?.(dataset.id)}>
        {dataset.extractRefreshing ? "Refreshing…" : "Refresh extract"}
      </button>
      {onEdit && (info.recipe?.kind === "join" || info.recipe?.kind === "sql") && (
        <button type="button" className="quiet" disabled={dataset.extractRefreshing}
                title="Open the joins or SQL behind this extract, change them, and save over it"
                onClick={() => onEdit(dataset.id)}>Edit in Data Builder</button>
      )}
    </div>
  );
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

export function DatasetPane({ dataset, dashboardFilters = NO_FILTERS, palette, onUpdate, onEditJoinCanvas, onOpenTable,
                             onRefreshExtract, onEditExtract }: Props) {
  const aiFeatures = useAiFeatures();
  const plinkExport = usePlink();
  const { result, filters, charts } = dataset;
  // The rows the user sees: this tab's filters and the dashboard filters. Exports, compare,
  // summaries and workflows read these; edits (chips, cohorts, OR groups) keep the tab's own.
  const scoped = dashboardFilters.length ? { ...dataset, filters: [...filters, ...dashboardFilters] } : dataset;
  const [exportJob, setExportJob] = useState<ExportJob | null>(null);
  const [exportError, setExportError] = useState("");
  const [exportFormat, setExportFormat] = useState<"tsv" | "tsv.gz" | "parquet" | "json" | "duckdb">("tsv");
  useEffect(() => { setExportFormat("tsv"); }, [dataset.id]);
  const [cancelingExport, setCancelingExport] = useState(false);
  const [creatingExport, setCreatingExport] = useState(false);
  const cohorts = dataset.cohorts ?? [];
  const [showCompare, setShowCompare] = useState(false);
  const [showDerive, setShowDerive] = useState(false);
  const [showAggregate, setShowAggregate] = useState(false);
  const [showGroups, setShowGroups] = useState(false);
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

  // Chart clicks select: a plain click selects only that category (again clears it),
  // Ctrl/⌘/Shift-click adds or removes one. The selection is the tab's categorical filter
  // on the chart's field, so every chart on the tab follows it.
  const [lastSelected, setLastSelected] = useState<string | null>(null);
  useEffect(() => { setLastSelected(null); }, [dataset.id]);
  const selectionOf = (column: string) =>
    filters.find((f) => f.column === column && f.kind === "categorical")?.values ?? [];
  const setSelection = (column: string, values: string[]) => {
    const rest = filters.filter((f) => f.column !== column);
    onUpdate({ filters: values.length ? [...rest, { column, kind: "categorical", values }] : rest });
  };
  const selectCategory = (column: string, value: string, additive: boolean) => {
    const current = selectionOf(column);
    setSelection(column, additive
      ? (current.includes(value) ? current.filter((v) => v !== value) : [...current, value])
      : (current.length === 1 && current[0] === value ? [] : [value]));
    setLastSelected(column);
  };
  // Esc clears the selection of the chart clicked last, unless Esc is closing a menu or editing a field.
  useEffect(() => {
    if (!lastSelected) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable], [role=dialog]")) return;
      if (document.querySelector(".popover-panel:not([hidden]), [role=dialog]")) return;
      if (selectionOf(lastSelected).length) setSelection(lastSelected, []);
      setLastSelected(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  const chips: { label: string; title?: string; remove: () => void }[] = [];
  for (const f of filters) {
    if (f.kind === "any") {
      const n = f.groups?.length ?? 0;
      chips.push({
        label: `any of ${n} group${n === 1 ? "" : "s"}`,
        title: describeFilter(f),
        remove: () => onUpdate({ filters: filters.filter((o) => o !== f) }),
      });
    } else if (f.kind === "categorical") {
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
        ? ["scatter", "heatmap", "map", "box"] : isNumeric(spec.x) ? ["heatmap", "box"] : ["heatmap"];
    } else {
      base = isNumeric(spec.x) ? ["bar", "histogram", "box"] : ["bar"];
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
      if (databaseScoped) {
        if (exportFormat === "duckdb") throw new Error("DuckDB export is not available for Aurora yet.");
        setExportJob(await api.createExport(dataset.id, scoped.filters, exportFormat));
      }
      else await api.export(dataset.id, scoped.filters, exportFormat);
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
        <div className="hero-line">
            <span className="hero-meta">
              <span className="hero-source" title={dataset.source}>{dataset.source}</span>
              {databaseScoped && <>
                <span className="settings-hint" title={result?.cache
                  ? `${result.cache.hit ? "Cached" : "Fetched"} ${cacheTime(result.cache.as_of)} · cache TTL ${result.cache.ttl_seconds ?? 30} s`
                  : "Database result status unavailable"}>
                  {" · "}{result?.cache ? `${result.cache.hit ? "cached" : "fetched"} ${cacheAge(result.cache.as_of)}` : "status unavailable"}
                </span>
                <button type="button" className="icon-button" aria-label={dataset.refreshing ? "Refreshing…" : "Refresh data"}
                        title={dataset.refreshing ? "Refreshing…" : "Refresh data"} disabled={dataset.refreshing}
                        onClick={() => onUpdate({ refreshNonce: (dataset.refreshNonce ?? 0) + 1,
                          refreshing: true })}>
                  <span aria-hidden className={dataset.refreshing ? "spin" : undefined}>↻</span>
                </button>
              </>}
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
        <ExtractBar dataset={dataset} onUpdate={onUpdate} onRefresh={onRefreshExtract} onEdit={onEditExtract} />
        {dataset.sourceRef?.kind === "join" && onEditJoinCanvas && <button className="quiet"
          title="Reopen this join in Data Builder"
          onClick={() => onEditJoinCanvas(dataset.id)}>Edit in Data Builder</button>}
        <DatasetSettings dataset={dataset} onUpdate={onUpdate} />
        <Popover label={<>Export <span aria-hidden>▾</span></>} ariaLabel="Export options" className="export-menu">
        <div className="popover-row">
        <label className="inline-field format-select">Format <select aria-label="Export format" value={exportFormat} disabled={exportRunning || creatingExport || Boolean(exportJob)} onChange={e => setExportFormat(e.target.value as "tsv" | "tsv.gz" | "parquet" | "json" | "duckdb")}><option value="tsv">TSV</option><option value="tsv.gz">TSV.gz</option><option value="parquet">Parquet</option><option value="json">JSON</option>{!databaseScoped && <option value="duckdb">DuckDB</option>}</select></label>
        <button onClick={startExport} disabled={exportRunning || creatingExport || Boolean(exportJob)}>
          {creatingExport ? "Starting export…" : `Export ${{tsv: "TSV", "tsv.gz": "TSV.gz", parquet: "Parquet", json: "JSON", duckdb: "DuckDB"}[exportFormat]}`}
        </button>
        </div>
        {plinkExport && <PlinkExport key={dataset.id} dataset={scoped} />}
        <button onClick={() => { void import("../pdf").then(({ captureCharts, captureGroupSummary, exportDatasetPdf }) =>
          exportDatasetPdf(scoped, captureCharts(), captureGroupSummary())).catch(() => setExportError("Could not load PDF export. Try again.")); }}
                disabled={!result}>
          Export PDF
        </button>
        <SaveToAurora dataset={dataset} />
        </Popover>
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
          Download {{tsv: "TSV", "tsv.gz": "TSV.gz", parquet: "Parquet", json: "JSON", duckdb: "DuckDB"}[exportFormat]}{exportJob.bytes ? ` · ${formatBytes(exportJob.bytes)}` : ""}
        </a>}
        {!exportRunning && <button className="quiet" onClick={clearExport}
                                    disabled={cancelingExport}>
          {cancelingExport ? "Clearing…" : "Clear export"}
        </button>}
      </div>}
      {exportError && <div className="settings-hint" role="alert">{exportError}</div>}

      {dataset.sourceInfo?.format === "vcf" && <div className="large-data-warning" role="status">
        <div>{dataset.sourceInfo.note}</div>
        <div>Reference header (not verified): {dataset.sourceInfo.reference || "not specified"} · {dataset.sourceInfo.sample_count.toLocaleString()} samples · {dataset.sourceInfo.calls.toLocaleString()} calls</div>
      </div>}
      {largeDataset && scope !== "database" && <div className="large-data-warning" role="status">
        <div>{result?.sampled
            ? `This loaded preview has ${result!.total.toLocaleString()} rows. Counts cover only the loaded preview, not the full source. Add filters to narrow the preview.`
            : `This dataset has ${result!.total.toLocaleString()} loaded rows. Large queries may take longer. Add filters to narrow the result.`}</div>
      </div>}

      {chips.length > 0 && (
        <div className="chips">
          {chips.map((chip) => (
            <span key={chip.label} className="chip" onClick={chip.remove} title={chip.title}>
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
        <span className="hero cohort-size" aria-label="Cohort size">
          <span className="count">
            {result ? (dataset.entityColumn && entityCount
              ? entityCount.filtered.toLocaleString()
              : result.filtered.toLocaleString()) : "…"}
          </span>
            <span className="detail">
              {dataset.entityColumn && entityCount
                ? `of ${entityCount.total.toLocaleString()} unique ${dataset.columns.find((c) => c.name === entityCount.column)?.label || entityCount.column}`
                // Unfiltered: "1,392,882 rows", not "1,392,882 of 1,392,882 rows".
                : result && result.filtered === result.total ? "rows" : `of ${result?.total.toLocaleString() ?? "…"} rows`}
              {" · "}{scope === "database" ? "full database"
                : result?.sampled ? "capped loaded sample" : "in memory"}
            </span>
        </span>
        {cohorts.map((c) => (
          <span key={c.name} className={`cohort-chip${JSON.stringify(c.filters) === JSON.stringify(filters) ? " active" : ""}`}>
            <button type="button" className="quiet cohort-apply"
                    title={`Apply ${c.name}: ${c.filters.length} filter(s)`}
                    aria-label={`Apply cohort ${c.name}`}
                    onClick={() => onUpdate({ filters: c.filters, page: 0 })}>{c.name}</button>
            <button className="quiet" aria-label={`Remove cohort ${c.name}`} title="Remove cohort"
                    onClick={() => removeCohort(c.name)}>
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
        <Popover label={<>+ Add <span aria-hidden>▾</span></>} ariaLabel="Add to this view" align="left">
          {(close) => <div className="popover-menu">
            <button onClick={() => { setShowDerive((v) => !v); close(); }}>
              {showDerive ? "Hide calculated field" : "+ Calculated field"}
            </button>
            <button onClick={() => { setShowAggregate((v) => !v); close(); }}>
              {showAggregate ? "Hide aggregation" : "+ Aggregation filter"}
            </button>
            <button onClick={() => { setShowSummary((v) => !v); close(); }}>{showSummary ? "Hide summary" : "+ Group summary"}</button>
            <button onClick={() => { setShowGroups((v) => !v); close(); }}>{showGroups ? "Hide OR groups" : "+ Match any group (OR)"}</button>
          </div>}
        </Popover>
        <button onClick={() => setShowLaunch((v) => !v)}>
          {showLaunch ? "Hide workflow" : "Run workflow ▸"}
        </button>
      </div>

      {databaseScoped && aiFeatures && <div className="settings-hint">
        Chat uses loaded rows and is unavailable for this full-source dataset.
      </div>}

      {showCompare && (
        <ComparePanel dataset={dataset} scope={dashboardFilters} onClose={() => setShowCompare(false)} />
      )}

      {showDerive && (
        <DeriveColumn dataset={dataset} onUpdate={onUpdate}
                      onClose={() => setShowDerive(false)} />
      )}

      {showGroups && <CriteriaGroups columns={dataset.columns} filters={filters} parameters={dataset.parameters ?? []}
        onChange={(next) => onUpdate({ filters: next, page: 0 })} onClose={() => setShowGroups(false)} />}
      {showSummary && <GroupSummary dataset={scoped}onUpdate={onUpdate} onOpenTable={onOpenTable}
        onClose={() => { setShowSummary(false); onUpdate({ groupSummary: undefined }); }} />}

      {showAggregate && <AggregateFilter dataset={dataset} onUpdate={onUpdate}
        onClose={() => setShowAggregate(false)} />}

      {showLaunch && (
        <LaunchWorkflow dataset={scoped}onClose={() => setShowLaunch(false)}
                        onSubmitted={() => undefined} />
      )}

      {aiFeatures && (databaseScoped || !chatOpen) && <AskAI dataset={dataset} onUpdate={onUpdate}
        databaseScoped={databaseScoped} onOpenChatDraft={(text) => {
          const id = chatDraftNumber + 1;
          setChatDraftNumber(id);
          setChatDraft({ id: `${dataset.id}-${id}`, text, datasetId: dataset.id });
        }} />}

      {databaseScoped || !aiFeatures ? null : <ChatWidget key={dataset.id} dataset={dataset}
        onUpdate={onUpdate} draft={chatDraft?.datasetId === dataset.id ? chatDraft : null}
        onOpenChange={setChatOpen} />}

      <div className="chart-tools">
        <AddChart dataset={dataset} onUpdate={onUpdate} />
        <label className="chart-columns">Charts per row
          <select aria-label="Charts per row" value={String(dataset.chartColumns ?? 0)}
                  onChange={(e) => onUpdate({ chartColumns: Number(e.target.value) as 0 | 1 | 2 | 3 | 4 })}>
            <option value="0">Auto (fill screen)</option>
            {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
      </div>

      {dataset.queryError && <div className="query-error" role="alert">
        <span>{dataset.queryError}{result ? " Showing the last successful result." : ""}</span>
        <button type="button" className="quiet" onClick={() => onUpdate({
          refreshNonce: (dataset.refreshNonce ?? 0) + 1, refreshing: true,
        })}>Retry query</button>
      </div>}
      {!result && dataset.queryLoading && <p className="query-state" role="status">
        Loading data and charts…
      </p>}

      {result && <div className="chart-grid" data-cols={dataset.chartColumns ? String(dataset.chartColumns) : undefined}>
        {charts.map((spec, i) => (
          <ChartCard
            key={`${spec.kind}-${spec.x}-${spec.y ?? ""}-${i}`}
            spec={spec}
            result={result?.charts[i]}
            columnLabels={Object.fromEntries(dataset.columns.map((c) =>
              [c.name, c.label || c.name]))}
            palette={palette}
            kinds={allowedKinds(spec)}
            onTapCategory={selectCategory}
            selection={selectionOf(spec.x)}
            onClearSelection={() => setSelection(spec.x, [])}
            onChangeKind={(kind, style, mark) => updateChart(i, kind === "bar" ? { kind, style, mark }
              : { kind, style, mark, measure: undefined, series: undefined })}
            onMarksChange={(marks) => updateChart(i, { marks })}
            fields={dataset.columns}
            onDataChange={(changes) => updateChart(i, changes)}
            onRename={(title) => updateChart(i, { title: title || undefined })}
            onAxesChange={(x_axis, y_axis, references) => updateChart(i, { x_axis, y_axis, references })}
            parameters={dataset.parameters}
            onToggleWide={() => updateChart(i, { wide: !spec.wide })}
            onClose={() => updateChart(i, null)}
            onMove={(delta) => {
              const j = i + delta;
              if (j < 0 || j >= charts.length) return;
              // Move the loaded results with their charts so no card shows another chart's data.
              const swap = <T,>(list: T[]) => { const next = [...list]; [next[i], next[j]] = [next[j], next[i]]; return next; };
              onUpdate({ charts: swap(charts),
                         ...(result ? { result: { ...result, charts: swap(result.charts) } } : {}) });
            }}
            canMoveUp={i > 0} canMoveDown={i < charts.length - 1}
            onDuplicate={() => {
              const copy = { ...spec, title: `${spec.title || (dataset.columns.find((c) => c.name === spec.x)?.label ?? spec.x)} (copy)` };
              const insert = <T,>(list: T[], item: T) => [...list.slice(0, i + 1), item, ...list.slice(i + 1)];
              onUpdate({ charts: insert(charts, copy),
                         ...(result ? { result: { ...result, charts: insert(result.charts, result.charts[i]) } } : {}) });
            }}
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
      // Every row is written (no row cap); the recipe is kept so the table can be refreshed.
      const out = await api.extract(dataset.id, "aurora", resourceId, table, dataset.title, (job) => {
        const rows = job.detail?.rows;
        if (typeof rows === "number" && rows > 0) setStatus(`Saving… ${rows.toLocaleString()} rows written`);
      });
      void api.closeDataset(out.dataset_id).catch(() => undefined);
      setStatus(`Saved ${(out.extract?.rows ?? 0).toLocaleString()} rows to ${table}.`);
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
  const [agg, setAgg] = useState<MeasureAgg>("count");
  const [chartX, setChartX] = useState("");
  const measureChoices = measureFields(dataset.columns, agg, chartX);

  const submit = (form: HTMLFormElement) => {
    const data = new FormData(form);
    const picked = data.get("kind") as string;
    const measureColumn = (data.get("measure_column") as string) || undefined;
    const series = (data.get("series") as string) || undefined;
    if (agg !== "count" && !measureColumn) { setError(`Choose a field for ${MEASURE_LABEL[agg]}.`); return; }
    const measure: ChartMeasure | undefined = agg !== "count" && measureColumn ? { agg, column: measureColumn } : undefined;
    // Styles (column, line, area, pie, donut) draw bar or histogram counts.
    const styleKinds: Record<string, ChartStyle> = { column: "column", line: "line", area: "area", pie: "pie", donut: "donut" };
    const style = styleKinds[picked];
    const kind = (style ? "auto" : picked) as ChartSpec["kind"] | "auto";
    const x = data.get("x") as string;
    const y = (data.get("y") as string) || undefined;
    if (!x) return;
    const col = dataset.columns.find((c) => c.name === x);
    const numericX = col?.filter_kind === "range";
    const measured = isMeasured({ measure, series });
    const resolved: ChartSpec["kind"] = kind === "auto"
      ? (numericX && !measured && style !== "pie" && style !== "donut" ? "histogram" : "bar") : kind;
    if (resolved === "map" && (!y || x === y || !numeric.includes(x) || !numeric.includes(y))) {
      setError("Map requires numeric longitude and latitude columns.");
      return;
    }
    if (resolved === "box" && (!numeric.includes(x) || x === y)) {
      setError("Box needs a numeric field; Group by is optional.");
      return;
    }
    if (measured && (resolved !== "bar" || (y && !style))) {
      setError("Measure and Split by apply to bar, column, line and area charts of one field.");
      return;
    }
    if (series === x) { setError("Split by needs a field other than the chart field."); return; }
    if (measured && style && typeof resolveMark(style as MarkType, ["bar"], false, { measure, series }) === "string") {
      setError(resolveMark(style as MarkType, ["bar"], false, { measure, series }) as string);
      return;
    }
    setError("");
    const spec: ChartSpec = { kind: resolved, x, ...(style ? { style, y: undefined } : { y }),
      ...(measure ? { measure } : {}), ...(series ? { series } : {}),
      wide: resolved === "scatter" || resolved === "heatmap" || resolved === "map" || Boolean(series) };
    onUpdate({ charts: [...dataset.charts, spec] });
    form.reset();
    setChartKind("auto");
    setAgg("count");
    setChartX("");
  };

  return (
    <form data-tutorial-target="add-chart"
      style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "end", margin: "10px 0" }}
      onSubmit={(e) => { e.preventDefault(); submit(e.currentTarget); }}
    >
      <div style={{ width: 220 }}>
        <div className="field-label">{chartKind === "map" ? "Longitude" : "Add chart"}</div>
        <select name="x" value={chartX} onChange={(e) => setChartX(e.target.value)}>
          <option value="" disabled>Choose a column…</option>
          {all.map((c) => <option key={c}>{c}</option>)}
        </select>
      </div>
      <div style={{ width: 120 }}>
        <div className="field-label">Type</div>
        <select name="kind" value={chartKind} onChange={e => setChartKind(e.target.value)}>
          {["auto", "bar", "column", "line", "area", "pie", "donut", "histogram", "box", "scatter", "heatmap", "map"].map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
      </div>
      <div style={{ width: 160 }}>
        <div className="field-label">{chartKind === "map" ? "Latitude" : chartKind === "box" ? "Group by" : "Second field"}</div>
        <select name="y" defaultValue="">
          <option value="">—</option>
          {(chartKind === "box" ? seriesFields(dataset.columns, chartX).map((c) => c.name) : numeric).map((c) => <option key={c}>{c}</option>)}
        </select>
      </div>
      <div style={{ width: 130 }}>
        <div className="field-label">Measure</div>
        <select aria-label="New chart measure" value={agg} onChange={(e) => setAgg(e.target.value as MeasureAgg)}>
          {(Object.keys(MEASURE_LABEL) as MeasureAgg[]).map((a) => <option key={a} value={a}
            disabled={a !== "count" && measureFields(dataset.columns, a, chartX).length === 0}>{MEASURE_LABEL[a]}</option>)}
        </select>
      </div>
      {agg !== "count" && <div style={{ width: 150 }}>
        <div className="field-label">Of</div>
        <select name="measure_column" aria-label="New chart measure field" key={agg}
                defaultValue={measureChoices[0]?.name ?? ""}>
          {measureChoices.map((c) => <option key={c.name} value={c.name}>{c.label || c.name}</option>)}
        </select>
      </div>}
      <div style={{ width: 140 }}>
        <div className="field-label">Split by</div>
        <select name="series" aria-label="New chart split by" defaultValue="">
          <option value="">None</option>
          {seriesFields(dataset.columns, chartX).map((c) => <option key={c.name} value={c.name}>{c.label || c.name}</option>)}
        </select>
      </div>
      <button className="primary" type="submit">Add</button>
      {error && <span role="alert">{error}</span>}
    </form>
  );
}
