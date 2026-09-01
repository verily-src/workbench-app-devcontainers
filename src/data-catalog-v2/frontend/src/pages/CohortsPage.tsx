import { useCallback, useEffect, useMemo, useState } from "react";
import { useCohortDimensions } from "../hooks/useCohortDimensions";
import { useTerminologySlim } from "../hooks/useTerminology";
import type {
  CohortTable,
  CohortFilter,
  CohortJoin,
  CohortCountResult,
  CohortPreviewResult,
  NLCohortResult,
} from "../types/cohort";
import { Badge, Button, Card, Stack, Tabs } from "../components/rds";

const OPERATORS = ["=", "!=", ">", ">=", "<", "<="];

const inputStyle: React.CSSProperties = {
  padding: "6px 10px",
  border: "1px solid var(--wb-border)",
  borderRadius: "var(--wb-radius)",
  fontSize: 13,
  fontFamily: "var(--wb-font)",
  outline: "none",
};

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  background: "#fff",
  cursor: "pointer",
};

function shortTable(fq: string) {
  const parts = fq.split(".");
  return parts.length === 3 ? `${parts[1]}.${parts[2]}` : fq;
}

// ── Shared Results Panel ─────────────────────────────────────────────────────

function ResultsPanel(props: {
  countResult: CohortCountResult | null;
  previewResult: CohortPreviewResult | null;
  sql: string | null;
  explanation?: string;
}) {
  const [showSql, setShowSql] = useState(false);
  const [copied, setCopied] = useState(false);
  const sql = props.previewResult?.sql || props.countResult?.sql || props.sql;

  const copySql = useCallback(() => {
    if (!sql) return;
    navigator.clipboard.writeText(sql).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [sql]);

  return (
    <Stack gap={12}>
      {props.explanation && (
        <div style={{ fontSize: 14, color: "var(--wb-text)", lineHeight: 1.5 }}>
          {props.explanation}
        </div>
      )}

      {props.countResult && (
        <div style={{ fontSize: 18, fontWeight: 600, color: "var(--wb-text)" }}>
          <span style={{ color: "var(--wb-primary)", fontSize: 24 }}>{props.countResult.count.toLocaleString()}</span>
          {" "}matching subjects
        </div>
      )}

      {props.previewResult && props.previewResult.rows.length > 0 && (
        <Card>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--wb-muted)", marginBottom: 8 }}>
            Preview ({props.previewResult.row_count} rows)
          </div>
          <div style={{ overflowX: "auto", maxHeight: 400 }}>
            <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
              <thead>
                <tr>
                  {props.previewResult.columns.map((c) => (
                    <th key={c.name} style={{
                      textAlign: "left", padding: "6px 8px", borderBottom: "2px solid var(--wb-border)",
                      fontSize: 11, fontWeight: 600, textTransform: "uppercase", color: "var(--wb-muted)", whiteSpace: "nowrap",
                      position: "sticky", top: 0, background: "#fff", zIndex: 1,
                    }}>{c.name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {props.previewResult.rows.slice(0, 100).map((row, ri) => (
                  <tr key={ri}>
                    {(row as unknown[]).map((cell, ci) => (
                      <td key={ci} style={{
                        padding: "4px 8px", borderBottom: "1px solid var(--wb-border)",
                        whiteSpace: "nowrap", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis",
                      }}>
                        {cell == null ? <span style={{ color: "var(--wb-muted)" }}>null</span> : String(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {sql && (
        <div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
            <button
              onClick={() => setShowSql(!showSql)}
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: 13, color: "var(--wb-primary)", padding: 0, fontFamily: "var(--wb-font)" }}
            >
              {showSql ? "Hide SQL" : "Show SQL"}
            </button>
            <button
              onClick={copySql}
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "var(--wb-muted)", padding: 0, fontFamily: "var(--wb-font)" }}
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
          {showSql && (
            <pre style={{
              background: "#1e1e1e", color: "#d4d4d4", padding: 16, borderRadius: "var(--wb-radius)",
              fontSize: 12, overflow: "auto", lineHeight: 1.5,
            }}>
              {sql}
            </pre>
          )}
        </div>
      )}
    </Stack>
  );
}

// ── Filter Row ───────────────────────────────────────────────────────────────

function FilterRow(props: {
  filter: CohortFilter;
  table: CohortTable;
  onChange: (f: CohortFilter) => void;
  onRemove: () => void;
}) {
  const dim = props.table.dimensions.find((d) => d.column === props.filter.column);
  const hasValues = dim && dim.values.length > 0 && dim.values.length <= 50;

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      <select
        value={props.filter.column}
        onChange={(e) => props.onChange({ ...props.filter, column: e.target.value, value: "" })}
        style={{ ...selectStyle, minWidth: 180 }}
      >
        <option value="">Select dimension...</option>
        {props.table.dimensions.map((d) => (
          <option key={d.column} value={d.column}>{d.column}</option>
        ))}
      </select>

      <select
        value={props.filter.operator}
        onChange={(e) => props.onChange({ ...props.filter, operator: e.target.value })}
        style={{ ...selectStyle, width: 60 }}
      >
        {OPERATORS.map((op) => (
          <option key={op} value={op}>{op}</option>
        ))}
      </select>

      {hasValues ? (
        <select
          value={props.filter.value}
          onChange={(e) => props.onChange({ ...props.filter, value: e.target.value })}
          style={{ ...selectStyle, minWidth: 160 }}
        >
          <option value="">Select value...</option>
          {dim.values.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      ) : (
        <input
          value={props.filter.value}
          onChange={(e) => props.onChange({ ...props.filter, value: e.target.value })}
          placeholder="Value"
          style={{ ...inputStyle, minWidth: 120 }}
        />
      )}

      {dim?.definition && (
        <span style={{ fontSize: 11, color: "var(--wb-muted)", maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {dim.definition}
        </span>
      )}

      <button
        onClick={props.onRemove}
        style={{ background: "none", border: "none", color: "var(--wb-danger)", cursor: "pointer", fontSize: 16, padding: "0 4px" }}
      >
        x
      </button>
    </div>
  );
}

// ── Join Section ─────────────────────────────────────────────────────────────

function JoinSection(props: {
  join: CohortJoin;
  index: number;
  allTables: CohortTable[];
  baseTable: CohortTable;
  onChange: (j: CohortJoin) => void;
  onRemove: () => void;
}) {
  const joinTable = props.allTables.find((t) => t.fq_table === props.join.target_table);

  const addFilter = () => {
    props.onChange({
      ...props.join,
      filters: [...props.join.filters, { column: "", operator: "=", value: "" }],
    });
  };

  const updateFilter = (i: number, f: CohortFilter) => {
    const next = [...props.join.filters];
    next[i] = f;
    props.onChange({ ...props.join, filters: next });
  };

  const removeFilter = (i: number) => {
    props.onChange({ ...props.join, filters: props.join.filters.filter((_, idx) => idx !== i) });
  };

  return (
    <div style={{
      border: "1px solid var(--wb-border)",
      borderRadius: "var(--wb-radius)",
      padding: 16,
      background: "#fafbfc",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Badge tone="info">JOIN</Badge>
          <select
            value={props.join.target_table}
            onChange={(e) => props.onChange({ ...props.join, target_table: e.target.value, filters: [] })}
            style={{ ...selectStyle, fontWeight: 500 }}
          >
            <option value="">Select table...</option>
            {props.baseTable.joinable_tables.map((jt) => {
              const t = props.allTables.find((x) => x.fq_table === jt);
              return (
                <option key={jt} value={jt}>
                  {t?.business_name || shortTable(jt)}
                </option>
              );
            })}
          </select>
          <span style={{ fontSize: 12, color: "var(--wb-muted)" }}>
            via {props.join.join_column}
          </span>
        </div>
        <button
          onClick={props.onRemove}
          style={{ background: "none", border: "none", color: "var(--wb-danger)", cursor: "pointer", fontSize: 13 }}
        >
          Remove join
        </button>
      </div>

      {joinTable && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {props.join.filters.map((f, i) => (
            <FilterRow
              key={i}
              filter={f}
              table={joinTable}
              onChange={(nf) => updateFilter(i, nf)}
              onRemove={() => removeFilter(i)}
            />
          ))}
          <div>
            <Button size="sm" variant="ghost" onClick={addFilter}>+ Add filter on {shortTable(props.join.target_table)}</Button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Tab 1: Table Filters ─────────────────────────────────────────────────────

function TableFiltersTab() {
  const { data, loading, err } = useCohortDimensions();

  const [baseTableFq, setBaseTableFq] = useState("");
  const [filters, setFilters] = useState<CohortFilter[]>([]);
  const [joins, setJoins] = useState<CohortJoin[]>([]);

  const [running, setRunning] = useState(false);
  const [runErr, setRunErr] = useState<string | null>(null);
  const [countResult, setCountResult] = useState<CohortCountResult | null>(null);
  const [previewResult, setPreviewResult] = useState<CohortPreviewResult | null>(null);

  const allTables = data?.tables || [];
  const baseTable = useMemo(() => allTables.find((t) => t.fq_table === baseTableFq), [allTables, baseTableFq]);

  const selectBase = useCallback((fq: string) => {
    setBaseTableFq(fq);
    setFilters([]);
    setJoins([]);
    setCountResult(null);
    setPreviewResult(null);
    setRunErr(null);
  }, []);

  const addFilter = () => setFilters((prev) => [...prev, { column: "", operator: "=", value: "" }]);
  const updateFilter = (i: number, f: CohortFilter) => setFilters((prev) => { const n = [...prev]; n[i] = f; return n; });
  const removeFilter = (i: number) => setFilters((prev) => prev.filter((_, idx) => idx !== i));

  const addJoin = () => {
    if (!baseTable) return;
    setJoins((prev) => [...prev, { target_table: "", join_column: baseTable.entity_anchor, filters: [] }]);
  };
  const updateJoin = (i: number, j: CohortJoin) => setJoins((prev) => { const n = [...prev]; n[i] = j; return n; });
  const removeJoin = (i: number) => setJoins((prev) => prev.filter((_, idx) => idx !== i));

  const validFilters = filters.filter((f) => f.column && f.value);
  const validJoins = joins.filter((j) => j.target_table);
  const canRun = baseTable && baseTable.entity_anchor && validFilters.length > 0;

  const execute = useCallback(async (mode: "count" | "preview") => {
    if (!baseTable) return;
    setRunning(true);
    setRunErr(null);
    try {
      const r = await fetch("/api/cohorts/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_table: baseTableFq,
          entity_column: baseTable.entity_anchor,
          filters: validFilters,
          joins: validJoins.map((j) => ({
            ...j,
            filters: j.filters.filter((f) => f.column && f.value),
          })),
          mode,
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      const result = await r.json();
      if (mode === "count") {
        setCountResult(result);
        setPreviewResult(null);
      } else {
        setPreviewResult(result);
      }
    } catch (e) {
      setRunErr(String(e));
    } finally {
      setRunning(false);
    }
  }, [baseTable, baseTableFq, validFilters, validJoins]);

  return (
    <Stack gap={16}>
      {loading && <p style={{ color: "var(--wb-muted)" }}>Loading dimensions...</p>}
      {err && <p style={{ color: "var(--wb-danger)" }}>{err}</p>}

      {data && (
        <Stack gap={16}>
          <Card>
            <div style={{ display: "flex", gap: 16, alignItems: "center", flexWrap: "wrap" }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", color: "var(--wb-muted)", marginBottom: 4 }}>
                  Base Table
                </div>
                <select
                  value={baseTableFq}
                  onChange={(e) => selectBase(e.target.value)}
                  style={{ ...selectStyle, minWidth: 280, fontWeight: 500 }}
                >
                  <option value="">Select a table...</option>
                  {allTables.map((t) => (
                    <option key={t.fq_table} value={t.fq_table}>
                      {t.business_name || shortTable(t.fq_table)} ({t.dimensions.length} dimensions)
                    </option>
                  ))}
                </select>
              </div>

              {baseTable && (
                <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                  <div>
                    <div style={{ fontSize: 11, color: "var(--wb-muted)", textTransform: "uppercase", fontWeight: 600 }}>Entity</div>
                    <Badge tone="info">{baseTable.entity_anchor}</Badge>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: "var(--wb-muted)", textTransform: "uppercase", fontWeight: 600 }}>Type</div>
                    <span style={{ fontSize: 13 }}>{baseTable.entity_type || "—"}</span>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: "var(--wb-muted)", textTransform: "uppercase", fontWeight: 600 }}>Dimensions</div>
                    <span style={{ fontSize: 13 }}>{baseTable.dimensions.length}</span>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: "var(--wb-muted)", textTransform: "uppercase", fontWeight: 600 }}>Joinable</div>
                    <span style={{ fontSize: 13 }}>{baseTable.joinable_tables.length} tables</span>
                  </div>
                </div>
              )}
            </div>
          </Card>

          {baseTable && (
            <Card title="Filters">
              <Stack gap={8}>
                {filters.map((f, i) => (
                  <FilterRow
                    key={i}
                    filter={f}
                    table={baseTable}
                    onChange={(nf) => updateFilter(i, nf)}
                    onRemove={() => removeFilter(i)}
                  />
                ))}
                <div>
                  <Button size="sm" variant="ghost" onClick={addFilter}>+ Add filter</Button>
                </div>
              </Stack>
            </Card>
          )}

          {baseTable && baseTable.joinable_tables.length > 0 && (
            <Card title="Joins">
              <Stack gap={12}>
                {joins.map((j, i) => (
                  <JoinSection
                    key={i}
                    join={j}
                    index={i}
                    allTables={allTables}
                    baseTable={baseTable}
                    onChange={(nj) => updateJoin(i, nj)}
                    onRemove={() => removeJoin(i)}
                  />
                ))}
                <div>
                  <Button size="sm" variant="ghost" onClick={addJoin}>+ Add join</Button>
                </div>
              </Stack>
            </Card>
          )}

          {baseTable && (
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Button
                variant="primary"
                onClick={() => execute("count")}
                disabled={!canRun || running}
              >
                {running ? "Running..." : "Count"}
              </Button>
              <Button
                onClick={() => execute("preview")}
                disabled={!canRun || running}
              >
                Preview Rows
              </Button>
              {runErr && <span style={{ fontSize: 13, color: "var(--wb-danger)" }}>{runErr}</span>}
            </div>
          )}

          {(countResult || previewResult) && (
            <ResultsPanel countResult={countResult} previewResult={previewResult} sql={null} />
          )}
        </Stack>
      )}
    </Stack>
  );
}

// ── Tab 2: Terminology ───────────────────────────────────────────────────────

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

interface TermFilterState {
  concept_key: string;
  fq_table: string;
  column: string;
  operator: string;
  value: string;
}

function parseSourceColumn(sc: string): { fq_table: string; column: string } {
  const parts = sc.split(".");
  if (parts.length >= 4) {
    return { fq_table: parts.slice(0, 3).join("."), column: parts[3] };
  }
  const dotIdx = sc.lastIndexOf(".");
  if (dotIdx > 0) {
    return { fq_table: sc.slice(0, dotIdx), column: sc.slice(dotIdx + 1) };
  }
  return { fq_table: "", column: sc };
}

function useColumnValues(fqTable: string, column: string) {
  const [values, setValues] = useState<string[]>([]);
  const [dataType, setDataType] = useState("STRING");

  useEffect(() => {
    if (!fqTable || !column) return;
    let cancelled = false;
    fetch(`/api/cohorts/column-values?table=${encodeURIComponent(fqTable)}&column=${encodeURIComponent(column)}`)
      .then(async (r) => r.ok ? r.json() : null)
      .then((d) => {
        if (!cancelled && d) {
          setValues(d.values || []);
          setDataType(d.data_type || "STRING");
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [fqTable, column]);

  return { values, dataType };
}

function TermFilterRowUI(props: {
  entry: { system: string; code: string; display: string; concept_key: string; source_columns: string[] };
  filter: TermFilterState;
  onChange: (f: TermFilterState) => void;
  onRemove: () => void;
}) {
  const { entry, filter } = props;
  const shortSys = systemShortName(entry.system);
  const tone = systemTones[shortSys] || "neutral";

  const tableColumnMap = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const sc of entry.source_columns) {
      const { fq_table, column } = parseSourceColumn(sc);
      if (!fq_table) continue;
      const cols = map.get(fq_table) || [];
      cols.push(column);
      map.set(fq_table, cols);
    }
    return map;
  }, [entry.source_columns]);

  const tables = useMemo(() => Array.from(tableColumnMap.keys()), [tableColumnMap]);
  const columns = tableColumnMap.get(filter.fq_table) || [];
  const { values: topValues } = useColumnValues(filter.fq_table, filter.column);
  const hasDropdown = topValues.length > 0 && topValues.length <= 50;

  return (
    <div style={{
      display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap",
      padding: "8px 12px", background: "#fafbfc", borderRadius: "var(--wb-radius)",
      border: "1px solid var(--wb-border)",
    }}>
      <Badge tone={tone}>{shortSys}</Badge>
      <span style={{ fontWeight: 500, fontSize: 13, minWidth: 100 }}>{entry.display}</span>

      {tables.length > 1 ? (
        <select
          value={filter.fq_table}
          onChange={(e) => {
            const newTable = e.target.value;
            const newCols = tableColumnMap.get(newTable) || [];
            props.onChange({ ...filter, fq_table: newTable, column: newCols[0] || "", value: "" });
          }}
          style={{ ...selectStyle, minWidth: 160, fontSize: 12 }}
        >
          {tables.map((t) => (
            <option key={t} value={t}>{shortTable(t)}</option>
          ))}
        </select>
      ) : (
        <span style={{ fontSize: 12, color: "var(--wb-muted)" }}>{shortTable(filter.fq_table)}</span>
      )}

      {columns.length > 1 ? (
        <select
          value={filter.column}
          onChange={(e) => props.onChange({ ...filter, column: e.target.value, value: "" })}
          style={{ ...selectStyle, fontSize: 12 }}
        >
          {columns.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      ) : (
        <span style={{ fontFamily: "monospace", fontSize: 12, color: "var(--wb-text)" }}>{filter.column}</span>
      )}

      <select
        value={filter.operator}
        onChange={(e) => props.onChange({ ...filter, operator: e.target.value })}
        style={{ ...selectStyle, width: 60, fontSize: 12 }}
      >
        <option value="">any</option>
        {OPERATORS.map((op) => (
          <option key={op} value={op}>{op}</option>
        ))}
      </select>

      {filter.operator && (
        hasDropdown ? (
          <select
            value={filter.value}
            onChange={(e) => props.onChange({ ...filter, value: e.target.value })}
            style={{ ...selectStyle, minWidth: 120, fontSize: 12 }}
          >
            <option value="">Select value...</option>
            {topValues.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        ) : (
          <input
            value={filter.value}
            onChange={(e) => props.onChange({ ...filter, value: e.target.value })}
            placeholder="Value"
            style={{ ...inputStyle, minWidth: 100, fontSize: 12 }}
          />
        )
      )}

      {!filter.operator && (
        <span style={{ fontSize: 11, color: "var(--wb-muted)", fontStyle: "italic" }}>IS NOT NULL</span>
      )}

      <button
        onClick={props.onRemove}
        style={{ background: "none", border: "none", color: "var(--wb-danger)", cursor: "pointer", fontSize: 16, padding: "0 4px", marginLeft: "auto" }}
      >
        x
      </button>
    </div>
  );
}

function TerminologyTab() {
  const { data, loading, err } = useTerminologySlim();
  const [search, setSearch] = useState("");
  const [termFilters, setTermFilters] = useState<TermFilterState[]>([]);
  const [running, setRunning] = useState(false);
  const [runErr, setRunErr] = useState<string | null>(null);
  const [countResult, setCountResult] = useState<CohortCountResult | null>(null);
  const [previewResult, setPreviewResult] = useState<CohortPreviewResult | null>(null);
  const [resultInfo, setResultInfo] = useState<{ base_table: string; tables_used: string[] } | null>(null);

  const selectedKeys = useMemo(() => new Set(termFilters.map((f) => f.concept_key)), [termFilters]);

  const filtered = useMemo(() => {
    if (!data) return [];
    const q = search.toLowerCase();
    if (!q) return data.entries;
    return data.entries.filter((e) =>
      e.display.toLowerCase().includes(q) ||
      e.code.toLowerCase().includes(q) ||
      systemShortName(e.system).toLowerCase().includes(q)
    );
  }, [data, search]);

  const toggle = useCallback((entry: { concept_key: string; source_columns: string[] }) => {
    const key = entry.concept_key;
    if (selectedKeys.has(key)) {
      setTermFilters((prev) => prev.filter((f) => f.concept_key !== key));
    } else {
      const first = entry.source_columns[0] || "";
      const { fq_table, column } = parseSourceColumn(first);
      setTermFilters((prev) => [...prev, { concept_key: key, fq_table, column, operator: "", value: "" }]);
    }
  }, [selectedKeys]);

  const updateTermFilter = (i: number, f: TermFilterState) => setTermFilters((prev) => { const n = [...prev]; n[i] = f; return n; });
  const removeTermFilter = (i: number) => setTermFilters((prev) => prev.filter((_, idx) => idx !== i));

  const execute = useCallback(async (mode: "count" | "preview") => {
    if (termFilters.length === 0) return;
    setRunning(true);
    setRunErr(null);
    try {
      const r = await fetch("/api/cohorts/from-terminology", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filters: termFilters, mode }),
      });
      if (!r.ok) throw new Error(await r.text());
      const result = await r.json();
      setResultInfo({ base_table: result.base_table, tables_used: result.tables_used || [] });
      if (mode === "count") {
        setCountResult(result);
        setPreviewResult(null);
      } else {
        setPreviewResult(result);
      }
    } catch (e) {
      setRunErr(String(e));
    } finally {
      setRunning(false);
    }
  }, [termFilters]);

  const entryByKey = useMemo(() => {
    if (!data) return new Map();
    return new Map(data.entries.map((e) => [e.concept_key, e]));
  }, [data]);

  return (
    <Stack gap={16}>
      {loading && <p style={{ color: "var(--wb-muted)" }}>Loading terminology...</p>}
      {err && <p style={{ color: "var(--wb-danger)" }}>{err}</p>}

      {data && (
        <>
          <Card>
            <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16 }}>
              <input
                type="text"
                placeholder="Search terms..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{ ...inputStyle, flex: 1 }}
              />
              <span style={{ fontSize: 13, color: "var(--wb-muted)", whiteSpace: "nowrap" }}>
                {termFilters.length} selected
              </span>
              {termFilters.length > 0 && (
                <button
                  onClick={() => setTermFilters([])}
                  style={{ background: "none", border: "none", color: "var(--wb-primary)", cursor: "pointer", fontSize: 13, fontFamily: "var(--wb-font)", padding: 0 }}
                >
                  Clear
                </button>
              )}
            </div>

            <div style={{ maxHeight: 300, overflowY: "auto" }}>
              <table style={{ borderCollapse: "collapse", width: "100%" }}>
                <thead>
                  <tr>
                    <th style={{ width: 36, padding: "8px 4px", borderBottom: "2px solid var(--wb-border)" }} />
                    <th style={{ textAlign: "left", padding: "8px 12px", borderBottom: "2px solid var(--wb-border)", fontSize: 12, fontWeight: 600, textTransform: "uppercase", color: "var(--wb-muted)" }}>System</th>
                    <th style={{ textAlign: "left", padding: "8px 12px", borderBottom: "2px solid var(--wb-border)", fontSize: 12, fontWeight: 600, textTransform: "uppercase", color: "var(--wb-muted)" }}>Code</th>
                    <th style={{ textAlign: "left", padding: "8px 12px", borderBottom: "2px solid var(--wb-border)", fontSize: 12, fontWeight: 600, textTransform: "uppercase", color: "var(--wb-muted)" }}>Name</th>
                    <th style={{ textAlign: "center", padding: "8px 12px", borderBottom: "2px solid var(--wb-border)", fontSize: 12, fontWeight: 600, textTransform: "uppercase", color: "var(--wb-muted)" }}>Tables</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((e) => {
                    const shortSys = systemShortName(e.system);
                    const tone = systemTones[shortSys] || "neutral";
                    const checked = selectedKeys.has(e.concept_key);
                    return (
                      <tr
                        key={e.concept_key}
                        onClick={() => toggle(e)}
                        style={{ cursor: "pointer", background: checked ? "#f0f7ff" : undefined, transition: "background 0.1s" }}
                        onMouseEnter={(ev) => { if (!checked) ev.currentTarget.style.background = "#f8f9fa"; }}
                        onMouseLeave={(ev) => { if (!checked) ev.currentTarget.style.background = ""; }}
                      >
                        <td style={{ padding: "8px 4px", borderBottom: "1px solid var(--wb-border)", textAlign: "center" }}>
                          <input type="checkbox" checked={checked} readOnly style={{ cursor: "pointer" }} />
                        </td>
                        <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--wb-border)" }}>
                          <Badge tone={tone}>{shortSys}</Badge>
                        </td>
                        <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--wb-border)", fontFamily: "monospace", fontSize: 12 }}>{e.code || "—"}</td>
                        <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--wb-border)", fontWeight: 500, fontSize: 13 }}>{e.display}</td>
                        <td style={{ padding: "8px 12px", borderBottom: "1px solid var(--wb-border)", textAlign: "center", fontSize: 12, color: "var(--wb-muted)" }}>{e.tables_count}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {filtered.length === 0 && (
                <div style={{ padding: "24px 0", textAlign: "center", color: "var(--wb-muted)", fontSize: 14 }}>
                  {data.total === 0 ? "No terminology entries. Profile tables with semantic profiling first." : "No terms match your search."}
                </div>
              )}
            </div>
          </Card>

          {termFilters.length > 0 && (
            <Card title="Filters">
              <Stack gap={8}>
                {termFilters.map((f, i) => {
                  const entry = entryByKey.get(f.concept_key);
                  if (!entry) return null;
                  return (
                    <TermFilterRowUI
                      key={f.concept_key}
                      entry={entry}
                      filter={f}
                      onChange={(nf) => updateTermFilter(i, nf)}
                      onRemove={() => removeTermFilter(i)}
                    />
                  );
                })}
              </Stack>
            </Card>
          )}

          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Button variant="primary" onClick={() => execute("count")} disabled={termFilters.length === 0 || running}>
              {running ? "Running..." : "Count"}
            </Button>
            <Button onClick={() => execute("preview")} disabled={termFilters.length === 0 || running}>
              Preview Rows
            </Button>
            {runErr && <span style={{ fontSize: 13, color: "var(--wb-danger)" }}>{runErr}</span>}
          </div>

          {resultInfo && (
            <div style={{ fontSize: 13, color: "var(--wb-muted)" }}>
              Base table: <strong>{shortTable(resultInfo.base_table)}</strong>
              {resultInfo.tables_used.length > 1 && (
                <> | Joined: {resultInfo.tables_used.slice(1).map(shortTable).join(", ")}</>
              )}
            </div>
          )}

          {(countResult || previewResult) && (
            <ResultsPanel countResult={countResult} previewResult={previewResult} sql={null} />
          )}
        </>
      )}
    </Stack>
  );
}

// ── Tab 3: Natural Language ──────────────────────────────────────────────────

function NaturalLanguageTab() {
  const [query, setQuery] = useState("");
  const [running, setRunning] = useState(false);
  const [runErr, setRunErr] = useState<string | null>(null);
  const [nlResult, setNlResult] = useState<NLCohortResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewData, setPreviewData] = useState<CohortPreviewResult | null>(null);

  const generate = useCallback(async () => {
    if (!query.trim()) return;
    setRunning(true);
    setRunErr(null);
    setNlResult(null);
    setPreviewData(null);
    try {
      const r = await fetch("/api/cohorts/from-natural-language", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), mode: "generate" }),
      });
      if (!r.ok) throw new Error(await r.text());
      setNlResult(await r.json());
    } catch (e) {
      setRunErr(String(e));
    } finally {
      setRunning(false);
    }
  }, [query]);

  const execute = useCallback(async () => {
    if (!query.trim()) return;
    setRunning(true);
    setRunErr(null);
    setPreviewData(null);
    try {
      const r = await fetch("/api/cohorts/from-natural-language", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), mode: "execute" }),
      });
      if (!r.ok) throw new Error(await r.text());
      setNlResult(await r.json());
    } catch (e) {
      setRunErr(String(e));
    } finally {
      setRunning(false);
    }
  }, [query]);

  const runPreview = useCallback(async () => {
    if (!nlResult?.preview_sql) return;
    setPreviewLoading(true);
    setRunErr(null);
    try {
      const r = await fetch("/api/cohorts/run-preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sql: nlResult.preview_sql }),
      });
      if (!r.ok) throw new Error(await r.text());
      setPreviewData(await r.json());
    } catch (e) {
      setRunErr(String(e));
    } finally {
      setPreviewLoading(false);
    }
  }, [nlResult]);

  const countResult = nlResult?.count != null ? { sql: nlResult.sql, count: nlResult.count } : null;
  const nlPreviewResult = nlResult?.rows ? {
    sql: nlResult.sql,
    columns: nlResult.columns || [],
    rows: nlResult.rows,
    row_count: nlResult.row_count || 0,
  } : null;

  return (
    <Stack gap={16}>
      <Card>
        <div style={{ marginBottom: 12, fontSize: 13, color: "var(--wb-muted)" }}>
          Describe the cohort you want to find in plain English. The system will generate a BigQuery SQL query using your profiled datasets.
        </div>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g., Patients over 65 with type 2 diabetes who had a lab result in the last year"
          rows={3}
          style={{
            width: "100%",
            padding: "10px 12px",
            border: "1px solid var(--wb-border)",
            borderRadius: "var(--wb-radius)",
            fontSize: 14,
            fontFamily: "var(--wb-font)",
            outline: "none",
            resize: "vertical",
            lineHeight: 1.5,
            boxSizing: "border-box",
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              generate();
            }
          }}
        />
      </Card>

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Button variant="primary" onClick={generate} disabled={!query.trim() || running}>
          {running ? "Generating..." : "Generate SQL"}
        </Button>
        <Button onClick={execute} disabled={!query.trim() || running}>
          Generate & Run
        </Button>
        {countResult && nlResult?.preview_sql && (
          <Button onClick={runPreview} disabled={previewLoading}>
            {previewLoading ? "Loading..." : "Preview Rows"}
          </Button>
        )}
        {runErr && <span style={{ fontSize: 13, color: "var(--wb-danger)" }}>{runErr}</span>}
      </div>

      {nlResult && (
        <ResultsPanel
          countResult={countResult}
          previewResult={previewData || nlPreviewResult}
          sql={nlResult.sql}
          explanation={nlResult.explanation}
        />
      )}
    </Stack>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

const TAB_LABELS = ["Table Filters", "Terminology", "Natural Language"];

export default function CohortsPage() {
  const [tab, setTab] = useState(0);

  return (
    <div style={{ padding: "32px 40px" }}>
      <Stack gap={24}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: "var(--wb-text)" }}>Cohort Builder</h1>
          <p style={{ margin: "4px 0 0", fontSize: 14, color: "var(--wb-muted)" }}>
            Build subject cohorts using filters, terminology, or natural language
          </p>
        </div>

        <Tabs labels={TAB_LABELS} active={tab} onChange={setTab} />

        {tab === 0 && <TableFiltersTab />}
        {tab === 1 && <TerminologyTab />}
        {tab === 2 && <NaturalLanguageTab />}
      </Stack>
    </div>
  );
}
