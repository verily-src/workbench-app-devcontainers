import { useCallback, useEffect, useRef, useState } from "react";
import { api, OpenResult } from "./api";
import { DatasetPane } from "./components/DatasetPane";
import { FilterPanel } from "./components/FilterPanel";
import { LineageView } from "./components/LineageView";
import { SettingsView } from "./components/SettingsView";
import type { ChartSpec, Dataset, Source, TableInfo } from "./types";

const AUTO_CHART_LIMIT = 8;

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
      await api.adminUpdate();
      // poll until the server restarts on new code, then reload the page
      const before = sha;
      for (let i = 0; i < 60; i++) {
        await new Promise((r) => setTimeout(r, 5000));
        try {
          const v = await api.version();
          if (v.sha !== before) { window.location.reload(); return; }
        } catch { /* server restarting */ }
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
  const [view, setView] = useState<"explore" | "lineage" | "settings">("explore");
  const pollRef = useRef<number>();

  // ---- datasource discovery (poll until the wb resource cache warms) ----
  useEffect(() => {
    const poll = async () => {
      try {
        const out = await api.datasources();
        setSources(out.sources);
        if (out.ready) setReady(true);
        // keep polling while empty: on Workbench VMs the wb CLI often
        // is not logged in yet when the app starts (backend retries too)
        if (out.ready && out.sources.length > 0) {
          window.clearInterval(pollRef.current);
        }
      } catch { /* backend still starting */ }
    };
    poll();
    pollRef.current = window.setInterval(poll, 3000);
    return () => window.clearInterval(pollRef.current);
  }, []);

  const source = sources.find((s) => `${s.kind}:${s.id}` === sourceKey);

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

  // ------------------------------------------------- dataset lifecycle ----
  const openResult = (opened: OpenResult, title: string) => {
    const existing = datasets.findIndex((d) => d.source === opened.source);
    if (existing >= 0) {
      setActive(existing);
      return;
    }
    const ds: Dataset = {
      id: opened.dataset_id,
      title,
      source: opened.source,
      columns: opened.columns,
      filters: [],
      charts: autoCharts(opened.columns),
      page: 0,
    };
    setDatasets((prev) => [...prev, ds]);
    setActive(datasets.length);
  };

  const loadTable = async () => {
    if (!source || !table) return;
    setActivity(`Loading ${table}…`);
    setError("");
    try {
      const opened = await api.openDataset(source.kind, source.id, table);
      openResult(opened, table.split("/").pop() ?? table);
    } catch (e) {
      setError(`Load failed: ${(e as Error).message}`);
    } finally {
      setActivity("");
    }
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

  // ---------------- one round trip per state change, per dataset ----------
  const activeDs = datasets[active];
  useEffect(() => {
    if (!activeDs) return;
    let cancelled = false;
    api.query(activeDs.id, activeDs.filters, activeDs.charts, activeDs.page)
      .then((result) => {
        if (cancelled) return;
        setDatasets((prev) => prev.map((d) =>
          d.id === activeDs.id ? { ...d, result } : d));
      })
      .catch((e) => setError(`Query failed: ${(e as Error).message}`));
    return () => { cancelled = true; };
  }, [activeDs?.id, activeDs?.filters, activeDs?.charts, activeDs?.page]);
  // eslint-disable-line react-hooks/exhaustive-deps

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
        <div className="field-label">Table</div>
        <select value={table} onChange={(e) => setTable(e.target.value)}>
          <option value="" disabled>Choose…</option>
          {tables.map((t) => (
            <option key={t.name} value={t.name}>
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

        <div className="section-label">Upload</div>
        <label className="upload-btn">
          <input
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
        <VersionFooter />
      </aside>

      <div className="main">
        <div className="topbar">
          <span className="logomark" />
          <span className="brand">Cohort Studio</span>
          <nav className="topnav">
            {(["explore", "lineage", "settings"] as const).map((v) => (
              <span key={v}
                    className={`topnav-link${view === v ? " active" : ""}`}
                    onClick={() => setView(v)}>
                {v[0].toUpperCase() + v.slice(1)}
              </span>
            ))}
          </nav>
          <div style={{ flex: 1 }} />
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
          {view === "settings" ? (
            <SettingsView />
          ) : view === "lineage" ? (
            <LineageView />
          ) : datasets.length === 0 ? (
            <div className="empty">
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none"
                   stroke="#9095a0" strokeWidth="1.5">
                <rect x="3" y="3" width="7" height="9" rx="1.5" />
                <rect x="14" y="3" width="7" height="5" rx="1.5" />
                <rect x="14" y="12" width="7" height="9" rx="1.5" />
                <rect x="3" y="16" width="7" height="5" rx="1.5" />
              </svg>
              <div className="title">No data loaded</div>
              <div className="caption">
                Choose a datasource in the sidebar, or upload a CSV.
                Each table opens in its own tab.
              </div>
            </div>
          ) : (
            <>
              <div className="tabs">
                {datasets.map((d, i) => (
                  <span key={d.id}
                        className={`tab${i === active ? " active" : ""}`}
                        onClick={() => setActive(i)}>
                    {d.title}
                    <button className="quiet" onClick={(e) => {
                      e.stopPropagation(); closeDataset(i);
                    }}>✕</button>
                  </span>
                ))}
              </div>
              {activeDs && (
                <DatasetPane
                  dataset={activeDs}
                  onUpdate={(changes) => updateDataset(active, changes)}
                />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
