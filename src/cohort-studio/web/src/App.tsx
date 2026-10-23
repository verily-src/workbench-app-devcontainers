import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, OpenResult, WorkflowList } from "./api";
import { OmopBuilder } from "./components/OmopBuilder";
import { DatasetPane } from "./components/DatasetPane";
import { FilterPanel } from "./components/FilterPanel";
import { LineageView } from "./components/LineageView";
import { SettingsView } from "./components/SettingsView";
import { SavedViews } from "./components/SavedViews";
import { JoinPanel } from "./components/JoinPanel";
import { PublishCatalog } from "./components/PublishCatalog";
import { WorkflowsView } from "./components/WorkflowsView";
import { Toasts } from "./components/Toasts";
import { BrandMark } from "./components/BrandMark";
import { CommandPalette, Command } from "./components/CommandPalette";
import { useWorkflowAlerts } from "./workflowAlerts";
import { api as apiClient } from "./api";
import type { ChartSpec, Dataset, JoinStats, JoinStep, Source, TableInfo } from "./types";

const AUTO_CHART_LIMIT = 8;

class JoinRecoveryError extends Error {}

function autoCharts(columns: Dataset["columns"]): ChartSpec[] {
  const specs: ChartSpec[] = [];
  for (const col of columns) {
    if (col.filter_kind === "categorical" && (col.values?.length ?? 0) >= 2) {
      specs.push({ kind: "bar", x: col.name });
    } else if (col.filter_kind === "range") {
      specs.push({ kind: "histogram", x: col.name });
    }
  }
  return specs.slice(0, AUTO_CHART_LIMIT);
}

function VersionFooter() {
  const [sha, setSha] = useState("");
  const [updating, setUpdating] = useState(false);

  useEffect(() => {
    api.version().then((v) => setSha(v.sha)).catch(() => undefined);
  }, []);

  const update = async () => {
    setUpdating(true);
    try {

      const before = (await api.version()).sha;
      setSha(before);
      await api.adminUpdate();

      for (let i = 0; i < 60; i++) {
        await new Promise((r) => setTimeout(r, 5000));
        try {
          const v = await api.version();
          if (v.sha !== before) { window.location.reload(); return; }
        } catch {  }
      }
    } finally {
      setUpdating(false);
    }
  };

  return (
    <div className="version-footer">
      <span>{sha ? sha.slice(0, 9) : "…"}</span>
      <button className="quiet" disabled={updating} onClick={update}>
        {updating ? "Updating…" : "Update app"}
      </button>
    </div>
  );
}

export default function App() {
  const [sources, setSources] = useState<Source[]>([]);
  const [ready, setReady] = useState(false);
  const [sourceKey, setSourceKey] = useState("");
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [table, setTable] = useState("");
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [active, setActive] = useState(0);
  const [activity, setActivity] = useState("");
  const [error, setError] = useState("");
  const [view, setView] = useState<
    "explore" | "workflows" | "lineage" | "settings">("explore");
  const [exploreModes, setExploreModes] = useState<Record<string, "tables" | "omop">>({});
  const [palette, setPalette] = useState("verily");
  const [showJoin, setShowJoin] = useState(false);
  const [workflows, setWorkflows] = useState<WorkflowList | null>(null);
  const [cmdOpen, setCmdOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const consumedRefreshNonce = useRef<Record<string, number>>({});
  const alerts = useWorkflowAlerts();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    apiClient.config().then((c) => setPalette(c.chart_palette))
      .catch(() => undefined);

    api.workflows().then(setWorkflows).catch(() => undefined);
  }, []);
  const pollRef = useRef<number>();

  useEffect(() => {
    const poll = async () => {
      try {
        const out = await api.datasources();
        setSources(out.sources);
        if (out.ready) setReady(true);

        if (out.ready && out.sources.length > 0 && !out.catalogs_pending) {
          window.clearInterval(pollRef.current);
        }
      } catch {  }
    };
    poll();
    pollRef.current = window.setInterval(poll, 3000);
    return () => window.clearInterval(pollRef.current);
  }, []);

  const source = sources.find((s) => `${s.kind}:${s.id}` === sourceKey);
  const exploreMode = source?.kind === "aurora"
    ? exploreModes[sourceKey] ?? "tables" : "tables";
  const setExploreMode = (mode: "tables" | "omop") => {
    if (source?.kind === "aurora") {
      setExploreModes((previous) => ({ ...previous, [sourceKey]: mode }));
      if (mode === "omop") setView("explore");
    }
  };
  const showExploreTables = () => {
    setExploreModes({});
    setView("explore");
  };

  useEffect(() => {
    if (!source) return;
    setTables([]);
    setTable("");
    setActivity(`Listing tables in ${source.id}…`);
    api.tables(source.kind, source.id)
      .then((t) => {
        setTables(t);
        if (!t.length) setError(`No tables or data files in ${source.id}.`);
      })
      .catch((e) => setError(`Could not list tables: ${e.message}`))
      .finally(() => setActivity(""));
  }, [sourceKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const openResult = (
    opened: OpenResult, title: string,
    sourceRef?: Dataset["sourceRef"],
    initial?: { filters: Dataset["filters"]; charts: Dataset["charts"];
      entityColumn?: string },
    options?: { forceNewTab?: boolean },
  ) => {
    showExploreTables();
    const forceNewTab = options?.forceNewTab ?? false;
    const existing = datasets.findIndex((d) => d.source === opened.source);
    if (existing >= 0 && !initial && !forceNewTab) {
      setActive(existing);
      return;
    }
    const ds: Dataset = {
      id: opened.dataset_id,
      title,
      source: opened.source,
      sourceRef: opened.source_ref ?? sourceRef,
      queryScope: opened.query_scope,
      entityColumn: initial?.entityColumn,
      columns: opened.columns,
      filters: initial?.filters ?? [],
      charts: initial?.charts ?? autoCharts(opened.columns),
      page: 0,
    };
    setDatasets((prev) => {
      const next = forceNewTab ? prev : prev.filter((d) => d.source !== opened.source);
      setActive(next.length);
      return [...next, ds];
    });
  };

  const openTableDirect = async (src: Source, tbl: string) => {
    setActivity(`Loading ${tbl}…`);
    setError("");
    try {
      const info = tables.find((t) => t.name === tbl);
      const opened = src.kind === "aurora" && info?.schema && info?.table
        ? await api.openSourceRef({ kind: "aurora", resource_id: src.id,
            table: info.table, schema: info.schema })
        : await api.openDataset(src.kind, src.id, tbl);
      openResult(opened, tbl.split("/").pop() ?? tbl,
        { kind: src.kind, resource_id: src.id, table: tbl, uuid: src.uuid });
      setView("explore");
    } catch (e) {
      setError(`Load failed: ${(e as Error).message}`);
    } finally {
      setActivity("");
    }
  };

  const loadTable = async () => {
    if (!source || !table) return;
    await openTableDirect(source, table);
  };

  const uploadCsv = async (file: File) => {
    setActivity(`Loading ${file.name}…`);
    setError("");
    try {
      openResult(await api.uploadDataset(file), file.name);
    } catch (e) {
      setError(`Upload failed: ${(e as Error).message}`);
    } finally {
      setActivity("");
    }
  };

  const loadView = async (store: { kind: string; id: string },
                          name: string) => {
    setActivity(`Loading view ${name}…`);
    setError("");
    try {
      const v = await api.getView(store.kind, store.id, name);
      const specs = v.datasets ?? [];
      const opened = await Promise.all(specs.map((d) =>
        api.openSourceRef(d.source)
          .then((o) => ({ o, d }))));
      const restored: Dataset[] = opened.map(({ o, d }) => ({
        id: o.dataset_id,
        title: d.title || (d.source.kind === "join" ? "Joined dataset"
          : d.source.kind === "derived" ? d.source.spec.name
            : d.source.table.split("/").pop()) || "view",
        source: o.source,
        sourceRef: o.source_ref ?? d.source,
        queryScope: o.query_scope,
        entityColumn: d.entity_column ?? undefined,
        columns: o.columns,
        filters: d.filters,
        charts: d.charts,
        cohorts: d.cohorts ?? [],
        page: 0,
      }));
      setDatasets(restored);
      setActive(Math.min(v.active ?? 0, Math.max(0, restored.length - 1)));
      showExploreTables();
    } catch (e) {
      setError(`Could not load view: ${(e as Error).message}`);
    } finally {
      setActivity("");
    }
  };

  const hashLoaded = useRef(false);
  useEffect(() => {
    if (!ready || hashLoaded.current) return;
    const m = window.location.hash.match(/view=([^:]+):([^:]+):(.+)/);
    if (m) {
      hashLoaded.current = true;
      loadView({ kind: m[1], id: m[2] }, decodeURIComponent(m[3]));
    }
  }, [ready]); // eslint-disable-line react-hooks/exhaustive-deps

  const doJoin = async (p: { baseId: string; steps: JoinStep[] }) => {
    setActivity("Joining…");
    setError("");
    try {
      let opened: OpenResult & { join: JoinStats };
      try {
        opened = await api.join(p.baseId, p.steps);
      } catch (e) {
        if (!(e instanceof ApiError) || e.status !== 404
            || e.code !== "DATASET_EXPIRED") throw e;

        const inputIds = [...new Set([
          p.baseId, ...p.steps.map((s) => s.right_id),
        ])];
        const inputs = new Map(datasets.map((d) => [d.id, d]));
        if (inputIds.some((id) => !inputs.get(id)?.sourceRef)) {
          throw new JoinRecoveryError(
            "The join inputs expired. Reopen the source or upload the data "
            + "again, then retry the join.");
        }

        const reopened = new Map<string, OpenResult>();
        const createdIds: string[] = [];
        try {
          for (const id of inputIds) {
            const sourceRef = inputs.get(id)!.sourceRef!;
            const result = await api.openSourceRef(sourceRef);
            reopened.set(id, result);
            createdIds.push(result.dataset_id);
          }
          const base = reopened.get(p.baseId)!;
          const retrySteps = p.steps.map((step) => ({
            ...step,
            right_id: reopened.get(step.right_id)!.dataset_id,
          }));
          opened = await api.join(base.dataset_id, retrySteps);
        } catch (retryError) {
          await Promise.allSettled(createdIds.map((id) => api.closeDataset(id)));
          const reason = retryError instanceof Error ? retryError.message : "unknown error";
          throw new JoinRecoveryError(
            `The join inputs expired. Automatic recovery failed: ${reason}. `
            + "Reopen the source or upload the data again, then retry.");
        }

        setDatasets((prev) => prev.map((dataset) => {
          const fresh = reopened.get(dataset.id);
          if (!fresh) return dataset;
          return {
            ...dataset,
            id: fresh.dataset_id,
            source: fresh.source,
            sourceRef: fresh.source_ref ?? dataset.sourceRef,
            queryScope: fresh.query_scope,
            columns: fresh.columns,
            result: undefined,
          };
        }));
      }

      openResult(opened, opened.source.split(" + ").map(
        (x) => x.split("/").pop()?.trim()).join(" + "), undefined, undefined,
      { forceNewTab: true });
      const { join } = opened;
      alerts.pushToast({
        title: join.truncated ? "Join capped" : "Joined",
        tone: join.truncated ? "fail" : "ok",
        body: (join.truncated
          ? `Showing ${join.rows.toLocaleString()} of ${join.total_rows.toLocaleString()} rows`
          : `${join.rows.toLocaleString()} rows from ${p.steps.length + 1} tables`)
          + (join.engine === "aurora" ? " (ran in Aurora)." : " (ran in memory).")
          + (join.capped_inputs?.length ? " Some inputs were capped — results may be incomplete." : ""),
      });
      setShowJoin(false);
    } catch (e) {
      const message = (e as Error).message;
      setError(e instanceof JoinRecoveryError
        ? message : `Join failed: ${message}`);
    } finally {
      setActivity("");
    }
  };

  const closeDataset = (index: number) => {
    const ds = datasets[index];
    api.closeDataset(ds.id).catch(() => undefined);
    setDatasets((prev) => prev.filter((_, i) => i !== index));
    setActive((a) => Math.max(0, a > index ? a - 1 : Math.min(a,
      datasets.length - 2)));
  };

  const updateDataset = useCallback((index: number,
                                     changes: Partial<Dataset>) => {
    setDatasets((prev) => prev.map((d, i) =>
      i === index ? { ...d, ...changes, ...(changes.filters || changes.charts
        ? { page: 0, ...changes } : {}) } : d));
  }, []);

  const activeDs = datasets[active];

  const TERMINAL = new Set(
    ["COMPLETED", "FAILED", "CANCELLED", "CANCELED", "DELETED"]);
  const dependentJob = (() => {
    const ref = activeDs?.sourceRef;
    if (!ref || ref.kind !== "s3" || !workflows) return null;

    const uuid = ref.uuid
      ?? sources.find((s) => s.id === ref.resource_id)?.uuid;
    if (!uuid) return null;
    return workflows.jobs.find((j) =>
      !TERMINAL.has((j.status || "").toUpperCase())
      && j.output_bucket_uuid === uuid
      && (!j.output_bucket_path
          || ref.table.includes(j.output_bucket_path)
          || j.output_bucket_path.includes(ref.table.split("/")[0]))) ?? null;
  })();

  useEffect(() => {
    if (!activeDs) return;
    let cancelled = false;
    const refreshNonce = activeDs.refreshNonce ?? 0;
    const forceRefresh = refreshNonce > (consumedRefreshNonce.current[activeDs.id] ?? 0);
    if (forceRefresh) consumedRefreshNonce.current[activeDs.id] = refreshNonce;
    api.query(activeDs.id, activeDs.filters, activeDs.charts, activeDs.page,
      activeDs.entityColumn, forceRefresh)
      .then((result) => {
        if (cancelled) return;
        setDatasets((prev) => prev.map((d) =>
          d.id === activeDs.id ? { ...d, result,
            ...(forceRefresh && result.columns
              ? { columns: result.columns } : {}),
            refreshing: false } : d));
      })
      .catch((e) => {
        if (cancelled) return;
        setDatasets((prev) => prev.map((d) => d.id === activeDs.id
          ? { ...d, refreshing: false } : d));
        setError(`Query failed: ${(e as Error).message}`);
      });
    return () => { cancelled = true; };
  }, [activeDs?.id, activeDs?.filters, activeDs?.charts, activeDs?.page,
      activeDs?.entityColumn, activeDs?.refreshNonce]);
  // eslint-disable-line react-hooks/exhaustive-deps

  const commands: Command[] = [
    ...(["explore", "workflows", "lineage", "settings"] as const).map((v) => ({
      id: `view:${v}`, group: "Go to",
      label: v[0].toUpperCase() + v.slice(1), run: () => setView(v),
    })),
    ...datasets.map((d, i) => ({
      id: `tab:${d.id}`, group: "Open tab", label: d.title,
      hint: `${d.result?.filtered?.toLocaleString() ?? "?"} rows`,
      run: () => { setActive(i); showExploreTables(); },
    })),
    ...sources.map((s) => ({
      id: `src:${s.kind}:${s.id}`, group: "Datasource",
      label: s.id, hint: s.kind.toUpperCase(),
      run: () => { setSourceKey(`${s.kind}:${s.id}`); setView("explore"); },
    })),
    ...(source ? tables.map((t) => ({
      id: `tbl:${t.name}`, group: `Open from ${source.id}`,
      label: t.name, hint: t.detail,
      run: () => openTableDirect(source, t.name),
    })) : []),
    { id: "act:upload", group: "Action", label: "Upload a CSV…",
      run: () => fileRef.current?.click() },
  ];

  return (
    <div className="app">
      <aside className="sidebar">
        {!ready ? (
          <div className="activity"><span className="pulse" />
            Connecting to workspace…</div>
        ) : (
          <div style={{ fontSize: 12.5, color: "var(--ink-muted)" }}>
            {sources.length
              ? `${sources.length} datasource(s)`
              : "Waiting for workspace datasources… CSV upload works now."}
          </div>
        )}

        <div className="section-label">Datasource</div>
        <select value={sourceKey}
                onChange={(e) => setSourceKey(e.target.value)}>
          <option value="" disabled>Choose…</option>
          {sources.map((s) => (
            <option key={`${s.kind}:${s.id}`} value={`${s.kind}:${s.id}`}>
              {s.label}
            </option>
          ))}
        </select>
        {source?.kind === "aurora" && <label className="field-label">
          Explore mode
          <select aria-label="Explore mode" value={exploreMode}
                  onChange={(e) => setExploreMode(e.target.value as "tables" | "omop")}>
            <option value="tables">Tables and views</option>
            <option value="omop">OMOP cohorts</option>
          </select>
        </label>}
        {exploreMode === "tables" && <>
          <div className="field-label">Table</div>
          <select aria-label="Table" value={table}
                  onChange={(e) => setTable(e.target.value)}>
            <option value="" disabled>Choose…</option>
            {tables.map((t) => (
              <option key={t.name} value={t.name} title={t.sql ?? undefined}>
                {t.name} ({t.detail})
              </option>
            ))}
          </select>
          <div style={{ marginTop: 10 }}>
            <button className="primary" onClick={loadTable}
                    disabled={!table || Boolean(activity)}>
              Load table
            </button>
          </div>
        </>}
        {source?.kind === "s3" && (
          <PublishCatalog source={source} onToast={alerts.pushToast}
                          onPublished={() => api.datasources()
                            .then((out) => setSources(out.sources))
                            .catch(() => undefined)} />
        )}

        <div className="section-label">Upload</div>
        <label className="upload-btn">
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.tsv,.txt"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) uploadCsv(f);
              e.target.value = "";
            }}
          />
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth="2">
            <path d="M12 16V4m0 0l-4 4m4-4l4 4" />
            <path d="M4 17v2a1 1 0 001 1h14a1 1 0 001-1v-2" />
          </svg>
          Upload CSV/TSV
        </label>

        {!showJoin && <>
        <div className="section-label">Filters</div>

        {activeDs ? (
          <FilterPanel
            columns={activeDs.columns}
            filters={activeDs.filters}
            onChange={(filters) => updateDataset(active, { filters })}
          />
        ) : (
          <div style={{ color: "var(--ink-muted)" }}>
            Load a table to see filters.
          </div>
        )}

        </>}
        <div className="section-label">Saved views</div>
        <SavedViews sources={sources} datasets={datasets} active={active}
                    onLoadView={loadView} />

        <VersionFooter />
      </aside>

      <div className="main">
        <div className="topbar">
          <BrandMark size={20} />
          <span className="brand">
            <span className="brand-verily">verily</span> Cohort Studio
          </span>
          <nav className="topnav">
            {(["explore", "workflows", "lineage", "settings"] as const)
              .map((v) => (
              <span key={v}
                    className={`topnav-link${view === v ? " active" : ""}`}
                    onClick={() => setView(v)}>
                {v[0].toUpperCase() + v.slice(1)}
                {v === "workflows" && (workflows?.running_count ?? 0) > 0 && (
                  <span className="nav-badge">{workflows!.running_count}</span>
                )}
              </span>
            ))}
          </nav>
          <div style={{ flex: 1 }} />
          <button className="cmdk-hint" onClick={() => setCmdOpen(true)}
                  title="Command palette">
            <span>⌘K</span>
          </button>
          {activity && (
            <div className="activity"><span className="pulse" />{activity}</div>
          )}
          {error && (
            <div style={{ color: "#c93a38", fontSize: 12.5 }}
                 onClick={() => setError("")}>
              {error} ✕
            </div>
          )}
        </div>
        <div className="content">
          <div hidden={view !== "explore" || exploreMode !== "omop"}>
            <OmopBuilder active={view === "explore" && exploreMode === "omop"}
                          source={source ?? null} onOpen={(opened, title) => {
              openResult(opened, title, undefined,
                { filters: [], charts: autoCharts(opened.columns) });
              setExploreMode("tables");
              setView("explore");
            }} />
          </div>
          {view === "explore" && exploreMode === "omop" ? null : view === "settings" ? (
            <SettingsView onPaletteChange={setPalette} />
          ) : view === "workflows" ? (
            <WorkflowsView isSubscribed={alerts.isSubscribed}
                           onToggleSubscribe={alerts.toggle} />
          ) : view === "lineage" ? (
            <LineageView />
          ) : datasets.length === 0 && !showJoin ? (
            <div className="empty">
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
                   stroke="#9095a0" strokeWidth="1.5">
                <rect x="3" y="3" width="7" height="9" rx="1.5" />
                <rect x="14" y="3" width="7" height="5" rx="1.5" />
                <rect x="14" y="12" width="7" height="9" rx="1.5" />
                <rect x="3" y="16" width="7" height="5" rx="1.5" />
              </svg>
              <div className="title">No data loaded</div>
              {sources.length > 0 && (
                <button className="primary" onClick={() => setShowJoin(true)}>
                  ⋈ Join tables
                </button>
              )}
            </div>
          ) : (
            <>
              <div className="tabs">
                {datasets.map((d, i) => (
                  <span key={d.id}
                        className={`tab${i === active ? " active" : ""}`}
                        onClick={() => { setActive(i); setShowJoin(false); showExploreTables(); }}>
                    {d.title}
                    <button className="quiet" onClick={(e) => {
                      e.stopPropagation(); closeDataset(i);
                    }}>✕</button>
                  </span>
                ))}
                {(datasets.length >= 2 || sources.length > 0) && (
                  <button className="tab-join"
                          onClick={() => setShowJoin((v) => !v)}>
                    ⋈ Join
                  </button>
                )}
              </div>
              {showJoin && (
                <JoinPanel datasets={datasets} sources={sources} busy={Boolean(activity)}
                           onSourceOpened={(opened, title, sourceRef) =>
                             openResult(opened, title, sourceRef, undefined,
                               { forceNewTab: true })}
                           onJoin={doJoin} onClose={() => setShowJoin(false)} />
              )}
              {dependentJob && !showJoin && (
                <div className="wf-dep-banner">
                  <span className="wf-pulse" />
                  This data shares the output bucket of workflow{" "}
                  <strong>{dependentJob.name}</strong>, which is{" "}
                  {dependentJob.status} — results may still be incomplete.
                  <span className="wf-dep-link"
                        onClick={() => setView("workflows")}>
                    View workflows
                  </span>
                </div>
              )}
              {activeDs && !showJoin && (
                <DatasetPane
                  dataset={activeDs}
                  palette={palette}
                  onUpdate={(changes) => updateDataset(active, changes)}
                />
              )}
            </>
          )}
        </div>
      </div>
      <Toasts toasts={alerts.toasts} onDismiss={alerts.dismissToast} />
      <CommandPalette open={cmdOpen} commands={commands}
                      onClose={() => setCmdOpen(false)} />
    </div>
  );
}
