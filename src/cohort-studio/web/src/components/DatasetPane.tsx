import { api } from "../api";
import type { ChartSpec, Dataset, Filter } from "../types";
import { ChartCard } from "./ChartCard";

interface Props {
  dataset: Dataset;
  onUpdate: (changes: Partial<Dataset>) => void;
}

function describeFilter(f: Filter): string {
  if (f.kind === "categorical") {
    return (f.values ?? []).map((v) => `${f.column}: ${v}`).join("|");
  }
  return `${f.column}: ${f.min}–${f.max}`;
}

export function DatasetPane({ dataset, onUpdate }: Props) {
  const { result, filters, charts } = dataset;

  const toggleCategory = (column: string, value: string) => {
    const existing = filters.find((f) => f.column === column);
    const current = existing?.values ?? [];
    const values = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    const rest = filters.filter((f) => f.column !== column);
    onUpdate({
      filters: values.length
        ? [...rest, { column, kind: "categorical", values }] : rest,
    });
  };

  const chips: { label: string; remove: () => void }[] = [];
  for (const f of filters) {
    if (f.kind === "categorical") {
      for (const v of f.values ?? []) {
        chips.push({
          label: `${f.column}: ${v}`,
          remove: () => toggleCategory(f.column, v),
        });
      }
    } else {
      chips.push({
        label: describeFilter(f),
        remove: () => onUpdate({
          filters: filters.filter((o) => o.column !== f.column) }),
      });
    }
  }

  const updateChart = (index: number, changes: Partial<ChartSpec> | null) => {
    const next = charts.flatMap((c, i) => {
      if (i !== index) return [c];
      return changes ? [{ ...c, ...changes }] : [];
    });
    onUpdate({ charts: next });
  };

  const pageCount = result
    ? Math.max(1, Math.ceil(result.filtered / result.rows.page_size)) : 1;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center" }}>
        <div className="hero">
          <span className="count">
            {result ? result.filtered.toLocaleString() : "…"}
          </span>
          <span className="detail">
            of {result?.total.toLocaleString() ?? "…"} rows
            · {dataset.source}
          </span>
        </div>
        <div style={{ flex: 1 }} />
        <button onClick={() => api.export(dataset.id, filters)}>
          Export TSV
        </button>
      </div>

      {chips.length > 0 && (
        <div className="chips">
          {chips.map((chip) => (
            <span key={chip.label} className="chip" onClick={chip.remove}>
              {chip.label} ✕
            </span>
          ))}
          <span className="chip clear" onClick={() => onUpdate({ filters: [] })}>
            Clear all
          </span>
        </div>
      )}

      <AddChart dataset={dataset} onUpdate={onUpdate} />

      <div className="chart-grid">
        {charts.map((spec, i) => (
          <ChartCard
            key={`${spec.kind}-${spec.x}-${spec.y ?? ""}-${i}`}
            spec={spec}
            result={result?.charts[i]}
            onTapCategory={toggleCategory}
            onToggleWide={() => updateChart(i, { wide: !spec.wide })}
            onClose={() => updateChart(i, null)}
          />
        ))}
      </div>

      {result && (
        <>
          <div className="section-label">Rows</div>
          <table className="data-table">
            <thead>
              <tr>
                {result.rows.columns.map((c) => <th key={c}>{c}</th>)}
              </tr>
            </thead>
            <tbody>
              {result.rows.data.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td key={j}>{cell === null ? "–" : String(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pager">
            <button disabled={dataset.page === 0}
                    onClick={() => onUpdate({ page: dataset.page - 1 })}>
              Prev
            </button>
            <span>page {dataset.page + 1} / {pageCount}</span>
            <button disabled={dataset.page + 1 >= pageCount}
                    onClick={() => onUpdate({ page: dataset.page + 1 })}>
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function AddChart({ dataset, onUpdate }: Props) {
  const numeric = dataset.columns
    .filter((c) => c.filter_kind === "range").map((c) => c.name);
  const all = dataset.columns.map((c) => c.name);

  const submit = (form: HTMLFormElement) => {
    const data = new FormData(form);
    const kind = data.get("kind") as ChartSpec["kind"] | "auto";
    const x = data.get("x") as string;
    const y = (data.get("y") as string) || undefined;
    if (!x) return;
    const col = dataset.columns.find((c) => c.name === x);
    const resolved: ChartSpec["kind"] = kind === "auto"
      ? (col?.filter_kind === "range" ? "histogram" : "bar") : kind;
    const spec: ChartSpec = { kind: resolved, x, y,
      wide: resolved === "scatter" || resolved === "heatmap" };
    onUpdate({ charts: [...dataset.charts, spec] });
    form.reset();
  };

  return (
    <form
      style={{ display: "flex", gap: 8, alignItems: "end", margin: "10px 0" }}
      onSubmit={(e) => { e.preventDefault(); submit(e.currentTarget); }}
    >
      <div style={{ width: 220 }}>
        <div className="field-label">Add chart</div>
        <select name="x" defaultValue="">
          <option value="" disabled>Choose a column…</option>
          {all.map((c) => <option key={c}>{c}</option>)}
        </select>
      </div>
      <div style={{ width: 120 }}>
        <div className="field-label">Type</div>
        <select name="kind" defaultValue="auto">
          {["auto", "bar", "histogram", "scatter", "heatmap"].map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
      </div>
      <div style={{ width: 160 }}>
        <div className="field-label">Second field</div>
        <select name="y" defaultValue="">
          <option value="">—</option>
          {numeric.map((c) => <option key={c}>{c}</option>)}
        </select>
      </div>
      <button className="primary" type="submit">Add</button>
    </form>
  );
}
