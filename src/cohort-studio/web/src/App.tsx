import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, OpenResult, WorkflowList, viewSpecs } from "./api";
import { FilterPanel } from "./components/FilterPanel";
import { SavedViews } from "./components/SavedViews";
import { SourcePicker } from "./components/SourcePicker";
import { PublishCatalog } from "./components/PublishCatalog";
import { Toasts } from "./components/Toasts";
import { BrandMark } from "./components/BrandMark";
import { CommandPalette, Command } from "./components/CommandPalette";
import { DataJobs } from "./components/DataJobs";
import { Tutorial } from "./components/Tutorial";
import { DiscoveryBanner, discoverySettled } from "./components/DiscoveryBanner";
import type { DiscoveryStatus } from "./api";
import type { AgentDashboardAction, AgentWorkflowVerification } from "./api";
import { useWorkflowAlerts } from "./workflowAlerts";
import { api as apiClient } from "./api";
import type { ChartSpec, Dataset, JoinFilter, JoinStats, JoinStep, Source, SourceRef, TableInfo } from "./types";
import { tableStats } from "./format";

const SIDEBAR_KEY = "cohort-studio.sidebar-collapsed";
const DatasetPane = lazy(() => import("./components/DatasetPane").then((m) => ({ default: m.DatasetPane })));
const JoinPanel = lazy(() => import("./components/JoinPanel").then((m) => ({ default: m.JoinPanel })));
const JoinCanvas = lazy(() => import("./components/JoinCanvas").then((m) => ({ default: m.JoinCanvas })));
const StudioAgent = lazy(() => import("./components/StudioAgent").then((m) => ({ default: m.StudioAgent })));
const SettingsView = lazy(() => import("./components/SettingsView").then((m) => ({ default: m.SettingsView })));
const WorkflowsView = lazy(() => import("./components/WorkflowsView").then((m) => ({ default: m.WorkflowsView })));
const LineageView = lazy(() => import("./components/LineageView").then((m) => ({ default: m.LineageView })));
const AddSourceDialog = lazy(() => import("./components/AddSourceDialog").then((m) => ({ default: m.AddSourceDialog })));

const AUTO_CHART_LIMIT = 8;

class JoinRecoveryError extends Error {}

interface JoinEdit {
  originalDatasetId: string;
  originalTitle: string;
  baseId: string;
  steps: JoinStep[];
  allowLoaded: boolean;
  baseFilters?: JoinFilter[];
  inputs: Dataset[];
}

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

const QUERY_DEBOUNCE_MS = 250;

export default function App() {
  const [sources, setSources] = useState<Source[]>([]);
  const [ready, setReady] = useState(false);
  const [discovery, setDiscovery] = useState<DiscoveryStatus | undefined>();
  const [sourceKey, setSourceKey] = useState("");
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [table, setTable] = useState("");
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [workflowVerification, setWorkflowVerification] = useState<{
    result: AgentWorkflowVerification; datasetId: string; strata?: number;
  } | null>(null);
  const [renamingDatasetId, setRenamingDatasetId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [active, setActive] = useState(0);
  const [activity, setActivity] = useState("");
  const [listingTables, setListingTables] = useState("");   // datasource being listed
  const [openingTable, setOpeningTable] = useState<TableInfo | null>(null);
  // Opens and joins show progress in the Data operations card; keep `activity`
  // as the busy flag but don't repeat the text in the top bar.
  const [activityInCard, setActivityInCard] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState<
    "explore" | "join" | "agent" | "workflows" | "lineage" | "settings">("explore");
  // The visual join canvas stays mounted (hidden) after its first visit so a draft survives tab switches.
  const [canvasMounted, setCanvasMounted] = useState(false);
  useEffect(() => { if (view === "join") setCanvasMounted(true); }, [view]);
  const [canvasEdit, setCanvasEdit] = useState<{ nonce: number; title: string;
    ref: Extract<SourceRef, { kind: "join" }> } | null>(null);
  const [tutorialAssistantConfigured, setTutorialAssistantConfigured] = useState(false);
  const [palette, setPalette] = useState("verily");
  const [showJoin, setShowJoin] = useState(false);
  // The join builder stays mounted (hidden) while you visit other tabs, so a
  // draft or a running join is still there when you come back.
  const [joinMounted, setJoinMounted] = useState(false);
  const [joinRunning, setJoinRunning] = useState(false);
  // Bumped for each Edit join so a reopened editor remounts with fresh inputs.
  const [joinSession, setJoinSession] = useState(0);
  useEffect(() => { if (showJoin) setJoinMounted(true); }, [showJoin]);
  const [editingJoin, setEditingJoin] = useState<JoinEdit | null>(null);
  const [workflows, setWorkflows] = useState<WorkflowList | null>(null);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [addSourceOpen, setAddSourceOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const consumedRefreshNonce = useRef<Record<string, number>>({});
  const recoveredDatasetIds = useRef(new Set<string>());
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
    apiClient.config().then((c) => {
      setPalette(c.chart_palette);
      setTutorialAssistantConfigured(Boolean(c.llm?.providers?.[c.llm.provider]?.configured));
    })
      .catch(() => undefined);

    api.workflows().then(setWorkflows).catch(() => undefined);
  }, []);
  useEffect(() => {
    let cancelled = false;
    let idle: number | undefined;
    const timer = window.setTimeout(() => {
      const prefetch = () => {
        if (cancelled) return;
        void Promise.allSettled([
          import("./components/WorkflowsView"), import("./components/LineageView"),
          import("./components/StudioAgent"), import("./components/SettingsView"),
          import("./components/JoinPanel"),
          import("./components/DatasetPane"), import("./pdf"),
        ]);
      };
      if ("requestIdleCallback" in window) idle = window.requestIdleCallback(prefetch, { timeout: 1500 });
      else prefetch();
    }, 2500);
    return () => { cancelled = true; window.clearTimeout(timer); if (idle !== undefined) window.cancelIdleCallback(idle); };
  }, []);
  const pollRef = useRef<number>();
  const startPollingRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    const poll = async () => {
      try {
        const out = await api.datasources();
        setSources(out.sources);
        setDiscovery(out.discovery);
        if (out.ready) setReady(true);

        // A list served from the discovery snapshot keeps polling until the
        // background refresh settles, so the fresh list (or a failure) shows;
        // a lasting failure polls slowly (the server retries on its own).
        if (out.ready && out.sources.length > 0 && !out.catalogs_pending) {
          window.clearInterval(pollRef.current);
          if (!discoverySettled(out.discovery)) {
            const slow = out.discovery?.status === "stale" || out.discovery?.status === "failed";
            pollRef.current = window.setInterval(poll, slow ? 15000 : 3000);
          }
        }
      } catch {  }
    };
    startPollingRef.current = () => {
      window.clearInterval(pollRef.current);
      void poll();
      pollRef.current = window.setInterval(poll, 3000);
    };
    startPollingRef.current();
    return () => window.clearInterval(pollRef.current);
  }, []);
  const retryDiscovery = () => api.refreshDatasources()
    .then((out) => setDiscovery(out.discovery))
    .catch((e) => alerts.pushToast({ title: "Datasource refresh did not start",
                                     body: e instanceof Error ? e.message : String(e), tone: "fail" }))
    .finally(() => startPollingRef.current());

  const source = sources.find((s) => `${s.kind}:${s.id}` === sourceKey);
  const refreshTutorialAssistantStatus = () => {
    void apiClient.config().then((config) => setTutorialAssistantConfigured(
      Boolean(config.llm?.providers?.[config.llm.provider]?.configured))).catch(() => undefined);
  };
  const showExploreTables = () => {
    setView("explore");
  };

  // Bumped by "Refresh tables" to list again, bypassing the server's listing cache.
  const [tablesRefresh, setTablesRefresh] = useState(0);
  // Folding the Data sources panel gives dashboards the full width; remembered per browser.
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem(SIDEBAR_KEY) === "1"; } catch { return false; }
  });
  const toggleSidebar = (collapsed: boolean) => {
    setSidebarCollapsed(collapsed);
    try { localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0"); } catch { /* private mode */ }
  };
  useEffect(() => {
    if (!source) return;
    setTables([]);
    setTable("");
    // Shown next to the Table picker; a newer datasource choice wins.
    let current = true;
    setListingTables(source.id);
    api.tables(source.kind, source.id, tablesRefresh > 0)
      .then((t) => {
        if (!current) return;
        setTables(t);
        if (!t.length) setError(`No tables or data files in ${source.id}.`);
      })
      .catch((e) => { if (current) setError(`Could not list tables: ${e.message}`); })
      .finally(() => { if (current) setListingTables(""); });
    return () => { current = false; };
  }, [sourceKey, tablesRefresh]); // eslint-disable-line react-hooks/exhaustive-deps

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
      sourceInfo: opened.source_info,
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

  const closeEditInputs = (edit: JoinEdit) =>
    Promise.allSettled(edit.inputs.map((dataset) => api.closeDataset(dataset.id)));

  const closeJoinPanel = () => {
    if (editingJoin) void closeEditInputs(editingJoin);
    setEditingJoin(null);
    setShowJoin(false);
    setJoinMounted(false);
  };

  const editJoin = async (datasetId: string) => {
    const original = datasets.find((dataset) => dataset.id === datasetId);
    const ref = original?.sourceRef;
    if (!original || ref?.kind !== "join") return;
    if (joinRunning) {
      setError("A join is still running. Wait for it to finish or cancel it before editing another join.");
      return;
    }
    if (editingJoin) {
      // Replace the previous (possibly hidden) edit session instead of leaking its inputs.
      await closeEditInputs(editingJoin);
      setEditingJoin(null);
      setJoinMounted(false);
    }
    setActivity("Restoring join inputs…");
    setError("");
    const inputIds = new Map<string, string>();
    datasets.forEach((dataset) => {
      if (dataset.sourceRef) inputIds.set(JSON.stringify(dataset.sourceRef), dataset.id);
    });
    const openedInputs: Dataset[] = [];
    const openInput = async (sourceRef: SourceRef): Promise<string> => {
      const key = JSON.stringify(sourceRef);
      const existing = inputIds.get(key);
      if (existing) return existing;
      const opened = await api.openSourceRef(sourceRef);
      const title = sourceRef.kind === "join" ? "Joined input"
        : sourceRef.kind === "derived" ? sourceRef.spec.name
          : sourceRef.kind === "group_summary" ? `Group summary (${sourceRef.spec.group_by.join(", ")})`
          : sourceRef.kind === "omop_cohort" ? sourceRef.name || "OMOP cohort"
          : sourceRef.kind === "sql" ? sourceRef.name || "SQL result"
          : sourceRef.kind === "materialized" ? "Saved join"
            : sourceRef.table.split("/").pop() ?? sourceRef.table;
      const input: Dataset = {
        id: opened.dataset_id, title, source: opened.source,
        sourceRef: opened.source_ref ?? sourceRef, queryScope: opened.query_scope,
        columns: opened.columns, filters: [], charts: autoCharts(opened.columns),
        cohorts: [], page: 0,
      };
      openedInputs.push(input);
      inputIds.set(key, input.id);
      return input.id;
    };
    try {
      const baseId = await openInput(ref.base);
      const steps: JoinStep[] = [];
      for (const step of ref.steps)
        steps.push({ ...step, right_id: await openInput(step.source) });
      setEditingJoin({ originalDatasetId: original.id, originalTitle: original.title,
        baseId, steps, allowLoaded: ref.allow_loaded ?? false,
        baseFilters: ref.base_filters, inputs: openedInputs });
      setJoinSession((n) => n + 1);
      setShowJoin(true);
    } catch (error) {
      await Promise.allSettled(openedInputs.map((dataset) => api.closeDataset(dataset.id)));
      setError(`Could not edit join: ${(error as Error).message}. The existing result is unchanged.`);
    } finally {
      setActivity("");
    }
  };

  const openTableDirect = async (src: Source, tbl: string) => {
    setActivity(`Loading ${tbl}…`);
    setActivityInCard(true);
    setError("");
    const info = tables.find((t) => t.name === tbl);
    setOpeningTable(info ?? null);
    try {
      const opened = (src.kind === "aurora" || src.kind === "postgres" || src.kind === "athena") && info?.schema && info?.table
        ? await api.openSourceRef({ kind: src.kind, resource_id: src.id,
            table: info.table, schema: info.schema })
        : await api.openDataset(src.kind, src.id, tbl);
      openResult(opened, tbl.split("/").pop() ?? tbl,
        { kind: src.kind, resource_id: src.id, table: tbl, uuid: src.uuid });
      setView("explore");
    } catch (e) {
      setError(`Load failed: ${(e as Error).message}`);
    } finally {
      setActivity("");
      setActivityInCard(false);
      setOpeningTable(null);
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
      await restoreSpecs(v.datasets ?? [], v.active ?? 0);
    } catch (e) {
      setError(`Could not load view: ${(e as Error).message}`);
    } finally {
      setActivity("");
    }
  };

  type ViewSpec = Awaited<ReturnType<typeof api.getView>>["datasets"][number];
  const restoreSpecs = async (specs: ViewSpec[], activeIndex: number) => {
    {
      // The server runs at most two data jobs per session, so open two at a
      // time; keep the tabs that open even if some fail.
      const results: ({ o: OpenResult; d: ViewSpec } | { error: string; d: ViewSpec })[] = new Array(specs.length);
      let next = 0;
      const worker = async () => {
        while (next < specs.length) {
          const index = next++;
          const d = specs[index];
          try {
            results[index] = { o: await api.openSourceRef(d.source), d };
          } catch (e) {
            results[index] = { error: (e as Error).message, d };
          }
        }
      };
      await Promise.all([worker(), worker()]);
      const failed = results.filter((r): r is { error: string; d: ViewSpec } => "error" in r);
      const opened = results.filter((r): r is { o: OpenResult; d: ViewSpec } => "o" in r);
      if (!opened.length && failed.length) throw new Error(failed[0].error);
      if (failed.length) {
        setError(`${failed.length} of ${specs.length} tab(s) could not be reopened: `
          + failed.map((f) => `${f.d.title || "untitled"} (${f.error})`).join("; "));
      }
      const activeSpec = specs[Math.min(activeIndex, specs.length - 1)];
      activeIndex = Math.max(0, opened.findIndex((r) => r.d === activeSpec));
      const restored: Dataset[] = opened.map(({ o, d }) => ({
        id: o.dataset_id,
        title: d.title || (d.source.kind === "join" ? "Joined dataset"
          : d.source.kind === "derived" ? d.source.spec.name
            : d.source.kind === "group_summary" ? `Group summary (${d.source.spec.group_by.join(", ")})`
            : d.source.kind === "omop_cohort" ? d.source.name || "OMOP cohort"
            : d.source.kind === "sql" ? d.source.name || "SQL result"
            : d.source.kind === "materialized" ? "Saved join"
              : d.source.table.split("/").pop()) || "view",
        source: o.source,
        sourceRef: o.source_ref ?? d.source,
        sourceInfo: o.source_info,
        queryScope: o.query_scope,
        entityColumn: d.entity_column ?? undefined,
        columns: o.columns,
        filters: d.filters,
        charts: d.charts,
        cohorts: d.cohorts ?? [],
        filterAskHistory: d.filter_ask_history ?? [],
        groupSummary: d.group_summary ?? undefined,
        sort: d.sort ?? undefined,
        page: 0,
      }));
      setDatasets(restored);
      setActive(Math.min(activeIndex, Math.max(0, restored.length - 1)));
      showExploreTables();
    }
  };

  // Session restore: autosave open tabs (as recipes) to this browser, and
  // offer to reopen them after a reload or app restart.
  const sessionKey = `studio-session-v1:${window.location.pathname}`;
  const [savedSession, setSavedSession] = useState<{ savedAt: string; active: number;
    datasets: ViewSpec[]; skipped: number } | null>(() => {
    try { return JSON.parse(localStorage.getItem(sessionKey) || "null"); } catch { return null; }
  });
  const hadDatasets = useRef(false);
  useEffect(() => {
    const restorable = datasets.filter((d) => d.sourceRef);
    if (datasets.length) hadDatasets.current = true;
    const timer = setTimeout(() => {
      try {
        if (restorable.length) {
          // Index of the active tab within the restorable list (uploads are dropped).
          const activeInSaved = Math.max(0, restorable.indexOf(datasets[active]));
          localStorage.setItem(sessionKey, JSON.stringify({
            savedAt: new Date().toISOString(), active: activeInSaved,
            datasets: viewSpecs(restorable), skipped: datasets.length - restorable.length }));
        } else if (hadDatasets.current) {
          // Every restorable tab was closed (only uploads, or nothing, remain).
          localStorage.removeItem(sessionKey);
        }
      } catch { /* storage may be full or disabled */ }
    }, 800);
    return () => clearTimeout(timer);
  }, [datasets, active]); // eslint-disable-line react-hooks/exhaustive-deps
  const restoreSession = async () => {
    if (!savedSession) return;
    const session = savedSession;
    setSavedSession(null);
    setActivity(`Restoring ${session.datasets.length} tab(s)…`);
    setError("");
    try {
      await restoreSpecs(session.datasets, session.active);
    } catch (e) {
      setError(`Could not restore the last session: ${(e as Error).message}`);
    } finally {
      setActivity("");
    }
  };
  const dismissSession = () => {
    setSavedSession(null);
    try { localStorage.removeItem(sessionKey); } catch { /* ignore */ }
  };

  const hashLoaded = useRef(false);
  useEffect(() => {
    if (!ready || hashLoaded.current) return;
    const m = window.location.hash.match(/view=([^:]+):([^:]+):(.+)/);
    if (m) {
      hashLoaded.current = true;
      loadView({ kind: m[1], id: decodeURIComponent(m[2]) }, decodeURIComponent(m[3]));
    }
  }, [ready]); // eslint-disable-line react-hooks/exhaustive-deps

  const doJoin = async (p: { baseId: string; steps: JoinStep[]; allowLoaded?: boolean;
                              baseFilters?: JoinFilter[];
                              // From the visual join canvas: its private inputs and the tab title.
                              fromCanvas?: boolean; extraInputs?: Dataset[]; title?: string }) => {
    setActivity("Joining…");
    setActivityInCard(true);
    setJoinRunning(true);
    setError("");
    try {
      let opened: OpenResult & { join: JoinStats };
      try {
        opened = await api.join(p.baseId, p.steps, p.allowLoaded, p.baseFilters);
      } catch (e) {
        if (!(e instanceof ApiError) || e.status !== 404
            || e.code !== "DATASET_EXPIRED") throw e;

        const inputIds = [...new Set([
          p.baseId, ...p.steps.map((s) => s.right_id),
        ])];
        const inputs = new Map([...datasets, ...(p.fromCanvas ? p.extraInputs ?? [] : editingJoin?.inputs ?? [])]
          .map((d) => [d.id, d]));
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
          opened = await api.join(base.dataset_id, retrySteps, p.allowLoaded, p.baseFilters);
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
            sourceInfo: fresh.source_info,
            queryScope: fresh.query_scope,
            columns: fresh.columns,
            result: undefined,
          };
        }));
      }

      openResult(opened, p.title || opened.source.split(" + ").map(
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
          + (join.capped_inputs?.length ? " Some inputs were capped — results may be incomplete." : "")
          + (join.large_growth ? ` Rows grew ${join.growth_total}× over the base — check for fan-out.` : ""),
      });
      if (!p.fromCanvas) {
        if (editingJoin) {
          await closeEditInputs(editingJoin);
          setEditingJoin(null);
        }
        setShowJoin(false);
        setJoinMounted(false);
      }
    } catch (e) {
      const message = (e as Error).message;
      setError(e instanceof JoinRecoveryError
        ? message : `Join failed: ${message}`);
    } finally {
      setActivity("");
      setActivityInCard(false);
      setJoinRunning(false);
    }
  };

  const closeDataset = (index: number) => {
    const ds = datasets[index];
    if (editingJoin && (ds.id === editingJoin.originalDatasetId
        || ds.id === editingJoin.baseId
        || editingJoin.steps.some((step) => step.right_id === ds.id))) closeJoinPanel();
    api.closeDataset(ds.id).catch(() => undefined);
    setDatasets((prev) => prev.filter((_, i) => i !== index));
    setActive((a) => Math.max(0, a > index ? a - 1 : Math.min(a,
      datasets.length - 2)));
  };

  const updateDataset = useCallback((datasetId: string,
                                     changes: Partial<Dataset>) => {
    setDatasets((prev) => prev.map((d) =>
      d.id === datasetId ? { ...d, ...changes, ...(changes.filters || changes.charts
        ? { page: 0, ...changes } : {}) } : d));
  }, []);

  const saveDatasetName = (dataset: Dataset) => {
    const title = renameDraft.trim().slice(0, 128);
    if (!title) return;
    setDatasets((previous) => previous.map((item) => item.id !== dataset.id ? item : {
      ...item, title,
      ...(item.sourceRef?.kind === "sql"
        ? { sourceRef: { ...item.sourceRef, name: title } } : {}),
    }));
    setRenamingDatasetId(null);
    setRenameDraft("");
  };

  const activeDs = datasets[active];
  const chartQuerySignature = JSON.stringify(activeDs?.charts.map(({ kind, x, y }) => ({ kind, x, y })) ?? []);
  const joinBuilderDatasets = editingJoin ? [...datasets, ...editingJoin.inputs] : datasets;

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
    setDatasets((prev) => prev.map((dataset) => dataset.id === activeDs.id
      ? { ...dataset, queryLoading: true, queryError: undefined } : dataset));
    // Debounce filter/sort/page bursts into one dashboard query, and abort the
    // previous request when inputs change. First load and Refresh run at once.
    const controller = new AbortController();
    const delay = forceRefresh || !activeDs.result ? 0 : QUERY_DEBOUNCE_MS;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const started = delay === 0
      ? Promise.resolve()          // send now, in the same tick as before
      : new Promise<void>((resolve) => { timer = setTimeout(resolve, delay); });
    const send = () => api.query(activeDs.id, activeDs.filters, activeDs.charts, activeDs.page,
      activeDs.entityColumn, forceRefresh, activeDs.sort, controller.signal);
    const request = delay === 0 ? send() : started.then(send);
    request
      .then((result) => {
        if (cancelled) return;
        recoveredDatasetIds.current.delete(activeDs.id);
        setDatasets((prev) => prev.map((d) =>
          d.id === activeDs.id ? { ...d, result,
            ...(forceRefresh && result.columns
              ? { columns: result.columns } : {}),
            refreshing: false, queryLoading: false, queryError: undefined } : d));
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404 && e.code === "DATASET_EXPIRED") {
          const expiredId = activeDs.id;
          if (recoveredDatasetIds.current.has(expiredId)) {
            setDatasets((prev) => prev.map((d) => d.id === expiredId
              ? { ...d, result: undefined, refreshing: false, queryLoading: false,
                  queryError: "This dataset expired again after reopening. Reopen the source or upload the data again." }
              : d));
            return;
          }
          if (!activeDs.sourceRef) {
            setDatasets((prev) => prev.map((d) => d.id === expiredId
              ? { ...d, result: undefined, refreshing: false, queryLoading: false,
                  queryError: "This dataset expired and has no saved source recipe. Reopen the datasource or upload the file again." }
              : d));
            return;
          }
          setDatasets((prev) => prev.map((d) => d.id === expiredId
            ? { ...d, result: undefined, refreshing: false, queryLoading: true,
                queryError: undefined }
            : d));
          api.openSourceRef(activeDs.sourceRef).then((opened) => {
            if (cancelled) {
              api.closeDataset(opened.dataset_id).catch(() => undefined);
              return;
            }
            recoveredDatasetIds.current.add(opened.dataset_id);
            setDatasets((prev) => prev.map((d) => d.id === expiredId
              ? { ...d, id: opened.dataset_id, source: opened.source,
                  sourceRef: opened.source_ref ?? activeDs.sourceRef,
                  sourceInfo: opened.source_info,
                  queryScope: opened.query_scope, columns: opened.columns,
                  result: undefined, refreshing: false, queryLoading: true,
                  queryError: undefined }
              : d));
          }).catch((reopenError) => {
            if (cancelled) return;
            const reason = reopenError instanceof Error
              ? reopenError.message : "source unavailable";
            setDatasets((prev) => prev.map((d) => d.id === expiredId
              ? { ...d, result: undefined, refreshing: false, queryLoading: false,
                  queryError: `Could not reopen the saved source: ${reason}. Check datasource access, then reopen it or upload the file again.` }
              : d));
          });
          return;
        }
        const detail = e instanceof ApiError
          ? `${e.status}: ${e.message}`
          : e instanceof Error ? e.message : "Check the connection and try again.";
        setDatasets((prev) => prev.map((d) => d.id === activeDs.id
          ? { ...d, refreshing: false, queryLoading: false,
              queryError: `Query failed: ${detail}` } : d));
      });
    return () => { cancelled = true; if (timer) clearTimeout(timer); controller.abort(); };
  }, [activeDs?.id, activeDs?.filters, chartQuerySignature, activeDs?.page,
      activeDs?.entityColumn, activeDs?.refreshNonce, activeDs?.sort]);
  // eslint-disable-line react-hooks/exhaustive-deps

  const commands: Command[] = [
    ...(["explore", "workflows", "lineage", "settings"] as const).map((v) => ({
      id: `view:${v}`, group: "Go to",
      label: v[0].toUpperCase() + v.slice(1), run: () => {
        if (view === "settings" && v !== "settings") refreshTutorialAssistantStatus();
        setView(v);
      },
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
      label: t.name, hint: [t.detail, tableStats(t)].filter(Boolean).join(" · "),
      run: () => openTableDirect(source, t.name),
    })) : []),
    { id: "act:upload", group: "Action", label: "Upload a CSV, TSV or Parquet file…",
      run: () => fileRef.current?.click() },
  ];

  return (
    <div className={`app${view !== "explore" ? " app-no-sidebar" : ""}${sidebarCollapsed ? " sidebar-is-collapsed" : ""}`}>
      {sidebarCollapsed && (
        <aside className="sidebar-rail" aria-label="Data sources (collapsed)">
          <button type="button" className="quiet sidebar-toggle" aria-label="Expand data sources"
                  title="Show data sources" aria-expanded={false}
                  onClick={() => toggleSidebar(false)}>»</button>
          <span className="sidebar-rail-label" aria-hidden="true">Data sources</span>
        </aside>
      )}
      <aside className="sidebar" hidden={sidebarCollapsed} id="data-sources-panel">
        <h2 className="sidebar-heading">
          <span>Data sources</span>
          <button type="button" className="quiet sidebar-toggle" aria-label="Collapse data sources"
                  title="Hide data sources" aria-expanded={true} aria-controls="data-sources-panel"
                  onClick={() => toggleSidebar(true)}>«</button>
        </h2>
        {!ready ? (
          <div className="activity"><span className="pulse" />
            Connecting to workspace…</div>
        ) : (
          <div style={{ fontSize: 12.5, color: "var(--ink-muted)" }}>
            {sources.length
              ? `${sources.length} available`
              : "Waiting for workspace datasources… File upload works now."}
          </div>
        )}
        <DiscoveryBanner discovery={discovery} onRetry={retryDiscovery} />

        {datasets.length === 0 && sources.length > 0 && <button className="quiet"
          data-tutorial-target="join-button" onClick={() => setShowJoin(true)}>Join tables</button>}
        <SourcePicker sources={sources} tables={tables} sourceKey={sourceKey} table={table}
          loading={!ready || Boolean(activity) || Boolean(listingTables)} busy={Boolean(activity)}
          listing={listingTables}
          onRefreshTables={() => setTablesRefresh((n) => n + 1)}
          onSourceKeyChange={setSourceKey} onTableChange={setTable} onLoadTable={loadTable} />
        <button className="quiet" onClick={() => setAddSourceOpen(true)}>+ Add data source</button>
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
            accept=".csv,.tsv,.txt,.gz,.parquet"
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
          Upload CSV, TSV or Parquet
        </label>

        {!showJoin && <>
        <div className="section-label">Filters</div>

        {activeDs ? (
          <FilterPanel
            columns={activeDs.columns}
            filters={activeDs.filters}
            onChange={(filters) => updateDataset(activeDs.id, { filters })}
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
            {(["explore", "join", "agent", "workflows", "lineage", "settings"] as const)
              .map((v) => (
              <span key={v} data-tutorial-target={`nav-${v}`}
                    className={`topnav-link${view === v ? " active" : ""}`}
                    onClick={() => {
                      if (view === "settings" && v !== "settings") refreshTutorialAssistantStatus();
                      if (v !== "explore") closeJoinPanel();
                      setView(v);
                    }}>
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
          <Tutorial progress={{
            sourceChosen: Boolean(sourceKey), dataLoaded: datasets.length > 0,
            hasSources: sources.length > 0, joinPanelOpen: showJoin,
            joinCreated: datasets.some((dataset) => dataset.sourceRef?.kind === "join"),
            view, hasDataset: Boolean(activeDs),
            chatHistoryAvailable: datasets.some((dataset) => Boolean(dataset.chatSessionId)),
            assistantConfigured: tutorialAssistantConfigured,
          }} />
          {activity && !activityInCard && (
            <div className="activity"><span className="pulse" />{activity}</div>
          )}
          {error && (
            <div style={{ color: "#c93a38", fontSize: 12.5 }}
                 onClick={() => setError("")}>
              {error} ✕
            </div>
          )}
        </div>
        <DataJobs expected={openingTable} showDone={view === "explore"}
                  onOpen={result => openResult(result, result.source, result.source_ref)} />
        <div className="content">
          {view === "explore" && workflowVerification?.result.verified
            && datasets[active]?.id === workflowVerification.datasetId && (
            <aside className="studio-agent-verified" role="status">
              <div><strong>Verified workflow results</strong>
                <span>Run {workflowVerification.result.run_id}</span>
                {workflowVerification.result.rows !== undefined && <span>{workflowVerification.result.rows.toLocaleString()} people</span>}
                {workflowVerification.strata !== undefined && <span>{workflowVerification.strata.toLocaleString()} strata</span>}
                {workflowVerification.result.integrity && <span>Integrity: {String(workflowVerification.result.integrity)
                  .replace(/[_-]+/g, " ")}</span>}
              </div>
              <button type="button" className="quiet" aria-label="Dismiss verification details"
                onClick={() => setWorkflowVerification(null)}>Dismiss</button>
            </aside>
          )}
          <Suspense fallback={<div role="status">Loading…</div>}>
          {canvasMounted && (
            <div className="join-canvas-host" hidden={view !== "join"}>
              <JoinCanvas datasets={datasets} sources={sources} busy={Boolean(activity)} edit={canvasEdit}
                          onJoin={doJoin}
                          onOpenResult={(opened, title, sourceRef) =>
                            openResult(opened, title, sourceRef, undefined, { forceNewTab: true })}
                          onAddSource={() => setAddSourceOpen(true)}
                          onClose={() => setView("explore")} />
            </div>
          )}
          {view === "join" ? null : view === "agent" ? (
            <StudioAgent onOpenSettings={() => setView("settings")} onOpenDashboard={(action: AgentDashboardAction & { update?: boolean }, verification?: AgentWorkflowVerification) => {
              const existing = action.update
                ? datasets.findIndex((d) => d.id === action.dataset.dataset_id) : -1;
              if (existing >= 0) {
                // update_dashboard: apply the Agent's filter/chart set to the open tab.
                setDatasets((prev) => prev.map((d, i) => i === existing
                  ? { ...d, filters: action.filters, charts: action.charts, page: 0 } : d));
                setActive(existing);
                setView("explore");
                return;
              }
              setWorkflowVerification(verification?.verified
                ? { result: verification, datasetId: action.dataset.dataset_id,
                    strata: action.dataset.rows } : null);
              openResult(action.dataset, action.title, action.dataset.source_ref,
                { filters: action.filters, charts: action.charts },
                { forceNewTab: true });
              setView("explore");
            }} />
          ) : view === "settings" ? (
            <SettingsView onPaletteChange={setPalette} />
          ) : view === "workflows" ? (
            <WorkflowsView data={workflows} onData={setWorkflows} isSubscribed={alerts.isSubscribed}
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
              {savedSession && savedSession.datasets.length > 0 && (
                <div className="session-restore" role="status">
                  <span>Your last session had {savedSession.datasets.length} tab
                    {savedSession.datasets.length === 1 ? "" : "s"}
                    {savedSession.skipped ? ` (${savedSession.skipped} uploaded file${savedSession.skipped === 1 ? "" : "s"} can't be reopened)` : ""}
                    , saved {new Date(savedSession.savedAt).toLocaleString()}.</span>
                  <button className="primary" onClick={() => void restoreSession()}>Restore last session</button>
                  <button className="quiet" onClick={dismissSession}>Dismiss</button>
                </div>
              )}
              {sources.length > 0 && (
                  <button className="primary" data-tutorial-target="load-data"
                    onClick={() => {
                      toggleSidebar(false);
                      window.setTimeout(() => {
                        const picker = document.querySelector<HTMLSelectElement>("[aria-label='Source type']");
                        picker?.scrollIntoView({ block: "nearest" });
                        picker?.focus();
                      });
                    }}>
                  Load data
                </button>
              )}
            </div>
          ) : (
            <>
              <div className="tabs">
                {datasets.map((d, i) => (
                  <span key={d.id}
                        className={`tab${i === active ? " active" : ""}`}
                        onClick={() => { setShowJoin(false); setActive(i); showExploreTables(); }}>
                    {renamingDatasetId === d.id ? <form className="tab-rename"
                      onClick={(event) => event.stopPropagation()}
                      onSubmit={(event) => { event.preventDefault(); saveDatasetName(d); }}>
                      <input type="text" autoFocus aria-label={`Name for ${d.title}`} maxLength={128}
                        value={renameDraft} onChange={(event) => setRenameDraft(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Escape") {
                            event.preventDefault(); setRenamingDatasetId(null); setRenameDraft("");
                          }
                        }} />
                      <button type="submit" className="quiet" disabled={!renameDraft.trim()}
                        aria-label="Save tab name">Save</button>
                      <button type="button" className="quiet" aria-label="Cancel rename"
                        onClick={() => { setRenamingDatasetId(null); setRenameDraft(""); }}>Cancel</button>
                    </form> : <>
                      <span>{d.title}</span>
                      <button type="button" className="quiet"
                        aria-label={`Rename ${d.title}`}
                        onClick={(event) => {
                          event.stopPropagation(); setActive(i); setRenamingDatasetId(d.id);
                          setRenameDraft(d.title);
                        }}>Rename</button>
                    </>}
                    <button className="quiet" onClick={(e) => {
                      e.stopPropagation(); closeDataset(i);
                    }}>✕</button>
                  </span>
                ))}
                {(datasets.length >= 2 || sources.length > 0) && (
                  <button className={`tab-join${showJoin ? " active" : ""}${joinRunning ? " running" : ""}`}
                          data-tutorial-target="join-button"
                          aria-label={joinRunning ? "Join (running)" : undefined}
                          onClick={() => setShowJoin(!showJoin)}>
                    {joinRunning ? <><span className="spinner small" aria-hidden="true" />Joining…</> : "⋈ Join"}
                  </button>
                )}
              </div>
              {(showJoin || joinMounted) && <div hidden={!showJoin}>
                <JoinPanel key={editingJoin ? `${editingJoin.originalDatasetId}:${joinSession}` : "new"}
                           datasets={joinBuilderDatasets} sources={sources} busy={Boolean(activity)}
                           initialPlan={editingJoin ? {
                             title: editingJoin.originalTitle, baseId: editingJoin.baseId,
                             steps: editingJoin.steps, allowLoaded: editingJoin.allowLoaded,
                             baseFilters: editingJoin.baseFilters,
                           } : undefined}
                           onSourceOpened={(opened, title, sourceRef) =>
                             openResult(opened, title, sourceRef, undefined,
                               { forceNewTab: true })}
                           onJoin={doJoin} onClose={closeJoinPanel}
                           onOpenCanvas={() => { closeJoinPanel(); setView("join"); }} />
              </div>}
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
                  onUpdate={(changes) => updateDataset(activeDs.id, changes)}
                  onEditJoin={editJoin}
                  onEditJoinCanvas={(datasetId) => {
                    const original = datasets.find((dataset) => dataset.id === datasetId);
                    if (original?.sourceRef?.kind !== "join") return;
                    setCanvasEdit((prev) => ({ nonce: (prev?.nonce ?? 0) + 1, title: original.title,
                                                ref: original.sourceRef as Extract<SourceRef, { kind: "join" }> }));
                    setView("join");
                  }}
                  onOpenTable={(opened, title) => openResult(opened, title, undefined, undefined, { forceNewTab: true })}
                />
              )}
            </>
          )}
          </Suspense>
        </div>
      </div>
      <Toasts toasts={alerts.toasts} onDismiss={alerts.dismissToast} />
      {addSourceOpen && <Suspense fallback={<div role="status">Loading…</div>}><AddSourceDialog onClose={() => setAddSourceOpen(false)}
        onAdded={({ kind, id }) => {
          setAddSourceOpen(false);
          api.datasources().then((out) => {
            setSources(out.sources);
            const created = out.sources.find((item) => item.kind === kind && item.id === id);
            if (created) {
              setSourceKey(`${created.kind}:${created.id}`);
              setView("explore");
            }
          }).catch((e) => setError(`Source was added, but the list could not refresh: ${e.message}`));
        }} /></Suspense>}
      <CommandPalette open={cmdOpen} commands={commands}
                      onClose={() => setCmdOpen(false)} />
    </div>
  );
}
