import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { DataJob } from "../api";
import type {
  ColumnProfile, Dataset, JoinCondition, JoinEngine, JoinFilter, JoinFilterOp, JoinFilterValue,
  JoinHow, JoinOp, JoinPreview, JoinStep,
  JoinRecommendation, JoinSuggestion, JoinValidation, Source, SourceRef, TableInfo,
} from "../types";
import { Combobox } from "./Combobox";
import { tableStats } from "../format";
import { SqlEditor } from "./SqlEditor";
import { JobProgress } from "./DataJobs";

interface Props {
  datasets: Dataset[];
  sources: Source[];
  busy: boolean;
  onJoin: (p: { baseId: string; steps: JoinStep[]; allowLoaded?: boolean;
                baseFilters?: JoinFilter[] }) => void;
  initialPlan?: { title: string; baseId: string; steps: JoinStep[]; allowLoaded: boolean;
                  baseFilters?: JoinFilter[] };
  onSourceOpened: (opened: Awaited<ReturnType<typeof api.openSourceRef>>,
                   title: string, sourceRef: SourceRef) => void;
  onClose: () => void;
  /** Opens the visual join canvas (the recommended way to build a join). */
  onOpenCanvas?: () => void;
}

export const HOWS: { id: JoinHow; label: string; hint: string }[] = [
  { id: "left", label: "Left", hint: "Keep every row on the left; add matches" },
  { id: "inner", label: "Inner", hint: "Only rows that match on both sides" },
  { id: "right", label: "Right", hint: "Keep every row of the joined table" },
  { id: "full", label: "Full", hint: "Keep every row from both sides" },
  { id: "semi", label: "Has match", hint: "Left rows with a match; adds no columns" },
  { id: "anti", label: "No match", hint: "Left rows without a match; adds no columns" },
];
const OPS: JoinOp[] = ["=", "!=", "<", "<=", ">", ">="];
export const ARROW = " → ";
const MAX_STEPS = 6;
const VALIDATE_DELAY_MS = 300;
const ENGINE_LABEL: Record<JoinEngine, string> = {
  aurora: "runs in Aurora", duckdb: "runs in memory",
};
const SOURCE_GROUP_LABEL: Record<Source["kind"], string> = {
  aurora: "Aurora", postgres: "PostgreSQL / RDS", athena: "Athena / Iceberg", s3: "S3 files", bq: "BigQuery", catalog: "Catalogs",
};

/** A condition row in the editor; `touched` once focus has left the row. */
interface CondRow extends JoinCondition { touched?: boolean }

/** A value-filter row in the editor; `text` is what the user typed. */
export interface FilterRow {
  column: string; op: JoinFilterOp; text: string; touched?: boolean;
  /** Saved list values, sent as-is until the user edits the text. */
  list?: JoinFilterValue[];
  /** Whether `text` is in list form (comma-separated, quoted); defaults to the operator's form. */
  textIsList?: boolean;
}

/** `uid` is a stable React key: index keys let a removed step's open
 * details and combobox state leak into the step that moves up. */
interface StepState extends Omit<JoinStep, "conditions" | "filters"> {
  conditions: CondRow[];
  filterRows: FilterRow[];
  touched: boolean; pickCols: boolean; uid: string;
  /** UI-only: narrow left keys to the base ("base") or an earlier step's uid. */
  joinTo?: string;
}

export type ColKind = "number" | "bool" | "time" | "text";
export const KIND_LABEL: Record<ColKind, string> = {
  number: "number", bool: "true/false", time: "date", text: "text",
};

/** Best guess of how the server will type a column (it checks again). */
export function colKind(column?: ColumnProfile): ColKind {
  const dtype = (column?.dtype ?? "").toLowerCase();
  if (dtype.includes("bool")) return "bool";
  if (/int|float|double|decimal|numeric|real/.test(dtype)) return "number";
  if (/date|time/.test(dtype)) return "time";
  return "text";
}

export const NULL_OPS: JoinFilterOp[] = ["is null", "is not null"];
export const LIST_OPS: JoinFilterOp[] = ["in", "not in"];
const FILTER_OPS: Record<ColKind, JoinFilterOp[]> = {
  text: ["=", "!=", "contains", "in", "not in", "<", "<=", ">", ">=", "is null", "is not null"],
  number: ["=", "!=", "<", "<=", ">", ">=", "in", "not in", "is null", "is not null"],
  time: ["=", "!=", "<", "<=", ">", ">=", "in", "not in", "is null", "is not null"],
  bool: ["=", "!=", "is null", "is not null"],
};
const OP_LABEL: Partial<Record<JoinFilterOp, string>> = {
  "in": "is one of", "not in": "is not one of", "contains": "contains",
};
const NUMBER_TEXT = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

const isBlankCond = (c: JoinCondition) => !c.left && !c.right;
const isCompleteCond = (c: JoinCondition) => Boolean(c.left && c.right);

function typedValue(text: string, kind: ColKind): JoinFilterValue {
  const raw = text.trim();
  // Integers beyond 2^53 stay text: the server parses them exactly.
  if (kind === "number" && NUMBER_TEXT.test(raw)
      && (!/^[+-]?\d+$/.test(raw) || Number.isSafeInteger(Number(raw)))) return Number(raw);
  if (kind === "bool" && (raw === "true" || raw === "false")) return raw === "true";
  return kind === "text" ? text : raw;
}

/** List text: items separated by commas; an item containing a comma, a quote or
 * edge spaces is written in double quotes with inner quotes doubled
 * ("Smith, John", "say ""hi"""). */
function formatList(values: JoinFilterValue[]): string {
  return values.map((v) => {
    const text = String(v);
    return /[",]|^\s|\s$/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }).join(", ");
}

/** Re-express a row's value when its operator switches between list and single-value forms,
 * so list quoting never leaks into a scalar value (or the reverse). */
function convertValue(row: FilterRow, op: JoinFilterOp): Partial<FilterRow> {
  // Null checks carry no value: keep the text (and its form) so switching back restores it.
  if (NULL_OPS.includes(op))
    return { textIsList: row.textIsList ?? (NULL_OPS.includes(row.op) ? false : LIST_OPS.includes(row.op)) };
  const wasList = row.textIsList ?? LIST_OPS.includes(row.op), isList = LIST_OPS.includes(op);
  if (wasList === isList) return { textIsList: isList };
  if (wasList) {
    const items = row.list ? row.list.map(String) : parseList(row.text);
    return { list: undefined, textIsList: false,
             text: items.length === 1 ? items[0] : items.join(", ") };
  }
  return { list: undefined, textIsList: true, text: row.text.trim() ? formatList([row.text]) : "" };
}

function parseList(text: string): string[] {
  const items: string[] = [];
  let i = 0;
  while (i < text.length) {
    while (text[i] === " " || text[i] === "\t") i++;
    if (i >= text.length) break;
    let item = "";
    if (text[i] === '"') {
      i++;
      while (i < text.length) {
        if (text[i] === '"' && text[i + 1] === '"') { item += '"'; i += 2; }
        else if (text[i] === '"') { i++; break; }
        else item += text[i++];
      }
      while (i < text.length && text[i] !== ",") i++;   // ignore text after the closing quote
      items.push(item);
    } else {
      while (i < text.length && text[i] !== ",") item += text[i++];
      if (item.trim()) items.push(item.trim());
    }
    i++;   // skip the comma
  }
  return items;
}

/** Filter rows the server should see: blank rows (no column) and rows still
 * missing a value are left out. */
export function sentFilters(rows: FilterRow[], columns: ColumnProfile[]): { filter: JoinFilter; row: number }[] {
  const out: { filter: JoinFilter; row: number }[] = [];
  rows.forEach((row, index) => {
    if (!row.column || filterProblem(row)) return;
    const kind = colKind(columns.find((c) => c.name === row.column));
    if (NULL_OPS.includes(row.op)) out.push({ filter: { column: row.column, op: row.op }, row: index });
    else if (LIST_OPS.includes(row.op)) out.push({ row: index, filter: { column: row.column, op: row.op,
      value: row.list ?? parseList(row.text).map((v) => typedValue(v, kind)) } });
    else out.push({ row: index, filter: { column: row.column, op: row.op,
      value: row.op === "contains" ? row.text : typedValue(row.text, kind) } });
  });
  return out;
}

export function filterProblem(row: FilterRow): string | null {
  if (!row.column || NULL_OPS.includes(row.op)) return null;
  if (LIST_OPS.includes(row.op))
    return (row.list?.length || parseList(row.text).length) ? null
      : `Enter one or more values for ${row.column}, separated by commas.`;
  return row.text.trim() ? null : `Enter a value for ${row.column}.`;
}

export const fromFilter = (f: JoinFilter): FilterRow => ({
  column: f.column, op: f.op, touched: true,
  text: Array.isArray(f.value) ? formatList(f.value) : f.value == null ? "" : String(f.value),
  textIsList: Array.isArray(f.value),
  ...(Array.isArray(f.value) ? { list: f.value } : {}),
});

/** Leaving a row (focus moves outside it) marks it touched. */
const leftRow = (event: React.FocusEvent<HTMLElement>) =>
  !event.currentTarget.contains(event.relatedTarget as Node | null);

export function FilterEditor({ rows, columns, table, label, checks, disabled, onChange }: {
  rows: FilterRow[]; columns: ColumnProfile[]; table: string; label: string;
  checks?: { problem: string | null }[]; disabled: boolean;
  onChange: (rows: FilterRow[]) => void;
}) {
  const sent = sentFilters(rows, columns);
  const set = (k: number, patch: Partial<FilterRow>) =>
    onChange(rows.map((row, m) => (m !== k ? row : {
      ...row, ...patch,
      // Editing the value or column drops the saved list; the text is parsed instead.
      ...("text" in patch || "column" in patch ? { list: undefined } : {}),
      // Typed text takes the form of the operator it is typed under.
      ...("text" in patch ? { textIsList: LIST_OPS.includes(patch.op ?? row.op) } : {}),
      // A patch that sets the value itself (e.g. a column change resetting it) wins.
      ...(patch.op && !("text" in patch) ? convertValue(row, patch.op) : {}),
    })));
  const hasBlank = rows.some((row) => !row.column);
  return (
    <div className={`join-section join-filters${label === "Start table" ? " join-base-filters" : ""}`} role="group" aria-label={`${label} filters`}>
      {rows.length > 0 && <div className="join-section-title">
        Filter {table} <span className="settings-hint">Filters this table before joining</span>
      </div>}
      {rows.map((row, k) => {
        const column = columns.find((c) => c.name === row.column);
        const kind = colKind(column);
        const ops = FILTER_OPS[kind].includes(row.op) ? FILTER_OPS[kind] : [row.op, ...FILTER_OPS[kind]];
        const sentIndex = sent.findIndex((item) => item.row === k);
        const serverProblem = sentIndex >= 0 ? checks?.[sentIndex]?.problem : null;
        const localProblem = row.touched ? filterProblem(row) : null;
        const problem = localProblem ?? serverProblem;
        const name = `${label} filter ${k + 1}`;
        return (
          <Fragment key={k}>
            <div className={`join-filter${problem ? " invalid" : ""}`}
                 onBlur={(e) => { if (leftRow(e) && row.column && !row.touched) set(k, { touched: true }); }}>
              <span className="join-cond-label">{k === 0 ? "where" : "and"}</span>
              <span className="join-pick">
                <select aria-label={`${name} column`} value={row.column} disabled={disabled}
                        onChange={(e) => {
                          const nextKind = colKind(columns.find((c) => c.name === e.target.value));
                          set(k, { column: e.target.value,
                            op: FILTER_OPS[nextKind].includes(row.op) ? row.op : "=",
                            text: nextKind === colKind(column) ? row.text : "" });
                        }}>
                  <option value="" disabled>Choose column</option>
                  <optgroup label={table}>
                    {columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
                  </optgroup>
                </select>
                {row.column && <small className="join-col-type">{KIND_LABEL[kind]}</small>}
              </span>
              <select className="join-filter-op" aria-label={`${name} operator`} value={row.op}
                      disabled={disabled}
                      onChange={(e) => set(k, { op: e.target.value as JoinFilterOp })}>
                {ops.map((op) => <option key={op} value={op}>{OP_LABEL[op] ?? op}</option>)}
              </select>
              {NULL_OPS.includes(row.op) ? <span className="join-filter-value" />
                : kind === "bool" && !LIST_OPS.includes(row.op) ? (
                  <select className="join-filter-value" aria-label={`${name} value`} value={row.text}
                          disabled={disabled} onChange={(e) => set(k, { text: e.target.value })}>
                    <option value="" disabled>Choose…</option>
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                ) : (
                  <input type="text" className="join-filter-value" aria-label={`${name} value`} value={row.text}
                         disabled={disabled}
                         inputMode={kind === "number" && !LIST_OPS.includes(row.op) ? "decimal" : undefined}
                         title={LIST_OPS.includes(row.op) ? 'Separate values with commas; quote a value that contains a comma: "Smith, John"' : undefined}
                         placeholder={LIST_OPS.includes(row.op) ? "value, value, …"
                           : kind === "number" ? "number" : kind === "time" ? "2024-01-31" : "text"}
                         onChange={(e) => set(k, { text: e.target.value })} />
                )}
              <button className="quiet" aria-label={`Remove ${name}`} title="Remove filter"
                      onClick={() => onChange(rows.filter((_, m) => m !== k))}>✕</button>
            </div>
            {problem && <div className="join-check join-error" role="alert">{problem}</div>}
          </Fragment>
        );
      })}
      <div className="join-tools">
        <button className="link" disabled={disabled || hasBlank || rows.length >= 12}
                aria-label={`Add filter to ${label}`}
                title={`Keep only ${table} rows that match a value, before joining`}
                onClick={() => onChange([...rows, { column: "", op: "=", text: "" }])}>
          + filter
        </button>
        {rows.length === 0 && <span className="settings-hint">Keep only some {table} rows before joining</span>}
      </div>
    </div>
  );
}

/** One line in plain language for the selected join type. */
export function howHint(how: JoinHow, left: string, right: string): string {
  switch (how) {
    case "left": return `Keep all ${left} rows; add ${right} columns where they match.`;
    case "inner": return `Keep only rows where ${left} and ${right} match.`;
    case "right": return `Keep all ${right} rows; add ${left} columns where they match.`;
    case "full": return `Keep all rows from ${left} and ${right}, side by side where they match.`;
    case "semi": return `Keep ${left} rows that have a match in ${right}; adds no columns.`;
    case "anti": return `Keep ${left} rows with no match in ${right}; adds no columns.`;
  }
}
let stepSeq = 0;
const stepUid = () => `step-${++stepSeq}`;
type KeyRecommendation = JoinRecommendation & { sourceTitle: string };

export const aliasOf = (d?: Dataset) =>
  (d?.title ?? "joined").replace(/\.(parquet|csv|tsv|txt|json|ndjson)$/i, "");

export const addsColumns = (how: JoinHow) => how !== "semi" && how !== "anti";

export function Venn({ how }: { how: JoinHow }) {
  const a = { cx: 7, cy: 7, r: 5.5 }, b = { cx: 14, cy: 7, r: 5.5 };
  const id = `venn-${how}`;
  return (
    <svg className="venn" width="21" height="14" viewBox="0 0 21 14" aria-hidden>
      <defs>
        <clipPath id={`${id}-a`}><circle {...a} /></clipPath>
        <mask id={`${id}-not-b`}>
          <rect width="21" height="14" fill="white" /><circle {...b} fill="black" />
        </mask>
      </defs>
      {(how === "left" || how === "full") && <circle {...a} className="venn-fill" />}
      {(how === "right" || how === "full") && <circle {...b} className="venn-fill" />}
      {(how === "inner" || how === "semi") &&
        <circle {...b} className="venn-fill" clipPath={`url(#${id}-a)`} />}
      {how === "anti" && <circle {...a} className="venn-fill" mask={`url(#${id}-not-b)`} />}
      <circle {...a} className="venn-line" />
      <circle {...b} className={`venn-line${addsColumns(how) ? "" : " venn-dashed"}`} />
    </svg>
  );
}

function outputColumns(base: Dataset | undefined, steps: StepState[],
                       upTo: number, byId: Map<string, Dataset>): string[] {
  const cols = base ? base.columns.map((c) => c.name) : [];
  steps.slice(0, upTo).forEach((s) => {
    const right = byId.get(s.right_id);
    if (!right || !addsColumns(s.how)) return;
    const picked = s.columns ?? right.columns.map((c) => c.name);
    picked.forEach((c) => cols.push(`${s.alias}${ARROW}${c}`));
  });
  return cols;
}

/** Left-side columns grouped by the table they come from. */
function leftGroups(base: Dataset | undefined, steps: StepState[], upTo: number,
                    byId: Map<string, Dataset>): { key: string; label: string; cols: string[] }[] {
  const groups = [{ key: "base", label: base?.title ?? "base", cols: base ? base.columns.map((c) => c.name) : [] }];
  steps.slice(0, upTo).forEach((st) => {
    const right = byId.get(st.right_id);
    if (!right || !addsColumns(st.how)) return;
    const picked = st.columns ?? right.columns.map((c) => c.name);
    groups.push({ key: st.uid, label: st.alias || aliasOf(right),
                  cols: picked.map((c) => `${st.alias}${ARROW}${c}`) });
  });
  return groups;
}

function defaultCondition(leftCols: string[], right?: Dataset): JoinCondition {
  void leftCols;
  void right;
  return { left: "", op: "=", right: "" };
}

export const directAurora = (ref?: SourceRef) =>
  (ref?.kind === "aurora" || ref?.kind === "postgres") && "table" in ref;

export function sourceResources(ref?: SourceRef): string[] {
  if (!ref) return [];
  if (ref.kind === "join") return [
    ...sourceResources(ref.base), ...ref.steps.flatMap((step) => sourceResources(step.source)),
  ];
  if (ref.kind === "derived" || ref.kind === "group_summary") return sourceResources(ref.base);
  return [ref.resource_id];
}

export function JoinPanel({ datasets, sources, busy, onJoin, initialPlan,
                            onSourceOpened, onClose, onOpenCanvas }: Props) {
  const byId = useMemo(() => new Map(datasets.map((d) => [d.id, d])), [datasets]);
  const [baseId, setBaseId] = useState(initialPlan?.baseId ?? datasets[0]?.id ?? "");
  const base = byId.get(baseId);
  const [resourceKey, setResourceKey] = useState("");
  const [sourceTables, setSourceTables] = useState<TableInfo[]>([]);
  const [sourceSchema, setSourceSchema] = useState("");
  const [sourceTable, setSourceTable] = useState("");
  const [sourceBusy, setSourceBusy] = useState(false);
  const [sourceError, setSourceError] = useState("");
  const [copyStatus, setCopyStatus] = useState("");
  const [sourceMode, setSourceMode] = useState<"table" | "sql">("table");
  const [sqlName, setSqlName] = useState("");
  const [sqlText, setSqlText] = useState("");
  const [sqlPreview, setSqlPreview] = useState<Awaited<ReturnType<typeof api.previewSql>> | null>(null);
  const [sqlBusy, setSqlBusy] = useState(false);
  const [sqlError, setSqlError] = useState("");
  const sqlRequest = useRef(0);
  const selectedSource = sources.find((source) =>
    `${source.kind}:${source.id}` === resourceKey);

  const invalidateSqlPreview = () => {
    sqlRequest.current += 1;
    setSqlBusy(false);
    setSqlPreview(null);
    setSqlError("");
  };

  useEffect(() => {
    if (!resourceKey && sources.length) {
      const first = sources[0];
      setResourceKey(`${first.kind}:${first.id}`);
    }
  }, [resourceKey, sources]);

  useEffect(() => {
    if (!selectedSource) { setSourceTables([]); setSourceTable(""); return; }
    let cancelled = false;
    setSourceTables([]);
    setSourceSchema("");
    setSourceTable("");
    setSourceError("");
    api.tables(selectedSource.kind, selectedSource.id).then((items) => {
      if (!cancelled) setSourceTables(items);
    }).catch((error) => {
      if (!cancelled) setSourceError((error as Error).message);
    });
    return () => { cancelled = true; };
  }, [resourceKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const attachOpenedSource = (opened: Awaited<ReturnType<typeof api.openSourceRef>>,
                              title: string, sourceRef: SourceRef, asBase = false) => {
    onSourceOpened(opened, title, sourceRef);
    if (!baseId || asBase) {
      setBaseId(opened.dataset_id);
      setBaseFilterRows([]);
      setSteps([{ uid: stepUid(), right_id: "", how: "left", alias: "joined", columns: null,
        touched: false, pickCols: false, filterRows: [],
        conditions: [{ left: "", op: "=", right: "" }] }]);
    } else {
      setSteps((previous) => {
        const add = (): StepState => ({
          right_id: opened.dataset_id, how: "left", alias: title, uid: stepUid(),
          columns: null, touched: false, pickCols: false, filterRows: [],
          conditions: [{ left: "", op: "=", right: "" }],
        });
        const emptyIndex = previous.findIndex((step) => !step.right_id);
        if (emptyIndex >= 0) return previous.map((step, i) =>
          i === emptyIndex ? add() : step);
        if (previous.length < MAX_STEPS) return [...previous, add()];
        return previous;
      });
    }
  };

  const addSourceTable = async (tableName = sourceTable, asBase = false) => {
    if (!selectedSource) return;
    if (!asBase && baseId && steps.every((step) => step.right_id) && steps.length >= MAX_STEPS) {
      setSourceError(`A join can include up to ${MAX_STEPS} additional tables.`);
      return;
    }
    const info = sourceTables.find((item) => item.name === tableName);
    if (!info) return;
    const sourceRef: SourceRef = {
      kind: selectedSource.kind, resource_id: selectedSource.id,
      ...(selectedSource.uuid ? { uuid: selectedSource.uuid } : {}),
      ...(info.schema ? { schema: info.schema } : {}),
      table: info.table ?? info.name,
    };
    setSourceBusy(true);
    setSourceError("");
    try {
      const opened = await api.openSourceRef(sourceRef);
      const duplicateCount = datasets.filter((dataset) => {
        const ref = dataset.sourceRef;
        return ref && "table" in ref && ref.kind === sourceRef.kind
          && ref.resource_id === sourceRef.resource_id
          && ref.schema === sourceRef.schema && ref.table === sourceRef.table;
      }).length;
      const title = duplicateCount ? `${info.name} (${duplicateCount + 1})` : info.name;
      attachOpenedSource(opened, title, sourceRef, asBase);
      setSourceTable("");
    } catch (error) {
      setSourceError((error as Error).message);
    } finally {
      setSourceBusy(false);
    }
  };

  const previewSql = async () => {
    if (selectedSource?.kind !== "aurora" && selectedSource?.kind !== "postgres") return;
    const requestId = ++sqlRequest.current;
    const resourceId = selectedSource.id;
    const query = sqlText.trim();
    setSqlBusy(true);
    setSqlError("");
    setSqlPreview(null);
    try {
      const result = await api.previewSql(resourceId, query);
      if (requestId === sqlRequest.current) {
        setSqlPreview(result);
      }
    } catch (error) {
      if (requestId === sqlRequest.current) setSqlError((error as Error).message);
    } finally {
      if (requestId === sqlRequest.current) setSqlBusy(false);
    }
  };

  const addSqlSource = async () => {
    if (!selectedSource || (selectedSource.kind !== "aurora" && selectedSource.kind !== "postgres")
        || !sqlText.trim() || sqlBusy || sourceBusy || busy) return;
    setSourceBusy(true);
    setSqlError("");
    try {
      const requestedName = sqlName.trim() || "SQL result";
      const duplicateCount = datasets.filter((dataset) => dataset.title === requestedName).length;
      const title = duplicateCount ? `${requestedName} (${duplicateCount + 1})` : requestedName;
      const sourceRef: SourceRef = { kind: "sql", resource_id: selectedSource.id, sql: sqlText.trim(), name: title };
      const opened = await api.openSourceRef(sourceRef);
      onSourceOpened(opened, title, opened.source_ref ?? sourceRef);
      setSqlPreview(null);
      onClose();
    } catch (error) {
      setSqlError((error as Error).message);
    } finally {
      setSourceBusy(false);
    }
  };

  const newStep = (rightId: string, prior: StepState[]): StepState => {
    const right = byId.get(rightId);
    const leftCols = outputColumns(base, prior, prior.length, byId);
    return { right_id: rightId, how: "left", alias: aliasOf(right), uid: stepUid(),
             columns: null, touched: false, pickCols: false, filterRows: [],
             conditions: [defaultCondition(leftCols, right)] };
  };

  const firstOther = (exclude: string) =>
    datasets.find((d) => d.id !== exclude)?.id ?? "";
  const [steps, setSteps] = useState<StepState[]>(() => initialPlan
    ? initialPlan.steps.map(({ filters, ...step }) => ({ ...step, touched: true, pickCols: false,
        uid: stepUid(), filterRows: (filters ?? []).map(fromFilter) }))
    : [newStep(firstOther(baseId), [])]);
  const [baseFilterRows, setBaseFilterRows] = useState<FilterRow[]>(
    () => (initialPlan?.baseFilters ?? []).map(fromFilter));
  const canAddSource = !baseId || steps.some((step) => !step.right_id)
    || steps.length < MAX_STEPS;
  const [suggestions, setSuggestions] = useState<Record<number, JoinSuggestion[]>>({});
  const [recommendations, setRecommendations] = useState<Record<number, KeyRecommendation[]>>({});
  const [recommendationWarnings, setRecommendationWarnings] = useState<string[]>([]);
  const [preview, setPreview] = useState<JoinPreview | null>(null);
  const [previewErr, setPreviewErr] = useState("");
  const [previewing, setPreviewing] = useState(false);
  const [previewJob, setPreviewJob] = useState<{ job: DataJob; receivedAt: number } | null>(null);
  const [runJob, setRunJob] = useState<{ job: DataJob; receivedAt: number } | null>(null);
  const [growthConfirmed, setGrowthConfirmed] = useState(false);
  useEffect(() => { setGrowthConfirmed(false); }, [preview]);
  const needsGrowthConfirm = Boolean(preview?.large_growth) && !growthConfirmed;
  const [cancelError, setCancelError] = useState("");
  useEffect(() => {
    // Full joins report through the same events as the Data operations card.
    const update = (event: Event) => {
      const { job } = (event as CustomEvent<{ id: string; job: DataJob | null }>).detail;
      if (job && job.kind !== "join") return;
      setRunJob(job && ["queued", "running", "cancelling"].includes(job.status)
        ? { job, receivedAt: Date.now() } : null);
    };
    window.addEventListener("studio-data-job", update);
    return () => window.removeEventListener("studio-data-job", update);
  }, []);
  const previewRequest = useRef(0);
  const previewAbort = useRef<AbortController | null>(null);
  useEffect(() => () => previewAbort.current?.abort(), []);
  const [allowLoaded, setAllowLoaded] = useState(initialPlan?.allowLoaded ?? false);

  const stepKey = steps.map((s) => s.right_id).join("|");
  const recommendationKey = steps.map((s) =>
    `${s.right_id}:${s.how}:${s.alias}:${s.columns?.join(",") ?? "*"}`).join("|");
  const commonKeys = base?.columns.map((c) => c.name).filter((name) =>
    steps.length > 0 && steps.every((s) =>
      byId.get(s.right_id)?.columns.some((c) => c.name === name))) ?? [];
  const [commonKey, setCommonKey] = useState("");
  const selectedInputs = [base, ...steps.map((step) => byId.get(step.right_id))]
    .filter((dataset): dataset is Dataset => Boolean(dataset));
  const resources = new Set(selectedInputs.flatMap((dataset) => sourceResources(dataset.sourceRef)));
  const hasUnbackedLoaded = selectedInputs.some((dataset) =>
    dataset.queryScope === "loaded" && !dataset.sourceRef);
  const crossSource = resources.size > 1 || (resources.size > 0 && hasUnbackedLoaded);

  useEffect(() => {
    if (!commonKeys.includes(commonKey)) setCommonKey(commonKeys[0] ?? "");
  }, [stepKey, baseId, commonKeys.join("|")]);

  useEffect(() => {
    let cancelled = false;
    setSuggestions({});
    Promise.all(steps.map(async (s, i) => {
      if (!s.right_id) return [] as JoinSuggestion[];
      const lefts: { id: string; prefix: string }[] = [{ id: baseId, prefix: "" }];
      steps.slice(0, i).forEach((p) => {
        if (addsColumns(p.how)) lefts.push({ id: p.right_id, prefix: `${p.alias}${ARROW}` });
      });
      const recommendationPairs = lefts.filter((l) => {
        const leftDataset = byId.get(l.id);
        const rightDataset = byId.get(s.right_id);
        return l.id && l.id !== s.right_id
          && !(directAurora(leftDataset?.sourceRef) && directAurora(rightDataset?.sourceRef));
      });
      const all = await Promise.all(recommendationPairs.map((l) =>
        api.suggestJoin(l.id, s.right_id)
          .then((r) => r.map((x) => ({ ...x, left: l.prefix + x.left })))
          .catch(() => [] as JoinSuggestion[])));
      const leftCols = new Set(outputColumns(base, steps, i, byId));
      return all.flat().filter((x) => leftCols.has(x.left))
        .sort((a, b) => b.score - a.score).slice(0, 3);
    })).then((ranked) => {
      if (cancelled) return;
      setSuggestions(Object.fromEntries(ranked.map((items, i) => [i, items])));
    });
    return () => { cancelled = true; };
  }, [baseId, recommendationKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let cancelled = false;
    setRecommendations({});
    setRecommendationWarnings([]);
    const requests = steps.map(async (step, stepIndex) => {
      const right = byId.get(step.right_id);
      if (!directAurora(right?.sourceRef)) return { stepIndex, candidates: [], warnings: [] };
      const lefts: { dataset: Dataset; prefix: string }[] = [];
      if (base && directAurora(base.sourceRef)) lefts.push({ dataset: base, prefix: "" });
      steps.slice(0, stepIndex).forEach((prior) => {
        const dataset = byId.get(prior.right_id);
        if (addsColumns(prior.how) && dataset && directAurora(dataset.sourceRef))
          lefts.push({ dataset, prefix: `${prior.alias}${ARROW}` });
      });
      const results = await Promise.all(lefts.map(async (left) => {
        try {
          const result = await api.recommendJoin(left.dataset.sourceRef!, right?.sourceRef!);
          return {
            candidates: result.candidates.map((candidate) => ({
              ...candidate,
              keys: candidate.keys.map((key) => ({ ...key, left: left.prefix + key.left })),
              sourceTitle: left.dataset.title,
            })),
            warnings: result.warnings,
          };
        } catch { return { candidates: [], warnings: [] }; }
      }));
      const visibleLeftCols = new Set(outputColumns(base, steps, stepIndex, byId));
      const visibleRightCols = new Set(right?.columns.map((column) => column.name) ?? []);
      const methodOrder = { foreign_key: 0, exact_name: 1, jev: 2 };
      const candidates = results.flatMap((result) => result.candidates)
        .filter((candidate) => candidate.keys.length > 0 && candidate.keys.every((key) =>
          visibleLeftCols.has(key.left) && visibleRightCols.has(key.right)))
        .sort((a, b) => methodOrder[a.method] - methodOrder[b.method])
        .slice(0, 3);
      return { stepIndex, candidates,
        warnings: results.flatMap((result) => result.warnings) };
    });
    Promise.all(requests).then((results) => {
      if (cancelled) return;
      setRecommendations(Object.fromEntries(results.map((result) =>
        [result.stepIndex, result.candidates])));
      setRecommendationWarnings([...new Set(results.flatMap((result) => result.warnings))]);
    });
    return () => { cancelled = true; };
  }, [baseId, recommendationKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    previewRequest.current += 1;
    previewAbort.current?.abort();
    setPreview(null);
    setPreviewErr("");
    setPreviewing(false);
  }, [baseId, steps, baseFilterRows]);

  const [validation, setValidation] = useState<JoinValidation | null>(null);
  useEffect(() => {
    setValidation(null);
    setCopyStatus("");
    if (!base || steps.some((s) => !s.right_id)) { setValidation(null); return; }
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      api.validateJoin(baseId, payload(), ctrl.signal, crossSource && allowLoaded, baseFilters())
        .then(setValidation)
        .catch(() => { if (!ctrl.signal.aborted) setValidation(null); });
    }, VALIDATE_DELAY_MS);
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, [baseId, steps, baseFilterRows, crossSource, allowLoaded]); // eslint-disable-line react-hooks/exhaustive-deps

  const options = datasets.map((d) => ({ id: d.id, label: d.title, hint: d.source }));
  // "Start from" can also open a table straight from the selected datasource,
  // so a join can begin with nothing open.
  const SOURCE_PREFIX = "source-table:";
  const startOptions = [...options, ...(selectedSource
    ? sourceTables.filter((item) => !sourceSchema || (item.schema ?? "") === sourceSchema)
        .map((item) => ({ id: SOURCE_PREFIX + item.name, label: item.name,
          hint: [`open from ${selectedSource.label ?? selectedSource.id}`, tableStats(item)]
            .filter(Boolean).join(" · ") }))
    : [])];
  const chooseStart = (id: string) => {
    if (id.startsWith(SOURCE_PREFIX)) void addSourceTable(id.slice(SOURCE_PREFIX.length), true);
    else changeBase(id);
  };
  const schemas = [...new Set(sourceTables.map((item) => item.schema ?? ""))];
  const sourceGroups = [...new Set(sources.map((item) => item.kind))]
    .map((kind) => ({ kind, items: sources.filter((item) => item.kind === kind) }));
  const visibleSourceTables = sourceTables.filter((item) =>
    !sourceSchema || (item.schema ?? "") === sourceSchema);
  const engine = preview?.engine ?? validation?.engine;
  const isS3Source = selectedSource?.kind === "s3";
  const supportsSchema = ["aurora", "postgres", "athena"].includes(selectedSource?.kind ?? "");

  const update = (i: number, patch: Partial<StepState>) =>
    setSteps((prev) => {
      const old = prev[i];
      const others = prev.filter((_, j) => j !== i).map((st) => st.alias);
      // Rewrite only when the old alias belonged to this step alone and the new
      // one is not another step's: mid-typing collisions would otherwise
      // redirect another step's conditions to the wrong table.
      const renamed = patch.alias !== undefined && old && patch.alias !== old.alias
        && !others.includes(old.alias) && !others.includes(patch.alias);
      return prev.map((s, j) => {
        if (j === i) return { ...s, ...patch };
        if (!renamed || j < i) return s;
        // Keep later conditions pointing at this step's columns after a rename.
        const from = `${old.alias}${ARROW}`, to = `${patch.alias}${ARROW}`;
        return { ...s, conditions: s.conditions.map((c) =>
          c.left.startsWith(from) ? { ...c, left: to + c.left.slice(from.length) } : c) };
      });
    });

  /** Swapping adjacent steps a (upper) and b (lower) is safe unless b's
   * conditions use a's columns: b would then reference a later step. */
  const swapBreaks = (upper: number, lower: number) => {
    const a = steps[upper], b = steps[lower];
    if (!a || !b) return true;
    const prefix = `${a.alias}${ARROW}`;
    return b.conditions.some((c) => c.left.startsWith(prefix));
  };

  const move = (i: number, delta: -1 | 1) =>
    setSteps((prev) => {
      const j = i + delta;
      if (j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });

  const setCondition = (i: number, k: number, patch: Partial<JoinCondition>) =>
    setSteps((prev) => prev.map((s, j) => j !== i ? s : {
      ...s, touched: true,
      conditions: s.conditions.map((c, m) => (m === k ? { ...c, ...patch } : c)),
    }));

  const copySqlSource = async () => {
    const statement = validation?.generated_sql?.copyable_sql;
    if (!statement) return;
    try {
      await navigator.clipboard.writeText(statement);
      setCopyStatus("SQL source copied.");
    } catch {
      setCopyStatus("Clipboard access is unavailable.");
    }
  };

  const changeBase = (id: string) => {
    setBaseId(id);
    setBaseFilterRows([]);
    setSteps([newStep(firstOther(id), [])]);
    setSuggestions({});
  };

  const applyCommonKey = () => {
    if (!commonKey) return;
    setSteps((prev) => prev.map((s) => {
      const condition = { left: commonKey, op: "=" as const, right: commonKey };
      return { ...s, touched: true,
        conditions: s.conditions.length
          ? [condition, ...s.conditions.slice(1)] : [condition] };
    }));
  };

  const changeRight = (i: number, id: string) =>
    setSteps((prev) => prev.map((s, j) => (j === i ? newStep(id, prev.slice(0, i)) : s)));

  // Only complete condition rows and filter rows are sent; blank rows are
  // ignored and incomplete ones block the join (see disabledReason).
  const payload = (): JoinStep[] => steps.map(
    ({ right_id, how, conditions, columns, alias, filterRows }) => {
      const filters = sentFilters(filterRows, byId.get(right_id)?.columns ?? [])
        .map((item) => item.filter);
      return { right_id, how, columns, alias: alias.trim(),
        conditions: conditions.filter(isCompleteCond).map(({ left, op, right }) => ({ left, op, right })),
        ...(filters.length ? { filters } : {}) };
    });
  const baseFilters = (): JoinFilter[] =>
    sentFilters(baseFilterRows, base?.columns ?? []).map((item) => item.filter);

  const stepName = (i: number) => steps.length > 1 ? `Step ${i + 1}: ` : "";
  const disabledReason = ((): string | null => {
    if (!base) return "Choose a table to start from.";
    const pending = baseFilterRows.find((row) => filterProblem(row));
    if (pending) return `Start table: ${filterProblem(pending)}`;
    for (const [i, st] of steps.entries()) {
      const right = byId.get(st.right_id);
      if (!right) return `${stepName(i)}Choose a table to join.`;
      if (st.conditions.some((c) => !isBlankCond(c) && !isCompleteCond(c)))
        return `${stepName(i)}Finish or remove the incomplete condition.`;
      if (!st.conditions.some(isCompleteCond)) return `${stepName(i)}Choose at least one matching column pair.`;
      const filter = st.filterRows.find((row) => filterProblem(row));
      if (filter) return `${stepName(i)}${filterProblem(filter)}`;
    }
    if (validation?.ok === false) return "Fix the problems shown above.";
    return null;
  })();
  const valid = disabledReason === null;

  const runPreview = async () => {
    const controller = new AbortController();
    previewAbort.current = controller;
    const requestId = ++previewRequest.current;
    setPreviewing(true);
    setPreviewErr("");
    setPreviewJob(null);
    try {
      const result = await api.previewJoin(baseId, payload(), crossSource && allowLoaded, controller.signal,
        (job) => { if (requestId === previewRequest.current) setPreviewJob({ job, receivedAt: Date.now() }); },
        baseFilters());
      if (requestId === previewRequest.current) setPreview(result);
    } catch (e) {
      if (requestId === previewRequest.current) setPreviewErr((e as Error).message);
    } finally {
      if (previewAbort.current === controller) previewAbort.current = null;
      if (requestId === previewRequest.current) { setPreviewing(false); setPreviewJob(null); }
    }
  };

  const changeAllowLoaded = (value: boolean) => {
    setAllowLoaded(value);
    previewRequest.current += 1;
    previewAbort.current?.abort();
    setPreview(null);
    setPreviewErr("");
    setPreviewing(false);
  };

  const reasonId = `join-reason-${baseId || "new"}`;
  const footerReason = disabledReason
    ?? (crossSource && !allowLoaded ? "Allow the full-source cross-source join below to continue." : null)
    ?? (needsGrowthConfirm ? "Confirm the large result to join." : null)
    ?? (busy || sourceBusy ? "Waiting for the current operation to finish." : null);
  const lastStat = preview?.large_growth ? undefined : preview?.steps[preview.steps.length - 1];
  const resultRows = lastStat ? `Result: ${lastStat.estimated ? "~" : ""}${lastStat.rows.toLocaleString()} rows`
    + (preview?.growth_total != null && preview.growth_total !== 1 ? ` (${preview.growth_total}× the base)` : "")
    : null;

  return (
    <div className="join-panel">
      <div className="join-row">
        {initialPlan && <strong>Edit {initialPlan.title}</strong>}
        {!initialPlan && sourceMode === "table" && <label>Start from
          <Combobox label="Start from" value={baseId} options={startOptions}
                    onChange={chooseStart}
                    placeholder={datasets.length ? "Choose a table…" : "Choose a table from the datasource below…"} />
        </label>}
        <div style={{ flex: 2 }} />
        {onOpenCanvas && !initialPlan && <button type="button" className="link join-open-canvas"
          title="Build the join by dragging tables onto a canvas" onClick={onOpenCanvas}>
          Open in Data Explorer
        </button>}
        <button className="quiet" onClick={onClose}>✕</button>
      </div>

      {sources.length > 0 && (
        <div className="join-source-picker">
          <strong>Add a source</strong>
          <div className="explore-toggle" role="group" aria-label="Source type">
            <button type="button" aria-pressed={sourceMode === "table"}
                    onClick={() => setSourceMode("table")}>Table</button>
            <button type="button" aria-pressed={sourceMode === "sql"}
                    disabled={selectedSource?.kind !== "aurora" && selectedSource?.kind !== "postgres"}
                    onClick={() => setSourceMode("sql")}>SQL</button>
          </div>
          <div className="join-row">
            <label>Datasource
              <select aria-label="Join datasource" value={resourceKey}
                      disabled={sourceBusy}
                      onChange={(e) => { invalidateSqlPreview(); setResourceKey(e.target.value);
                        if (!e.target.value.startsWith("aurora:") && !e.target.value.startsWith("postgres:")) setSourceMode("table"); }}>
                {sourceGroups.map(({ kind, items }) => (
                  <optgroup key={kind} label={SOURCE_GROUP_LABEL[kind]}>
                    {items.map((item) => (
                      <option key={`${item.kind}:${item.id}`} value={`${item.kind}:${item.id}`}>
                        {item.label}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
            {sourceMode === "table" && <>{supportsSchema && <label>Schema
              <select aria-label="Join schema" value={sourceSchema}
                      onChange={(e) => { setSourceSchema(e.target.value); setSourceTable(""); }}>
                <option value="">All schemas</option>
                {schemas.map((schema) => (
                  <option key={schema} value={schema}>{schema || "Default schema"}</option>
                ))}
              </select>
            </label>}
            <Combobox label={isS3Source ? "S3 file to add" : "Source table to add"} value={sourceTable}
                      options={visibleSourceTables.map((item) => ({
                        id: item.name, label: item.name, hint: [item.detail, tableStats(item)].filter(Boolean).join(" · "),
                      }))}
                      onChange={setSourceTable} placeholder={isS3Source ? "Search files…" : "Search tables…"} />
            <button className="primary" disabled={!sourceTable || sourceBusy || busy || !canAddSource}
                    onClick={() => void addSourceTable()}>
              {sourceBusy ? "Adding…" : isS3Source ? "Add file" : "Add table"}
            </button></>}
          </div>
          {sourceMode === "table" && sourceError && <div className="join-error" role="alert">{sourceError}</div>}
          {sourceMode === "sql" && <div>
            <div className="join-row">
              <label>SQL source name
                <input type="text" value={sqlName} maxLength={128} placeholder="e.g. visits" disabled={sourceBusy}
                       onChange={(event) => setSqlName(event.target.value)} />
              </label>
            </div>
            <div className="field-label">SQL query</div>
            <SqlEditor value={sqlText} disabled={sourceBusy} placeholder="SELECT … FROM schema.table"
                       resourceId={selectedSource && ["aurora", "postgres"].includes(selectedSource.kind) ? selectedSource.id : undefined}
                       onChange={(next) => { invalidateSqlPreview(); setSqlText(next); }} />
            <div className="join-row">
              <button className="primary" disabled={!selectedSource || !["aurora", "postgres"].includes(selectedSource.kind)
                || !sqlText.trim() || sqlBusy || sourceBusy || busy || !canAddSource}
                      onClick={previewSql}>
                {sqlBusy ? "Previewing…" : "Preview SQL"}
              </button>
              <button className="primary" disabled={!selectedSource
                || (selectedSource.kind !== "aurora" && selectedSource.kind !== "postgres")
                || !sqlText.trim() || sqlBusy || sourceBusy || busy}
                onClick={addSqlSource}>{sourceBusy ? "Creating…" : "Create dataset"}</button>
            </div>
            {sqlError && <div className="join-error" role="alert">{sqlError}</div>}
            {sqlPreview && <div className="join-sql-preview" aria-label="SQL preview">
              <p>{sqlPreview.rows} preview rows{sqlPreview.truncated ? " (more rows available)" : ""}</p>
              <table><thead><tr>{sqlPreview.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
                <tbody>{sqlPreview.sample.map((row, index) => <tr key={index}>
                  {sqlPreview.columns.map((column, cell) => {
                    const value = row[cell];
                    const display = value == null ? "NULL"
                      : typeof value === "object" ? JSON.stringify(value) : String(value);
                    return <td key={`${column}-${cell}`}>{display}</td>;
                  })}
                </tr>)}</tbody>
              </table>
            </div>}
          </div>}
        </div>
      )}

      {sourceMode === "table" && <>
      {steps.length > 1 && commonKeys.length > 0 && (
        <div className="join-row">
          <label>Common key
            <select value={commonKey} onChange={(e) => setCommonKey(e.target.value)}
                    disabled={!commonKeys.length}>
              {commonKeys.map((key) => <option key={key}>{key}</option>)}
            </select>
          </label>
          <button className="link" disabled={!commonKey} onClick={applyCommonKey}>
            Apply key to all
          </button>
        </div>
      )}

      {base && (
        <FilterEditor rows={baseFilterRows} columns={base.columns} table={base.title}
                      label="Start table" checks={validation?.base_filters}
                      disabled={sourceBusy || busy} onChange={setBaseFilterRows} />
      )}

      {steps.map((s, i) => {
        const right = byId.get(s.right_id);
        const leftCols = outputColumns(base, steps, i, byId);
        const groups = leftGroups(base, steps, i, byId);
        // After a reorder the chosen table may no longer be earlier: show all.
        const joinTo = groups.some((g) => g.key === s.joinTo) ? s.joinTo : undefined;
        const shown = joinTo ? groups.filter((g) => g.key === joinTo) : groups;
        const rightCols = right?.columns.map((c) => c.name) ?? [];
        const picked = s.columns ?? rightCols;
        const leftLabel = shown.length === 1 ? shown[0].label : "earlier tables";
        const rightLabel = right ? (s.alias.trim() || aliasOf(right)) : "the joined table";
        const howLeft = i === 0 ? (base?.title ?? "start table") : "the joined";
        const leftKind = (col: string) => {
          if (base?.columns.some((c) => c.name === col))
            return colKind(base.columns.find((c) => c.name === col));
          for (const prior of steps.slice(0, i)) {
            const prefix = `${prior.alias}${ARROW}`;
            if (col.startsWith(prefix))
              return colKind(byId.get(prior.right_id)?.columns.find((c) => c.name === col.slice(prefix.length)));
          }
          return undefined;
        };
        const rightKind = (col: string) => colKind(right?.columns.find((c) => c.name === col));
        const sentConds = s.conditions.map((c, k) => (isCompleteCond(c) ? k : -1)).filter((k) => k >= 0);
        const hasBlankCond = s.conditions.some(isBlankCond);
        const keyIdeas = (recommendations[i]?.length ?? 0) + (suggestions[i]?.length ?? 0);
        const stepProblems = (validation?.steps[i]?.problems ?? []).filter((p) =>
          !/add at least one join condition/i.test(p));
        return (
          <div className="join-step" key={s.uid}>
            <div className="join-step-head">
              <span className="join-step-no">{i + 1}</span>
              <div className="join-hows" role="radiogroup" aria-label="Join type">
                {HOWS.map((h) => (
                  <button key={h.id} title={h.hint} role="radio"
                          aria-checked={s.how === h.id}
                          className={`join-how${s.how === h.id ? " on" : ""}`}
                          onClick={() => update(i, { how: h.id })}>
                    <Venn how={h.id} />{h.label}
                  </button>
                ))}
              </div>
              {steps.length > 1 && (<>
                <button className="quiet" aria-label={`Move step ${i + 1} up`}
                        title={i > 0 && swapBreaks(i - 1, i)
                          ? `Uses columns from step ${i}; change that condition first` : "Move up"}
                        disabled={i === 0 || swapBreaks(i - 1, i)} onClick={() => move(i, -1)}>↑</button>
                <button className="quiet" aria-label={`Move step ${i + 1} down`}
                        title={i < steps.length - 1 && swapBreaks(i, i + 1)
                          ? `Step ${i + 2} uses this step's columns; change that condition first` : "Move down"}
                        disabled={i === steps.length - 1 || swapBreaks(i, i + 1)} onClick={() => move(i, 1)}>↓</button>
              </>)}
              {steps.length > 1 && (
                <button className="quiet" title="Remove this step" aria-label={`Remove step ${i + 1}`}
                        onClick={() => setSteps((prev) => prev.filter((_, j) => j !== i))}>✕</button>
              )}
            </div>
            <div className="join-how-hint settings-hint" aria-live="polite">
              {howHint(s.how, howLeft === "the joined" ? "the rows so far" : howLeft, rightLabel)}
            </div>

            <div className="join-row">
              <label>Table
                <Combobox label={`Table to join in step ${i + 1}`} value={s.right_id}
                          options={options.filter((o) => o.id !== baseId)}
                          onChange={(id) => changeRight(i, id)}
                          placeholder="Search open tables…" />
              </label>
              {groups.length > 1 && (
                <label>Join to
                  <select aria-label={`Join step ${i + 1} to`} value={joinTo ?? ""}
                          onChange={(e) => update(i, { joinTo: e.target.value || undefined })}>
                    <option value="">Any earlier table</option>
                    {groups.map((g) => <option key={g.key} value={g.key}>{g.label}</option>)}
                  </select>
                </label>
              )}
            </div>

            <div className="join-section" role="group" aria-label={`Step ${i + 1} matching columns`}>
              <div className="join-section-title">Match rows where</div>
              <div className="join-cond-head" aria-hidden>
                <span className="join-cond-label" />
                <span>{leftLabel} column</span>
                <span className="join-op-space" />
                <span>{rightLabel} column</span>
                <span className="join-remove-space" />
              </div>
              {s.conditions.map((c, k) => {
                const sentIndex = sentConds.indexOf(k);
                const check = sentIndex >= 0 ? validation?.steps[i]?.conditions[sentIndex] : undefined;
                const local = c.touched && !isBlankCond(c) && !isCompleteCond(c)
                  ? (!c.left ? `Pick a column from ${leftLabel}.` : `Pick a column from ${rightLabel}.`)
                  : null;
                const problem = local ?? check?.problem;
                const lk = c.left ? leftKind(c.left) : undefined;
                return (
                  <Fragment key={k}>
                    <div className={`join-cond${problem ? " invalid" : ""}`}
                         onBlur={(e) => {
                           if (leftRow(e) && !c.touched && !isBlankCond(c))
                             setSteps((prev) => prev.map((st, j) => j !== i ? st : {
                               ...st, conditions: st.conditions.map((x, m) => m === k ? { ...x, touched: true } : x),
                             }));
                         }}>
                      <span className="join-cond-label">{k === 0 ? "on" : "and"}</span>
                      <span className="join-pick">
                        <select disabled={sourceBusy || busy} aria-label={`Left key step ${i + 1} condition ${k + 1}`}
                                title={`${leftLabel} column`}
                                value={c.left} onChange={(e) => setCondition(i, k, { left: e.target.value })}>
                          <option value="" disabled>Choose column</option>
                          {c.left && !shown.some((g) => g.cols.includes(c.left)) && <option>{c.left}</option>}
                          {shown.map((g) => (
                            <optgroup key={g.key} label={g.label}>
                              {g.cols.map((col) => <option key={col}>{col}</option>)}
                            </optgroup>
                          ))}
                        </select>
                        {lk && <small className="join-col-type">{KIND_LABEL[lk]}</small>}
                      </span>
                      <select className="join-op" aria-label={`Operator step ${i + 1} condition ${k + 1}`}
                              value={c.op}
                              onChange={(e) => setCondition(i, k, { op: e.target.value as JoinOp })}>
                        {OPS.map((o) => <option key={o}>{o}</option>)}
                      </select>
                      <span className="join-pick">
                        <select disabled={sourceBusy || busy} aria-label={`Right key step ${i + 1} condition ${k + 1}`}
                                title={`${rightLabel} column`}
                                value={c.right} onChange={(e) => setCondition(i, k, { right: e.target.value })}>
                          <option value="" disabled>Choose column</option>
                          <optgroup label={rightLabel}>
                            {rightCols.map((col) => <option key={col}>{col}</option>)}
                          </optgroup>
                        </select>
                        {c.right && <small className="join-col-type">{KIND_LABEL[rightKind(c.right)]}</small>}
                      </span>
                      {s.conditions.length > 1 ? (
                        <button className="quiet" title="Remove condition"
                                aria-label={`Remove step ${i + 1} condition ${k + 1}`}
                                onClick={() => update(i, { touched: true,
                                  conditions: s.conditions.filter((_, m) => m !== k) })}>✕</button>
                      ) : <span className="join-remove-space" />}
                    </div>
                    {problem && <div className="join-check join-error" role="alert">{problem}</div>}
                    {!local && check?.note && <div className="join-check settings-hint">{check.note}</div>}
                  </Fragment>
                );
              })}
              {stepProblems.map((p) =>
                <div key={p} className="join-check join-error" role="alert">{p}</div>)}
              <div className="join-tools">
                <button className="link" disabled={hasBlankCond || s.conditions.length >= 12}
                        title={hasBlankCond ? "Fill in the empty condition first" : "Match on another column pair"}
                        onClick={() => update(i, { touched: true,
                          conditions: [...s.conditions, defaultCondition(leftCols, right)] })}>
                  + condition
                </button>
                {keyIdeas > 0 && <span className="settings-hint">Suggested keys:</span>}
                {(recommendations[i] ?? []).map((candidate, candidateIndex) => (
                  <Fragment key={`${candidate.method}-${candidateIndex}`}>
                    <button className="chip"
                            onClick={() => update(i, { touched: true,
                              conditions: candidate.keys.map((key) => ({
                                left: key.left, op: "=" as const, right: key.right,
                              })) })}>
                      Apply {candidate.sourceTitle}: {candidate.keys.map((key) =>
                        `${key.left} = ${key.right}`).join(" AND ")}
                      {` · ${candidate.method === "foreign_key" ? "foreign key"
                        : candidate.method === "exact_name" ? "matching names" : "Jev suggestion"}`}
                      {candidate.method === "jev" && candidate.confidence != null
                        ? ` · ${Math.round(candidate.confidence * 100)}% confidence` : ""}
                    </button>
                    {candidate.evidence.length > 0 && (
                      <details className="join-evidence">
                        <summary>Evidence</summary>
                        {candidate.evidence.join("; ")}
                      </details>
                    )}
                  </Fragment>
                ))}
                {(suggestions[i] ?? []).map((sg) => (
                  <button key={`${sg.left}|${sg.right}`} className="chip"
                          title={`${Math.round(sg.overlap * 100)}% of left values found`}
                          onClick={() => update(i, { touched: true,
                            conditions: [{ left: sg.left, op: "=", right: sg.right }] })}>
                    {sg.left} = {sg.right} · {Math.round(sg.overlap * 100)}%
                  </button>
                ))}
              </div>
            </div>

            {right && (
              <FilterEditor rows={s.filterRows} columns={right.columns} table={rightLabel}
                            label={`Step ${i + 1}`} checks={validation?.steps[i]?.filters}
                            disabled={sourceBusy || busy}
                            onChange={(rows) => update(i, { filterRows: rows })} />
            )}

            <details className="join-advanced">
              <summary>Advanced</summary>
              {addsColumns(s.how) ? (<>
                <div className="join-row">
                  <label className="join-alias">Name joined columns as
                    <input type="text" value={s.alias} onChange={(e) => update(i, { alias: e.target.value })}
                           placeholder={aliasOf(right)} />
                  </label>
                </div>
                <div className="join-row">
                  <button className="link" aria-expanded={s.pickCols}
                          onClick={() => update(i, { pickCols: !s.pickCols })}>
                    Columns to add: {picked.length === rightCols.length ? "all" : `${picked.length}/${rightCols.length}`} ▾
                  </button>
                </div>
                {s.pickCols && (
                  <div className="join-cols">
                    <button className="link" onClick={() => update(i, { columns: null })}>all</button>
                    <button className="link" onClick={() => update(i, { columns: [] })}>none</button>
                    {rightCols.map((col) => (
                      <label key={col} className="join-col">
                        <input type="checkbox" checked={picked.includes(col)}
                               onChange={(e) => update(i, { columns: e.target.checked
                                 ? rightCols.filter((x) => x === col || picked.includes(x))
                                 : picked.filter((x) => x !== col) })} />
                        {col}
                      </label>
                    ))}
                  </div>
                )}
              </>) : <div className="settings-hint">This join type adds no columns.</div>}
            </details>
          </div>
        );
      })}

      {recommendationWarnings.length > 0 && (
        <details className="join-evidence">
          <summary>Recommendation details</summary>
          {[...new Set(recommendationWarnings)].map((warning) => (
            <div key={warning}>{warning}</div>
          ))}
        </details>
      )}

      <div className="join-row">
        {steps.length < MAX_STEPS && datasets.length >= 2 && (
          <button className="link"
                  onClick={() => setSteps((prev) => [...prev, newStep(firstOther(baseId), prev)])}>
            + add another table
          </button>
        )}
        <div style={{ flex: 1 }} />
        {engine && (
          <span className={`join-engine ${engine}`}
                title={validation?.engine_reason ?? ""}>{ENGINE_LABEL[engine]}</span>
        )}
        <span className="join-disabled-reason" id={reasonId} aria-live="polite">{footerReason ?? ""}</span>
        {resultRows && <span className={`join-result-rows${preview?.large_growth ? " join-warn" : ""}`}>
          {resultRows}</span>}
        <button className="quiet" disabled={!valid || previewing || sourceBusy || busy
          || (crossSource && !allowLoaded)} onClick={runPreview}
                aria-describedby={footerReason ? reasonId : undefined}>
          {previewing ? "Previewing…" : "Preview"}
        </button>
        {previewing && <button type="button" onClick={() => { previewRequest.current += 1; previewAbort.current?.abort(); setPreviewing(false); setPreview(null); setPreviewErr("Preview cancelled."); }}>Cancel preview</button>}
        {crossSource && previewing && <span>Cancel interrupts active database and DuckDB work.</span>}
        {previewing && previewJob && (
          <div className="join-preview-progress" role="status" aria-label="Preview progress">
            <JobProgress job={previewJob.job} receivedAt={previewJob.receivedAt} />
          </div>
        )}
        {preview?.large_growth && (
          <label className="join-growth-confirm">
            <input type="checkbox" checked={growthConfirmed}
                   onChange={(e) => setGrowthConfirmed(e.target.checked)} />
            Run anyway: {preview.steps.some((st) => st.estimated) ? "~" : ""}
            {preview.steps[preview.steps.length - 1]?.rows.toLocaleString()} rows
            ({preview.growth_total}× the base)
          </label>
        )}
        <button className="primary" disabled={!valid || busy || sourceBusy || needsGrowthConfirm
          || (crossSource && !allowLoaded)} aria-describedby={footerReason ? reasonId : undefined}
                onClick={() => onJoin({ baseId, steps: payload(), allowLoaded: crossSource && allowLoaded,
                                        baseFilters: baseFilters() })}>
          {busy ? "Joining…" : initialPlan ? "Create edited join in new tab" : "Join into new tab"}
        </button>
      </div>
      {busy && runJob && (
        <div className="join-run-progress" role="status" aria-label="Join progress">
          <JobProgress job={runJob.job} receivedAt={runJob.receivedAt}
            onCancel={async () => {
              setCancelError("");
              try {
                const response = await fetch(`/api/data-jobs/${runJob.job.job_id}/cancel`, { method: "POST" });
                if (!response.ok) throw new Error("Could not cancel. Try again.");
              } catch (e) { setCancelError((e as Error).message); }
            }} />
          <p className="join-run-hint">You can switch tabs; the join keeps running and the result opens in a new tab.</p>
          {cancelError && <p role="alert">{cancelError}</p>}
        </div>
      )}

      {crossSource && <div className="settings-hint join-warn">
        <label><input type="checkbox" checked={allowLoaded} disabled={busy || previewing}
          onChange={(event) => changeAllowLoaded(event.target.checked)} />
          Allow full-source cross-source join
        </label>
        <div>{allowLoaded
          ? "Studio will scan each complete source and stage the join on disk. The operation stops above 1 TB."
          : "Cross-source joins require your approval to scan complete sources."}</div>
      </div>}

      {(validation?.problems ?? []).map((p) =>
        <div key={p} className="settings-hint join-error">{p}</div>)}
      {validation?.generated_sql && <details className="join-evidence">
        <summary>Generated SQL</summary>
        <div className="settings-hint">Engine: {validation.generated_sql.engine === "aurora" ? "Aurora" : "DuckDB"}</div>
        {validation.generated_sql.staged_inputs?.length ? <div className="settings-hint">
          Staged inputs: {validation.generated_sql.staged_inputs.join(", ")}
        </div> : null}
        <pre aria-label="Generated SQL" className="generated-sql-code">{validation.generated_sql.display_sql ?? validation.generated_sql.copyable_sql ?? validation.generated_sql.sql}</pre>
        {validation.generated_sql.copyable_sql && <div className="join-row">
          <button type="button" className="quiet" onClick={() => void copySqlSource()}>
            Copy SQL source
          </button>
          {copyStatus && <span role="status">{copyStatus}</span>}
        </div>}
        {!validation.generated_sql.copyable_sql && validation.generated_sql.copyable_sql_error
          && <div className="settings-hint" role="status">
            {validation.generated_sql.copyable_sql_error}
          </div>}
        {Object.keys(validation.generated_sql.parameters).length > 0 && <details>
          <summary>Parameters</summary>
          <pre aria-label="SQL parameters" className="generated-sql-code">{JSON.stringify(validation.generated_sql.parameters, null, 2)}</pre>
        </details>}
      </details>}
      {!preview && (validation?.capped_inputs.length ?? 0) > 0 && (
        <div className="settings-hint join-warn join-capped">
          Runs in memory on the loaded rows of {validation!.capped_inputs.join(", ")},
          which hit the row cap — results may be incomplete.
        </div>
      )}
      {previewErr && <div className="settings-hint join-error">{previewErr}</div>}
      {preview && (
        <div className="join-preview">
          <div className="join-funnel">
            <span>{preview.sample_only
              ? (preview.base_rows != null && preview.steps.some((st) => st.estimated)
                ? `~${preview.base_rows.toLocaleString()} rows (estimated)`
                : "Sample preview · full counts not calculated")
              : `${preview.base_rows?.toLocaleString() ?? "Unknown"} rows`}</span>
            {preview.steps.map((st, i) => (
              <span key={i}>→ {HOWS.find((h) => h.id === steps[i]?.how)?.label.toLowerCase()}{" "}
                {steps[i]?.alias || aliasOf(byId.get(steps[i]?.right_id ?? ""))}:{" "}
                <strong>{st.estimated ? "~" : ""}{st.rows.toLocaleString()}</strong>
                {st.fanout && (
                  <span className="join-warn join-fanout"
                        title="Rows multiplied: the join key repeats on the joined side.">
                    {" "}×{st.growth} fan-out
                  </span>
                )}</span>
            ))}
            {preview.truncated && preview.rows !== null && <span className="join-warn">capped at {preview.rows.toLocaleString()} rows</span>}
          </div>
          {preview.notes.map((n) => <div key={n} className="settings-hint">{n}</div>)}
          <div className="join-sample">
            <table>
              <thead><tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>
                {preview.sample.map((row, r) => (
                  <tr key={r}>{row.map((v, c) => <td key={c}>{v == null ? "—" : String(v)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      </>}
    </div>
  );
}
