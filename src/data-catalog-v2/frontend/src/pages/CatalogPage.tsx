import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { FilterBar } from "../components/FilterBar";
import { BulkActionBar, BulkProgressDrawer } from "../components/BulkProfileBar";
import { Badge, Card } from "../components/rds";
import { useBulkProfile } from "../hooks/useBulkProfile";
import type { BulkMode } from "../types/bulk";
import type { ApiConfig, CatalogDataset, CatalogTable } from "../types/catalog";

function matchesFilter(t: CatalogTable, state: "all" | "none" | "tech" | "full") {
  const tech = t.profiling.technical;
  const sem = t.profiling.semantic;
  if (state === "all") return true;
  if (state === "none") return tech !== "available";
  if (state === "tech") return tech === "available" && sem !== "available";
  return tech === "available" && sem === "available";
}

function profilingBadge(t: CatalogTable) {
  const tech = t.profiling.technical;
  const sem = t.profiling.semantic;
  if (tech === "running" || sem === "running") return <Badge tone="running">Profiling…</Badge>;
  if (tech === "available" && sem === "available") return <Badge tone="success">Fully profiled</Badge>;
  if (tech === "available") return <Badge tone="info">Technical only</Badge>;
  return <Badge tone="neutral">Not profiled</Badge>;
}

function formatSize(bytes: number | null) {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export default function CatalogHome(props: {
  config: ApiConfig | null;
  datasets: CatalogDataset[];
  loading: boolean;
  onRefresh?: () => void;
}) {
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState<"all" | "none" | "tech" | "full">("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const bulk = useBulkProfile(props.onRefresh);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return props.datasets.map((ds) => ({
      ...ds,
      tables: ds.tables.filter((t) => {
        if (!matchesFilter(t, stateFilter)) return false;
        if (!q) return true;
        return t.table_id.toLowerCase().includes(q) || t.fq_table.toLowerCase().includes(q);
      }),
    }));
  }, [props.datasets, search, stateFilter]);

  const totalTables = props.datasets.reduce((n, d) => n + d.tables.length, 0);
  const filteredTables = filtered.reduce((n, d) => n + d.tables.length, 0);
  const allFilteredFqs = useMemo(() => filtered.flatMap((ds) => ds.tables.map((t) => t.fq_table)), [filtered]);

  const toggleSelect = useCallback((fq: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(fq)) next.delete(fq);
      else next.add(fq);
      return next;
    });
  }, []);

  const selectDataset = useCallback((ds: CatalogDataset) => {
    setSelected((prev) => {
      const next = new Set(prev);
      const fqs = ds.tables.map((t) => t.fq_table);
      const allIn = fqs.every((fq) => next.has(fq));
      if (allIn) {
        fqs.forEach((fq) => next.delete(fq));
      } else {
        fqs.forEach((fq) => next.add(fq));
      }
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelected((prev) => {
      if (prev.size === allFilteredFqs.length) return new Set();
      return new Set(allFilteredFqs);
    });
  }, [allFilteredFqs]);

  const handleBulkProfile = useCallback(
    (mode: BulkMode, force = false) => {
      const tables = Array.from(selected);
      if (tables.length === 0) return;
      bulk.startBatch(tables, mode, force);
      setSelected(new Set());
    },
    [selected, bulk],
  );

  const profileDataset = useCallback(
    (ds: CatalogDataset, mode: BulkMode, force = false) => {
      const tables = ds.tables.map((t) => t.fq_table);
      if (tables.length === 0) return;
      bulk.startBatch(tables, mode, force);
    },
    [bulk],
  );

  return (
    <div style={{ padding: "32px 40px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: "var(--wb-text)" }}>
            {props.config?.data_project_name || "Data Catalog"}
            {props.config?.data_project_name && (
              <span style={{ fontSize: 14, fontWeight: 400, color: "var(--wb-muted)", marginLeft: 8 }}>
                ({props.config?.data_project})
              </span>
            )}
            {!props.config?.data_project_name && (
              <span style={{ color: "var(--wb-primary)", marginLeft: 8 }}>{props.config?.data_project}</span>
            )}
          </h1>
          <p style={{ color: "var(--wb-muted)", margin: "8px 0 0", fontSize: 14 }}>
            {props.loading
              ? "Loading datasets…"
              : `${totalTables} table(s) across ${props.datasets.length} dataset(s).`}
          </p>
        </div>
        {!props.loading && totalTables > 0 && (
          <div style={{ display: "flex", gap: 6 }}>
            <button
              onClick={selectAll}
              style={{
                background: "var(--wb-surface)",
                border: "1px solid var(--wb-border)",
                borderRadius: 6,
                padding: "6px 14px",
                fontSize: 12,
                cursor: "pointer",
                fontWeight: 500,
              }}
            >
              {selected.size === allFilteredFqs.length && selected.size > 0 ? "Deselect all" : "Select all"}
            </button>
            <button
              onClick={() => bulk.startBatch(allFilteredFqs, "both")}
              disabled={bulk.loading || allFilteredFqs.length === 0}
              style={{
                background: "var(--wb-primary, #1a5c5e)",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                padding: "6px 14px",
                fontSize: 12,
                cursor: bulk.loading ? "not-allowed" : "pointer",
                fontWeight: 600,
                opacity: bulk.loading ? 0.5 : 1,
              }}
            >
              Profile entire project
            </button>
          </div>
        )}
      </div>

      <Card style={{ marginBottom: 24, marginTop: 16 }}>
        <FilterBar search={search} onSearch={setSearch} stateFilter={stateFilter} onStateFilter={setStateFilter} />
        {search || stateFilter !== "all" ? (
          <div style={{ fontSize: 13, color: "var(--wb-muted)", marginTop: 8 }}>
            Showing {filteredTables} of {totalTables} tables
          </div>
        ) : null}
      </Card>

      {filtered.map((ds) =>
        ds.tables.length === 0 ? null : (
          <div key={ds.dataset_id} style={{ marginBottom: 24 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <h2
                style={{
                  fontSize: 14,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                  color: "var(--wb-muted)",
                  margin: 0,
                }}
              >
                {ds.dataset_id}
                <span style={{ fontWeight: 400, textTransform: "none", marginLeft: 8 }}>
                  {ds.tables.length} {ds.tables.length === 1 ? "table" : "tables"}
                </span>
              </h2>
              <div style={{ display: "flex", gap: 6 }}>
                <button
                  onClick={() => selectDataset(ds)}
                  style={{ background: "none", border: "1px solid var(--wb-border)", borderRadius: 4, padding: "3px 10px", fontSize: 11, cursor: "pointer" }}
                >
                  {ds.tables.every((t) => selected.has(t.fq_table)) ? "Deselect" : "Select all"}
                </button>
                <button
                  onClick={() => profileDataset(ds, "both")}
                  disabled={bulk.loading}
                  style={{
                    background: "var(--wb-primary, #1a5c5e)",
                    color: "#fff",
                    border: "none",
                    borderRadius: 4,
                    padding: "3px 10px",
                    fontSize: 11,
                    cursor: bulk.loading ? "not-allowed" : "pointer",
                    fontWeight: 600,
                    opacity: bulk.loading ? 0.5 : 1,
                  }}
                >
                  Profile all
                </button>
              </div>
            </div>

            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                <thead>
                  <tr style={{ background: "var(--wb-surface)" }}>
                    <th style={{ width: 36, padding: "10px 8px", borderBottom: "2px solid var(--wb-border)" }}>
                      <input
                        type="checkbox"
                        checked={ds.tables.length > 0 && ds.tables.every((t) => selected.has(t.fq_table))}
                        onChange={() => selectDataset(ds)}
                        style={{ cursor: "pointer" }}
                      />
                    </th>
                    {["Table", "Rows", "Size", "Columns", "Profiling"].map((h) => (
                      <th
                        key={h}
                        style={{
                          textAlign: "left",
                          padding: "10px 14px",
                          borderBottom: "2px solid var(--wb-border)",
                          color: "var(--wb-muted)",
                          fontWeight: 600,
                          fontSize: 12,
                          textTransform: "uppercase",
                          letterSpacing: "0.04em",
                        }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {ds.tables.map((t) => {
                    const to = `/table/${encodeURIComponent(t.project_id)}/${encodeURIComponent(t.dataset_id)}/${encodeURIComponent(t.table_id)}`;
                    return (
                      <tr
                        key={t.fq_table}
                        style={{
                          borderBottom: "1px solid var(--wb-border)",
                          cursor: "pointer",
                          background: selected.has(t.fq_table) ? "#f0f7f7" : "transparent",
                        }}
                        onMouseEnter={(e) => { if (!selected.has(t.fq_table)) e.currentTarget.style.background = "#f8fafb"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = selected.has(t.fq_table) ? "#f0f7f7" : "transparent"; }}
                      >
                        <td style={{ padding: "10px 8px", verticalAlign: "top" }}>
                          <input
                            type="checkbox"
                            checked={selected.has(t.fq_table)}
                            onChange={() => toggleSelect(t.fq_table)}
                            onClick={(e) => e.stopPropagation()}
                            style={{ cursor: "pointer" }}
                          />
                        </td>
                        <td style={{ padding: "10px 14px" }}>
                          <Link to={to} style={{ fontWeight: 600 }}>
                            {t.business_name || t.table_id}
                          </Link>
                          {t.business_name ? (
                            <div style={{ fontSize: 12, color: "var(--wb-muted)", fontWeight: 400, marginTop: 1 }}>
                              {t.table_id}
                            </div>
                          ) : null}
                          {t.table_definition ? (
                            <div style={{ fontSize: 12, color: "var(--wb-muted)", fontWeight: 400, marginTop: 3, lineHeight: 1.4, maxWidth: 360 }}>
                              {t.table_definition.length > 120 ? t.table_definition.slice(0, 120) + "…" : t.table_definition}
                            </div>
                          ) : null}
                        </td>
                        <td style={{ padding: "10px 14px", color: "var(--wb-muted)", verticalAlign: "top" }}>
                          {t.row_count != null ? t.row_count.toLocaleString() : "—"}
                        </td>
                        <td style={{ padding: "10px 14px", color: "var(--wb-muted)", verticalAlign: "top" }}>
                          {formatSize(t.size_bytes)}
                        </td>
                        <td style={{ padding: "10px 14px", color: "var(--wb-muted)", verticalAlign: "top" }}>
                          {t.column_count}
                        </td>
                        <td style={{ padding: "10px 14px", verticalAlign: "top" }}>{profilingBadge(t)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ),
      )}

      <BulkActionBar
        count={selected.size}
        onProfile={handleBulkProfile}
        onClear={() => setSelected(new Set())}
        disabled={bulk.loading}
        hasExistingProfiles={
          Array.from(selected).some((fq) => {
            for (const ds of props.datasets) {
              const tbl = ds.tables.find((t: any) => t.fq_table === fq);
              if (tbl) return tbl.profiling?.technical === "available" || tbl.profiling?.semantic === "available";
            }
            return false;
          })
        }
      />

      <BulkProgressDrawer
        status={bulk.status}
        loading={bulk.loading}
        error={bulk.error}
        onDismiss={bulk.dismiss}
      />
    </div>
  );
}
