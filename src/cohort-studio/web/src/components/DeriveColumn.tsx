import { useState } from "react";
import { api } from "../api";
import type { Dataset, Parameter } from "../types";

interface Props {
  dataset: Dataset;
  onUpdate: (changes: Partial<Dataset>) => void;
  onClose: () => void;
}

type Op = "bin" | "formula" | "expression" | "map";

/** Short reference shown with the expression box. */
const FUNCTION_HELP: [string, string][] = [
  ["+ - * /", "arithmetic (dividing by 0 gives empty)"],
  ["= != < <= > >=", "comparisons; text uses only = and !="],
  ["AND, OR, NOT", "combine conditions"],
  ["x IS NULL, x IS NOT NULL", "test for missing values"],
  ["IF(condition, then, else)", "one condition"],
  ["CASE WHEN … THEN … ELSE … END", "several conditions, first match wins"],
  ["COALESCE(a, b, …)", "first value that is not empty"],
  ["DATEDIFF(unit, start, end)", "whole days, weeks, months or years"],
  ["AGE_AT(birth_date, index_date)", "age in whole years"],
  ["DATE_TRUNC(unit, date)", "start of the date's week, month or year"],
  ["YEAR(date), MONTH(date), TODAY()", "date parts and today's date"],
  ["DATE '2024-01-01', 'text', 42, TRUE", "values"],
  ["@name", "a parameter of this tab"],
  ["abs, sqrt, ln", "number functions"],
  ['col("any name")', "a column whose name has spaces or symbols"],
];

const EXAMPLES: { label: string; name: string; expression: string }[] = [
  { label: "Age at index", name: "age_at_index", expression: "AGE_AT(birth_date, @index_date)" },
  { label: "Days of follow-up", name: "follow_up_days",
    expression: "DATEDIFF(day, index_date, COALESCE(end_date, TODAY()))" },
  { label: "Has diabetes", name: "has_diabetes",
    expression: "condition = 'Type 2 diabetes' OR hba1c >= 6.5" },
  { label: "30-day window", name: "in_window",
    expression: "visit_date >= @index_date AND DATEDIFF(day, @index_date, visit_date) <= 30" },
];

const QUOTED = /'(?:[^']|'')*'|"(?:[^"]|"")*"/g;
const PARAM_REF = /@([A-Za-z_][A-Za-z0-9_]*)/g;

/** The tab parameters an expression references, or the first unknown name. */
export function usedParameters(expression: string, parameters: Parameter[]):
    { used: Parameter[]; missing?: string } {
  const byName = new Map(parameters.map((p) => [p.name, p]));
  const used = new Map<string, Parameter>();
  for (const match of expression.replace(QUOTED, "''").matchAll(PARAM_REF)) {
    const parameter = byName.get(match[1]);
    if (!parameter) return { used: [...used.values()], missing: match[1] };
    used.set(parameter.name, { name: parameter.name, kind: parameter.kind, value: parameter.value });
  }
  return { used: [...used.values()] };
}

export function DeriveColumn({ dataset, onUpdate, onClose }: Props) {
  const numeric = dataset.columns
    .filter((c) => c.filter_kind === "range").map((c) => c.name);
  const categorical = dataset.columns
    .filter((c) => c.filter_kind === "categorical").map((c) => c.name);
  const parameters = dataset.parameters ?? [];

  const [op, setOp] = useState<Op>("bin");
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  const [binCol, setBinCol] = useState(numeric[0] ?? "");
  const [breaks, setBreaks] = useState("0, 18, 65, 120");
  const [labels, setLabels] = useState("");

  const [left, setLeft] = useState(numeric[0] ?? "");
  const [operator, setOperator] = useState("/");
  const [right, setRight] = useState(numeric[1] ?? numeric[0] ?? "");
  const [expression, setExpression] = useState("");

  const [mapCol, setMapCol] = useState(categorical[0] ?? "");
  const [mapText, setMapText] = useState("");
  const [mapDefault, setMapDefault] = useState("");

  const fail = (message: string) => { setFailed(true); setStatus(message); };

  const submit = async () => {
    if (!name.trim()) { fail("Name the new column."); return; }
    let spec: Record<string, unknown> = { op, name: name.trim() };
    if (op === "bin") {
      const b = breaks.split(",").map((s) => Number(s.trim()))
        .filter((n) => !Number.isNaN(n));
      const l = labels.trim()
        ? labels.split(",").map((s) => s.trim()) : undefined;
      spec = { ...spec, column: binCol, breaks: b, labels: l };
    } else if (op === "formula") {
      spec = { ...spec, left, operator, right };
    } else if (op === "expression") {
      const text = expression.trim();
      if (!text) { fail("Write an expression."); return; }
      // Parameters are resolved now; the spec keeps both the @name and its value.
      const { used, missing } = usedParameters(text, parameters);
      if (missing) { fail(`Unknown parameter @${missing}. Add it under Parameters first.`); return; }
      spec = { ...spec, expression: text, ...(used.length ? { parameters: used } : {}) };
    } else {
      const mapping: Record<string, string> = {};
      for (const line of mapText.split("\n")) {
        const [k, v] = line.split("=").map((s) => s.trim());
        if (k && v) mapping[k] = v;
      }
      spec = { ...spec, column: mapCol, mapping,
               default: mapDefault.trim() || undefined };
    }
    setBusy(true); setStatus(""); setFailed(false);
    try {
      const out = await api.derive(dataset.id, spec);
      onUpdate({ columns: out.columns, sourceRef: out.source_ref ?? undefined,
        queryScope: out.query_scope ?? "loaded",
        refreshNonce: (dataset.refreshNonce ?? 0) + 1, refreshing: true });
      setStatus(`Added "${out.name}".`);
      setName("");
    } catch (e) {
      fail(`Failed: ${(e as Error).message.replace(/Value error, /g, "")}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="derive-panel">
      <div className="derive-row">
        <label>Operation
          <select value={op} onChange={(e) => setOp(e.target.value as Op)}>
            <option value="bin">Bin a number into ranges</option>
            <option value="formula">Formula (column arithmetic)</option>
            <option value="expression">Expression (math, dates, conditions)</option>
            <option value="map">Map categorical values</option>
          </select>
        </label>
        <label>New column name
          <input type="text" value={name} placeholder="e.g. age_group"
                 onChange={(e) => setName(e.target.value)} />
        </label>
      </div>

      {op === "bin" && (
        <div className="derive-row">
          <label>Column
            <select value={binCol} onChange={(e) => setBinCol(e.target.value)}>
              {numeric.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label>Breaks (ascending, comma-sep)
            <input type="text" value={breaks}
                   onChange={(e) => setBreaks(e.target.value)} />
          </label>
          <label>Labels (optional, comma-sep)
            <input type="text" value={labels} placeholder="child, adult, senior"
                   onChange={(e) => setLabels(e.target.value)} />
          </label>
        </div>
      )}

      {op === "formula" && (
        <div className="derive-row">
          <label>Left
            <select value={left} onChange={(e) => setLeft(e.target.value)}>
              {numeric.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label>Op
            <select value={operator}
                    onChange={(e) => setOperator(e.target.value)}>
              {["+", "-", "*", "/"].map((o) => <option key={o}>{o}</option>)}
            </select>
          </label>
          <label>Right (column or number)
            <input type="text" value={right} list="numeric-cols"
                   onChange={(e) => setRight(e.target.value)} />
            <datalist id="numeric-cols">
              {numeric.map((c) => <option key={c} value={c} />)}
            </datalist>
          </label>
        </div>
      )}

      {op === "expression" && <>
        <div className="derive-row">
          <label>Expression
            <textarea aria-label="Calculation expression" rows={3} value={expression}
              placeholder="AGE_AT(birth_date, @index_date)"
              onChange={(event) => setExpression(event.target.value)} />
          </label>
        </div>
        <div className="derive-examples" role="group" aria-label="Expression examples">
          <span>Examples:</span>
          {EXAMPLES.map((example) => (
            <button key={example.label} type="button" className="link"
              title={example.expression}
              onClick={() => { setExpression(example.expression); if (!name.trim()) setName(example.name); }}>
              {example.label}
            </button>
          ))}
          <span className="derive-note">Replace the column names with yours.</span>
        </div>
        {parameters.length > 0 && <div className="derive-note">
          Parameters: {parameters.map((p, i) => <span key={p.name}>{i ? ", " : ""}
            <code>@{p.name} = {String(p.value)}</code></span>)}. Their values are used when the column is added.
        </div>}
        <details className="derive-help">
          <summary>Functions and syntax</summary>
          <dl>
            {FUNCTION_HELP.map(([syntax, meaning]) => (
              <div key={syntax}><dt><code>{syntax}</code></dt><dd>{meaning}</dd></div>
            ))}
          </dl>
          <p className="derive-note">Units are day, week, month or year. Months and years count
            whole units, like PostgreSQL age(). Text columns holding YYYY-MM-DD values work as
            dates; values that are not dates become empty. A condition makes a true/false
            column, a date result makes a date-filterable column.</p>
        </details>
      </>}

      {op === "map" && (
        <div className="derive-row">
          <label>Column
            <select value={mapCol} onChange={(e) => setMapCol(e.target.value)}>
              {categorical.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <label>Mapping (one <code>value = label</code> per line)
            <textarea rows={3} value={mapText}
                      placeholder={"liver = digestive\nlung = respiratory"}
                      onChange={(e) => setMapText(e.target.value)} />
          </label>
          <label>Unmapped →
            <input type="text" value={mapDefault} placeholder="(keep original)"
                   onChange={(e) => setMapDefault(e.target.value)} />
          </label>
        </div>
      )}

      <div className="derive-actions">
        <button className="primary" onClick={submit} disabled={busy}>
          {busy ? "Adding…" : "Add column"}
        </button>
        <button className="quiet" onClick={onClose}>✕</button>
        {status && <span className={failed ? "ask-note derive-error" : "ask-note"}
          role={failed ? "alert" : undefined}>{status}</span>}
      </div>
    </div>
  );
}
