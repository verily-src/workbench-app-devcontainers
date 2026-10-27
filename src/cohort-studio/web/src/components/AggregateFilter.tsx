import { useRef, useState } from "react";
import { api } from "../api";
import type { Dataset } from "../types";

export function AggregateFilter({ dataset, onUpdate, onClose }: {
  dataset: Dataset; onUpdate: (changes: Partial<Dataset>) => void; onClose: () => void;
}) {
  const [group, setGroup] = useState(dataset.columns.find((c) => c.name === "person_id")?.name ?? dataset.columns[0]?.name ?? "");
  const [additionalGroups, setAdditionalGroups] = useState<string[]>([]);
  const [metric, setMetric] = useState<"count" | "sum" | "mean" | "min" | "max">("count");
  const [comparison, setComparison] = useState<"at_least" | "at_most" | "between">("at_least");
  const [measure, setMeasure] = useState(dataset.columns[0]?.name ?? "");
  const [name, setName] = useState("Rows per group");
  const [minimum, setMinimum] = useState("2");
  const [maximum, setMaximum] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const currentFilters = useRef(dataset.filters);
  currentFilters.current = dataset.filters;
  const apply = async () => {
    const n = Number(minimum);
    const upper = Number(maximum);
    const groups = [group, ...additionalGroups];
    if (!group || !name.trim() || minimum.trim() === "" || !Number.isFinite(n)
        || new Set(groups).size !== groups.length
        || (metric === "count" && (!Number.isSafeInteger(n) || n < 0))
        || (comparison === "between" && (maximum.trim() === "" || !Number.isFinite(upper) || upper < n
          || (metric === "count" && (!Number.isSafeInteger(upper) || upper < 0))))
        || (metric !== "count" && !measure)) {
      setError("Choose distinct groups, a name, and valid bounds. Row counts require nonnegative whole numbers."); return;
    }
    if (dataset.columns.some((column) => column.name === name.trim())) {
      setError("Choose a name that is not already a column."); return;
    }
    setBusy(true); setError("");
    try {
      const out = await api.derive(dataset.id, { op: `group_${metric}`, name: name.trim(), column: group,
        ...(additionalGroups.length ? { group_by: groups } : {}),
        ...(metric === "count" ? {} : { measure }) });
      onUpdate({ columns: out.columns, sourceRef: out.source_ref ?? undefined,
        queryScope: out.query_scope ?? "loaded", filters: [...currentFilters.current,
          { column: out.name, kind: "range", min: comparison === "at_most" ? -Number.MAX_VALUE : n,
            max: comparison === "at_most" ? n : comparison === "between" ? upper : Number.MAX_VALUE }],
        refreshNonce: (dataset.refreshNonce ?? 0) + 1, refreshing: true });
      onClose();
    } catch (caught) {
      setError(`Could not create aggregation filter: ${(caught as Error).message}`);
    } finally { setBusy(false); }
  };
  return <section className="derive-panel" aria-label="Aggregation filter">
    <div className="derive-row">
      <label>Group by<select value={group} onChange={(event) => setGroup(event.target.value)}>
        {dataset.columns.map((column) => <option value={column.name} key={column.name}>{column.label || column.name}</option>)}
      </select></label>
      {additionalGroups.map((value, index) => <label key={index}>Group {index + 2}
        <select value={value} onChange={event => setAdditionalGroups(previous => previous.map((item, i) => i === index ? event.target.value : item))}>
          {dataset.columns.map(column => <option value={column.name} key={column.name}>{column.label || column.name}</option>)}
        </select>
        <button type="button" className="quiet" onClick={() => setAdditionalGroups(previous => previous.filter((_, i) => i !== index))}>Remove group</button>
      </label>)}
      {additionalGroups.length < 4 && dataset.columns.length > additionalGroups.length + 1 && <button type="button" onClick={() => {
        const next = dataset.columns.find(column => ![group, ...additionalGroups].includes(column.name));
        if (next) setAdditionalGroups(previous => [...previous, next.name]);
      }}>Add group</button>}
      <label>Aggregate<select value={metric} onChange={(event) => {
        const selected = event.target.value as typeof metric;
        setMetric(selected); setName(({ count: "Rows", sum: "Sum", mean: "Mean", min: "Minimum", max: "Maximum" }[selected]) + " per group");
        setMinimum(selected === "count" ? "2" : "0");
      }}><option value="count">Row count</option><option value="sum">Sum</option><option value="mean">Mean</option><option value="min">Minimum</option><option value="max">Maximum</option></select></label>
      {metric !== "count" && <label>Value column<select value={measure} onChange={(event) => setMeasure(event.target.value)}>
        {dataset.columns.map((column) => <option value={column.name} key={column.name}>{column.label || column.name}</option>)}
      </select></label>}
      <label>Comparison<select value={comparison} onChange={event => setComparison(event.target.value as typeof comparison)}>
        <option value="at_least">At least</option><option value="at_most">At most</option><option value="between">Between</option>
      </select></label>
      <label>{comparison === "at_most" ? "At most" : comparison === "between" ? "Minimum" : "At least"}<input type="number" min={metric === "count" ? "0" : undefined} step={metric === "count" ? "1" : "any"} value={minimum}
        onChange={(event) => setMinimum(event.target.value)} /></label>
      {comparison === "between" && <label>Maximum<input type="number" min={metric === "count" ? "0" : undefined} step={metric === "count" ? "1" : "any"} value={maximum}
        onChange={event => setMaximum(event.target.value)} /></label>}
      <label>Filter name<input value={name} maxLength={60} onChange={(event) => setName(event.target.value)} /></label>
    </div>
    <p>Aggregates use {dataset.result?.sampled ? "the loaded sample" : dataset.queryScope === "database" ? "all source rows" : "all loaded rows"} before other filters. Rows without a group are excluded.{metric !== "count" ? " Non-numeric values are ignored." : ""}</p>
    {error && <p role="alert">{error}</p>}
    <button className="primary" disabled={busy} onClick={() => void apply()}>{busy ? "Creating…" : "Apply filter"}</button>
    <button className="quiet" disabled={busy} onClick={onClose}>Cancel</button>
  </section>;
}
