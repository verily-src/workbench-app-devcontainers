/** Shared join building blocks for Data Builder: join types, filter rows and
 *  their editor, Venn icons, and source helpers. */
import { Fragment } from "react";
import type {
  ColumnProfile, Dataset, JoinFilter, JoinFilterOp, JoinFilterValue, JoinHow, SourceRef,
} from "../types";

export const HOWS: { id: JoinHow; label: string; hint: string }[] = [
  { id: "left", label: "Left", hint: "Keep every row on the left; add matches" },
  { id: "inner", label: "Inner", hint: "Only rows that match on both sides" },
  { id: "right", label: "Right", hint: "Keep every row of the joined table" },
  { id: "full", label: "Full", hint: "Keep every row from both sides" },
  { id: "semi", label: "Has match", hint: "Left rows with a match; adds no columns" },
  { id: "anti", label: "No match", hint: "Left rows without a match; adds no columns" },
];
export const ARROW = " → ";

/** A condition row in the editor; `touched` once focus has left the row. */

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


/** Left-side columns grouped by the table they come from. */


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

