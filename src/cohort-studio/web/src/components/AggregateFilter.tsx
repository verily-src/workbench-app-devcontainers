import { useRef, useState } from "react";
import { api } from "../api";
import type { Dataset } from "../types";

export function AggregateFilter({ dataset, onUpdate, onClose }: {
  dataset: Dataset; onUpdate: (changes: Partial<Dataset>) => void; onClose: () => void;
}) {
  const [group, setGroup] = useState(dataset.columns.find((c) => c.name === "person_id")?.name ?? dataset.columns[0]?.name ?? "");
  const [metric, setMetric] = useState<"count" | "sum" | "mean">("count");
  const [measure, setMeasure] = useState(dataset.columns[0]?.name ?? "");
  const [name, setName] = useState("Rows per group");
  const [minimum, setMinimum] = useState("2");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const currentFilters = useRef(dataset.filters);
  currentFilters.current = dataset.filters;
  const apply = async () => {
    const n = Number(minimum);
    if (!group || !name.trim() || minimum.trim() === "" || !Number.isFinite(n)
        || (metric === "count" && (!Number.isSafeInteger(n) || n < 1))
        || (metric !== "count" && !measure)) {
      setError("Choose a group, name, and valid minimum; row counts require a positive whole number."); return;
    }
    if (dataset.columns.some((column) => column.name === name.trim())) {
      setError("Choose a name that is not already a column."); return;
    }
    setBusy(true); setError("");
    try {
      const out = await api.derive(dataset.id, { op: `group_${metric}`, name: name.trim(), column: group,
        ...(metric === "count" ? {} : { measure }) });
      onUpdate({ columns: out.columns, sourceRef: out.source_ref ?? undefined,
        queryScope: out.query_scope ?? "loaded", filters: [...currentFilters.current,
          { column: out.name, kind: "range", min: n, max: Number.MAX_VALUE }],
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
      <label>Aggregate<select value={metric} onChange={(event) => {
        const selected = event.target.value as "count" | "sum" | "mean";
        setMetric(selected); setName(selected === "count" ? "Rows per group" : selected === "sum" ? "Sum per group" : "Mean per group");
        setMinimum(selected === "count" ? "2" : "0");
      }}><option value="count">Row count</option><option value="sum">Sum</option><option value="mean">Mean</option></select></label>
      {metric !== "count" && <label>Value column<select value={measure} onChange={(event) => setMeasure(event.target.value)}>
        {dataset.columns.map((column) => <option value={column.name} key={column.name}>{column.label || column.name}</option>)}
      </select></label>}
      <label>At least<input type="number" min={metric === "count" ? "1" : undefined} step={metric === "count" ? "1" : "any"} value={minimum}
        onChange={(event) => setMinimum(event.target.value)} /></label>
      <label>Filter name<input value={name} maxLength={60} onChange={(event) => setName(event.target.value)} /></label>
    </div>
    <p>Aggregates use {dataset.result?.sampled ? "the loaded sample" : dataset.queryScope === "database" ? "all source rows" : "all loaded rows"} before other filters. Rows without a group are excluded.{metric !== "count" ? " Non-numeric values are ignored." : ""}</p>
    {error && <p role="alert">{error}</p>}
    <button className="primary" disabled={busy} onClick={() => void apply()}>{busy ? "Creating…" : "Apply filter"}</button>
    <button className="quiet" disabled={busy} onClick={onClose}>Cancel</button>
  </section>;
}
