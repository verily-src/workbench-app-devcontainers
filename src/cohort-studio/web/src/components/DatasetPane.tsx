import { useEffect, useState } from "react";
import { api } from "../api";
import type { ChartSpec, Dataset, Filter, Source } from "../types";
import { ChartCard } from "./ChartCard";
import { ChatWidget } from "./ChatWidget";
import { ComparePanel } from "./ComparePanel";
import { captureCharts, exportDatasetPdf } from "../pdf";

interface Props {
  dataset: Dataset;
  palette: string;
  onUpdate: (changes: Partial<Dataset>) => void;
}

function describeFilter(f: Filter): string {
  if (f.kind === "categorical") {
    return (f.values ?? []).map((v) => `${f.column}: ${v}`).join("|");
  }
  return `${f.column}: ${f.min}–${f.max}`;
}

export function DatasetPane({ dataset, palette, onUpdate }: Props) {
  const { result, filters, charts } = dataset;
  const cohorts = dataset.cohorts ?? [];
  const [showCompare, setShowCompare] = useState(false);
  const [cohortName, setCohortName] = useState("");

  const saveCohort = () => {
    const name = cohortName.trim();
    if (!name || filters.length === 0) return;
    const rest = cohorts.filter((c) => c.name !== name);
    onUpdate({ cohorts: [...rest, { name, filters }] });
    setCohortName("");
  };
  const removeCohort = (name: string) =>
    onUpdate({ cohorts: cohorts.filter((c) => c.name !== name) });

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

  // A column is numeric when its server-inferred filter is a range.
  // Histogram and scatter need numeric columns; offering them on a
  // categorical field would coerce to empty (and used to 500 the query).
  const isNumeric = (name: string) =>
    dataset.columns.find((c) => c.name === name)?.filter_kind === "range";
  const allowedKinds = (spec: ChartSpec): ChartSpec["kind"][] => {
    let base: ChartSpec["kind"][];
    if (spec.y) {
      base = isNumeric(spec.x) && isNumeric(spec.y)
        ? ["scatter", "heatmap"] : ["heatmap"];
    } else {
      base = isNumeric(spec.x) ? ["bar", "histogram"] : ["bar"];
    }
    // Always keep the current kind selectable, even if a stale saved
    // view carries one that no longer matches the column types.
    return base.includes(spec.kind) ? base : [spec.kind, ...base];
  };

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
        <SaveToAurora dataset={dataset} />
        <button onClick={() => api.export(dataset.id, filters)}>
          Export TSV
        </button>
        <button onClick={() => exportDatasetPdf(dataset, captureCharts())}
                disabled={!result}>
          Export PDF
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

      <div className="cohort-bar">
        <span className="cohort-label">Cohorts</span>
        {cohorts.map((c) => (
          <span key={c.name} className="cohort-chip"
                title={`${c.filters.length} filter(s) — click ✕ to remove`}>
            {c.name}
            <button className="quiet" onClick={() => removeCohort(c.name)}>
              ✕
            </button>
          </span>
        ))}
        <input type="text" className="cohort-name"
               placeholder={filters.length
                 ? "name current filters…" : "set filters to save a cohort"}
               value={cohortName} disabled={filters.length === 0}
               onChange={(e) => setCohortName(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") saveCohort(); }} />
        <button onClick={saveCohort}
                disabled={!cohortName.trim() || filters.length === 0}>
          Save cohort
        </button>
        <button onClick={() => setShowCompare((v) => !v)}>
          {showCompare ? "Hide compare" : "Compare groups"}
        </button>
      </div>

      {showCompare && (
        <ComparePanel dataset={dataset} onClose={() => setShowCompare(false)} />
      )}

      <AskAI dataset={dataset} onUpdate={onUpdate} />

      <ChatWidget dataset={dataset} onUpdate={onUpdate} />

      <AddChart dataset={dataset} onUpdate={onUpdate} />

      <div className="chart-grid">
        {charts.map((spec, i) => (
          <ChartCard
            key={`${spec.kind}-${spec.x}-${spec.y ?? ""}-${i}`}
            spec={spec}
            result={result?.charts[i]}
            palette={palette}
            kinds={allowedKinds(spec)}
            onTapCategory={toggleCategory}
            onChangeKind={(kind) => updateChart(i, { kind })}
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

function SaveToAurora({ dataset }: { dataset: Dataset }) {
  const [open, setOpen] = useState(false);
  const [sources, setSources] = useState<Source[]>([]);
  const [resourceId, setResourceId] = useState("");
  const [table, setTable] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    api.datasources().then((out) => {
      const aurora = out.sources.filter((s) => s.kind === "aurora");
      setSources(aurora);
      if (aurora[0]) setResourceId(aurora[0].id);
    }).catch(() => undefined);
    if (!table) {
      setTable(dataset.title.replace(/\.[^.]+$/, "")
        .replace(/[^A-Za-z0-9_]/g, "_").toLowerCase().slice(0, 48));
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!resourceId || !table) return;
    setBusy(true);
    setStatus("");
    try {
      const out = await api.materialize(dataset.id, resourceId, table);
      setStatus(`Saved ${out.rows.toLocaleString()} rows to ${out.table}.`);
    } catch (e) {
      setStatus(`Failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return <button onClick={() => setOpen(true)}>Save to Aurora</button>;
  }
  return (
    <div className="save-aurora">
      <select value={resourceId} onChange={(e) => setResourceId(e.target.value)}>
        {sources.length === 0 && <option value="">No Aurora resource</option>}
        {sources.map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
      </select>
      <input type="text" placeholder="table_name" value={table}
             onChange={(e) => setTable(e.target.value)} />
      <button className="primary" onClick={save}
              disabled={busy || !resourceId || !table}>
        {busy ? "Saving…" : "Save"}
      </button>
      <button className="quiet" onClick={() => setOpen(false)}>✕</button>
      {status && <span className="ask-note">{status}</span>}
    </div>
  );
}

function AskAI({ dataset, onUpdate }:
    { dataset: Dataset; onUpdate: (c: Partial<Dataset>) => void }) {
  const [question, setQuestion] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const ask = async () => {
    if (!question.trim()) return;
    setBusy(true);
    setNote("");
    try {
      const out = await api.ask(dataset.id, question, dataset.filters);
      onUpdate({ filters: out.filters });
      setNote(out.explanation);
      setQuestion("");
    } catch (e) {
      setNote(`Ask AI failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ask-ai">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" strokeWidth="2">
        <path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4L12 3z" />
      </svg>
      <input
        type="text"
        placeholder='Ask AI to filter — e.g. "liver samples with RIN above 7"'
        value={question}
        disabled={busy}
        onChange={(e) => setQuestion(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") ask(); }}
      />
      <button className="primary" onClick={ask}
              disabled={busy || !question.trim()}>
        {busy ? "Thinking…" : "Ask"}
      </button>
      {note && <span className="ask-note">{note}</span>}
    </div>
  );
}

function AddChart({ dataset, onUpdate }:
    { dataset: Dataset; onUpdate: (c: Partial<Dataset>) => void }) {
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
