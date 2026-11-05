import { useEffect, useRef, useState } from "react";
import { api, OpenResult } from "../api";
import type { Dataset } from "../types";

type Summary = { columns: string[]; rows: unknown[][]; total_groups: number; input_rows: number;
  page: number; page_size: number; scope: "database" | "loaded"; sampled: boolean };

export function GroupSummary({ dataset, onUpdate, onClose, onOpenTable }: { dataset: Dataset; onUpdate: (changes: Partial<Dataset>) => void; onClose: () => void;
  onOpenTable?: (opened: OpenResult, title: string) => void }) {
  const [groups, setGroups] = useState(dataset.groupSummary?.group_by ?? [dataset.columns[0]?.name ?? ""]);
  const [measure, setMeasure] = useState(dataset.groupSummary?.measure ?? "");
  const [result, setResult] = useState<Summary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState("");
  const sequence = useRef(0);
  const filterKey = JSON.stringify(dataset.filters);
  useEffect(() => { sequence.current++; setResult(null); setError(""); setBusy(false); setOpenError(""); }, [dataset.id, filterKey]);
  // Opens the full summary (every group, current filters) as its own dataset tab.
  const openTable = async () => {
    if (!result || !onOpenTable) return;
    // A result is only shown while the selections match the run that produced it.
    const recipe = { group_by: groups, measure: measure || null };
    setOpening(true); setOpenError("");
    try {
      const opened = await api.openGroupSummary(dataset.id, { group_by: recipe.group_by, measure: recipe.measure, filters: dataset.filters });
      onOpenTable(opened, `${dataset.title} · Group summary (${recipe.group_by.join(", ")})`);
    } catch (e) {
      setOpenError((e as Error).message);
    } finally { setOpening(false); }
  };
  const run = async (page = 0, selectedGroups = groups, selectedMeasure = measure) => {
    if (selectedGroups.some(group => !group) || new Set(selectedGroups).size !== selectedGroups.length) {
      setError("Choose distinct grouping columns."); return;
    }
    const current = ++sequence.current;
    setBusy(true); setError("");
    try {
      const response = await api.groupSummary(dataset.id, { group_by: selectedGroups, measure: selectedMeasure || null,
        filters: dataset.filters, page, page_size: 50 });
      if (current === sequence.current) {
        setResult(response);
        const recipe = { group_by: selectedGroups, measure: selectedMeasure || null };
        if (JSON.stringify(dataset.groupSummary) !== JSON.stringify(recipe)) onUpdate({ groupSummary: recipe });
      }
    } catch (e) {
      if (current === sequence.current) { setResult(null); setError((e as Error).message); }
    } finally { if (current === sequence.current) setBusy(false); }
  };
  useEffect(() => {
    const recipe = dataset.groupSummary;
    const nextGroups = recipe?.group_by ?? [dataset.columns[0]?.name ?? ""];
    const nextMeasure = recipe?.measure ?? "";
    setGroups(nextGroups); setMeasure(nextMeasure);
    if (recipe) void run(0, nextGroups, nextMeasure);
  }, [dataset.id]);
  const change = (action: () => void) => { sequence.current++; setResult(null); setError(""); setOpenError(""); setBusy(false); action(); };
  return <section className="derive-panel" aria-label="Group summary">
    <div className="derive-row">
      {groups.map((group, index) => <label key={index}>{index ? `Group ${index + 1}` : "Group by"}
        <select value={group} onChange={e => change(() => setGroups(prev => prev.map((v, i) => i === index ? e.target.value : v)))}>
          {dataset.columns.map(c => <option key={c.name} value={c.name}>{c.label || c.name}</option>)}
        </select>
        {index > 0 && <button type="button" className="quiet" onClick={() => change(() => setGroups(prev => prev.filter((_, i) => i !== index)))}>Remove group</button>}
      </label>)}
      {groups.length < 5 && groups.length < dataset.columns.length && <button type="button" onClick={() => change(() => {
        const next = dataset.columns.find(c => !groups.includes(c.name)); if (next) setGroups(prev => [...prev, next.name]);
      })}>Add group</button>}
      <label>Value column<select value={measure} onChange={e => change(() => setMeasure(e.target.value))}>
        <option value="">None</option>{dataset.columns.map(c => <option key={c.name} value={c.name}>{c.label || c.name}</option>)}
      </select></label>
    </div>
    <button className="primary" disabled={busy || !groups[0]} onClick={() => void run()}>{busy ? "Summarizing…" : "Summarize"}</button>
    {onOpenTable && <button disabled={busy || opening || !result} onClick={() => void openTable()}
      title="Open every group of this summary, with the current filters, as a new dataset tab">{opening ? "Opening table…" : "Open as table"}</button>}
    <button className="quiet" onClick={onClose}>Close</button>
    {error && <p role="alert">Could not summarize: {error}</p>}
    {openError && <p role="alert">Could not open the summary as a table: {openError}</p>}
    {result && <div>
      <p role="status">{result.input_rows.toLocaleString()} filtered rows · {result.total_groups.toLocaleString()} {result.total_groups === 1 ? "group" : "groups"} · {result.sampled ? "Loaded sample" : result.scope === "database" ? "Full database" : "Loaded data"}. Empty group values are included.{measure ? " Non-numeric values are excluded from value statistics." : ""}</p>
      <div style={{ overflowX: "auto" }}><table className="data-table"><thead><tr>{result.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>{result.rows.map((row, index) => <tr key={index}>{row.map((value, i) => <td key={i}>{value == null ? "—" : String(value)}</td>)}</tr>)}</tbody></table></div>
      <div><button disabled={busy || result.page === 0} onClick={() => void run(result.page - 1)}>Previous</button>
        <span> Page {result.page + 1} of {Math.max(1, Math.ceil(result.total_groups / result.page_size))} </span>
        <button disabled={busy || (result.page + 1) * result.page_size >= result.total_groups} onClick={() => void run(result.page + 1)}>Next</button></div>
    </div>}
  </section>;
}
