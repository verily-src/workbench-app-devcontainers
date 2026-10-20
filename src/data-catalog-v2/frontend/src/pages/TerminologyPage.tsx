import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTerminology } from "../hooks/useTerminology";
import type { TerminologyEntry, ColumnMeta } from "../types/profile";
import { Badge, Card, Stack } from "../components/rds";

function systemShortName(uri: string): string {
  if (uri.includes("loinc")) return "LOINC";
  if (uri.includes("snomed") || uri.includes("sct")) return "SNOMED";
  if (uri.includes("icd-10")) return "ICD-10";
  if (uri.includes("rxnorm")) return "RxNorm";
  if (uri.includes("ndc")) return "NDC";
  if (uri.includes("cpt")) return "CPT";
  if (uri.includes("verily:custom")) return "Custom";
  return uri.split("/").pop() || uri;
}

const systemTones: Record<string, "info" | "success" | "warn" | "neutral"> = {
  LOINC: "info",
  SNOMED: "success",
  "ICD-10": "warn",
  RxNorm: "info",
  Custom: "neutral",
};

function tableUrl(fqTable: string) {
  const parts = fqTable.split(".");
  if (parts.length !== 3) return "/";
  return `/table/${encodeURIComponent(parts[0])}/${encodeURIComponent(parts[1])}/${encodeURIComponent(parts[2])}`;
}

function shortTable(fqTable: string) {
  const parts = fqTable.split(".");
  if (parts.length !== 3) return fqTable;
  return `${parts[1]}.${parts[2]}`;
}

const th: React.CSSProperties = {
  textAlign: "left",
  padding: "10px 12px",
  borderBottom: "2px solid var(--wb-border)",
  fontSize: 12,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.03em",
  color: "var(--wb-muted)",
  whiteSpace: "nowrap",
};

const td: React.CSSProperties = {
  padding: "10px 12px",
  borderBottom: "1px solid var(--wb-border)",
  verticalAlign: "top",
  fontSize: 13,
};

const methodStyle: React.CSSProperties = {
  display: "inline-block",
  padding: "1px 6px",
  borderRadius: 3,
  fontSize: 10,
  fontWeight: 500,
  background: "#f3e5f5",
  color: "#7b1fa2",
  marginLeft: 6,
};

function ExpandedSources(props: { meta: ColumnMeta[] }) {
  const grouped = useMemo(() => {
    const map = new Map<string, ColumnMeta[]>();
    for (const m of props.meta) {
      const fq = m.fq_table || m.fq_column;
      const cols = map.get(fq) || [];
      cols.push(m);
      map.set(fq, cols);
    }
    return Array.from(map.entries());
  }, [props.meta]);

  return (
    <tr>
      <td colSpan={5} style={{ padding: "8px 12px 12px 40px", borderBottom: "1px solid var(--wb-border)", background: "#fafafa" }}>
        <div style={{ fontSize: 12, color: "var(--wb-muted)", marginBottom: 8, fontWeight: 600 }}>
          Appears in {grouped.length} {grouped.length === 1 ? "table" : "tables"}:
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {grouped.map(([fqTable, cols]) => (
            <div key={fqTable}>
              <Link
                to={tableUrl(fqTable)}
                style={{ color: "var(--wb-primary)", textDecoration: "none", fontWeight: 500, fontSize: 13 }}
              >
                {shortTable(fqTable)}
              </Link>
              <div style={{ marginLeft: 16, display: "flex", flexDirection: "column", gap: 2, marginTop: 2, marginBottom: 6 }}>
                {cols.map((c) => (
                  <div key={c.fq_column} style={{ display: "flex", alignItems: "baseline", gap: 6, fontSize: 12 }}>
                    <span style={{ fontFamily: "monospace", fontWeight: 500, minWidth: 120 }}>{c.column || c.fq_column}</span>
                    {c.definition && (
                      <span style={{ color: "var(--wb-muted)" }}>{c.definition}</span>
                    )}
                    {c.measurement_method && (
                      <span style={methodStyle}>{c.measurement_method}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </td>
    </tr>
  );
}

function TermRow(props: { entry: TerminologyEntry }) {
  const [expanded, setExpanded] = useState(false);
  const e = props.entry;
  const shortSys = systemShortName(e.system);
  const tone = systemTones[shortSys] || "neutral";

  return (
    <>
      <tr
        onClick={() => setExpanded(!expanded)}
        style={{ cursor: "pointer", transition: "background 0.1s" }}
        onMouseEnter={(ev) => { ev.currentTarget.style.background = "#f8f9fa"; }}
        onMouseLeave={(ev) => { ev.currentTarget.style.background = ""; }}
      >
        <td style={td}><Badge tone={tone}>{shortSys}</Badge></td>
        <td style={{ ...td, fontFamily: "monospace", fontSize: 12 }}>{e.code || "—"}</td>
        <td style={{ ...td, fontWeight: 500 }}>{e.display}</td>
        <td style={{ ...td, textAlign: "center" }}>
          <span style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            minWidth: 24,
            height: 22,
            borderRadius: 11,
            background: e.tables_count > 1 ? "#e3f2fd" : "#f5f5f5",
            color: e.tables_count > 1 ? "#1565c0" : "var(--wb-muted)",
            fontSize: 12,
            fontWeight: 600,
            padding: "0 6px",
          }}>
            {e.tables_count}
          </span>
        </td>
        <td style={{ ...td, textAlign: "center", color: "var(--wb-muted)" }}>{e.columns_count}</td>
      </tr>
      {expanded && <ExpandedSources meta={e.columns_meta || []} />}
    </>
  );
}

export default function TerminologyPage() {
  const { data, loading, err } = useTerminology();
  const [search, setSearch] = useState("");
  const [systemFilter, setSystemFilter] = useState("all");

  const systems = useMemo(() => {
    if (!data) return [];
    const set = new Set<string>();
    for (const e of data.entries) set.add(systemShortName(e.system));
    return Array.from(set).sort();
  }, [data]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = search.toLowerCase();
    return data.entries.filter((e) => {
      if (systemFilter !== "all" && systemShortName(e.system) !== systemFilter) return false;
      if (!q) return true;
      return (
        e.display.toLowerCase().includes(q) ||
        e.code.toLowerCase().includes(q) ||
        systemShortName(e.system).toLowerCase().includes(q)
      );
    });
  }, [data, search, systemFilter]);

  return (
    <div style={{ padding: "32px 40px" }}>
      <Stack gap={24}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: "var(--wb-text)" }}>Terminology</h1>
          <p style={{ margin: "4px 0 0", fontSize: 14, color: "var(--wb-muted)" }}>
            Standard codes and terms across your datasets
          </p>
        </div>

        {loading && <p style={{ color: "var(--wb-muted)" }}>Loading terminology...</p>}
        {err && <p style={{ color: "var(--wb-danger)" }}>{err}</p>}

        {data && (
          <Card>
            <div style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "center" }}>
              <input
                type="text"
                placeholder="Search terms..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{
                  flex: 1,
                  padding: "8px 12px",
                  border: "1px solid var(--wb-border)",
                  borderRadius: "var(--wb-radius)",
                  fontSize: 14,
                  fontFamily: "var(--wb-font)",
                  outline: "none",
                }}
              />
              <select
                value={systemFilter}
                onChange={(e) => setSystemFilter(e.target.value)}
                style={{
                  padding: "8px 12px",
                  border: "1px solid var(--wb-border)",
                  borderRadius: "var(--wb-radius)",
                  fontSize: 14,
                  fontFamily: "var(--wb-font)",
                  background: "#fff",
                  cursor: "pointer",
                }}
              >
                <option value="all">All Systems</option>
                {systems.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <span style={{ fontSize: 13, color: "var(--wb-muted)", whiteSpace: "nowrap" }}>
                {filtered.length} of {data.total} terms
              </span>
            </div>

            {filtered.length === 0 ? (
              <div style={{ padding: "32px 0", textAlign: "center", color: "var(--wb-muted)", fontSize: 14 }}>
                {data.total === 0
                  ? "No terminology entries found. Profile tables with semantic profiling to populate."
                  : "No terms match your search."}
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ borderCollapse: "collapse", width: "100%" }}>
                  <thead>
                    <tr>
                      <th style={th}>Source</th>
                      <th style={th}>Code</th>
                      <th style={th}>Name</th>
                      <th style={{ ...th, textAlign: "center" }}>Tables</th>
                      <th style={{ ...th, textAlign: "center" }}>Columns</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((e) => (
                      <TermRow key={e.concept_key} entry={e} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}
      </Stack>
    </div>
  );
}
