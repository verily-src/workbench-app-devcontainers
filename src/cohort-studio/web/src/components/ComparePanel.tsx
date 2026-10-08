import { useState } from "react";
import { api, CompareResult, CompareRow } from "../api";
import type { Cohort, Dataset, Filter } from "../types";

interface Props {
  dataset: Dataset;
  onClose: () => void;
}

// Pseudo-cohorts always available alongside the user's saved ones.
const CURRENT = "__current__";
const REST = "__rest__";

function summaryText(row: CompareRow, side: "a" | "b"): string {
  const s = row[side];
  if (row.kind === "range") {
    return s.median != null ? `median ${s.median} (n=${s.n})` : `n=${s.n}`;
  }
  const top = (s.top ?? []).map((t) => `${t.value} ${t.pct}%`).join(", ");
  return top ? `${top} (n=${s.n})` : `n=${s.n}`;
}

const fmtP = (p: number | null) =>
  p == null ? "—" : p < 0.001 ? p.toExponential(1) : p.toFixed(3);

export function ComparePanel({ dataset, onClose }: Props) {
  const cohorts = dataset.cohorts ?? [];
  const [aKey, setAKey] = useState(CURRENT);
  const [bKey, setBKey] = useState(REST);
  const [result, setResult] = useState<CompareResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const filtersFor = (key: string): Filter[] => {
    if (key === CURRENT) return dataset.filters;
    if (key === REST) return [];
    return cohorts.find((c: Cohort) => c.name === key)?.filters ?? [];
  };

  const run = async () => {
    setBusy(true); setError(""); setResult(null);
    try {
      setResult(await api.compare(
        dataset.id, filtersFor(aKey), filtersFor(bKey), bKey === REST));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const options = (exclude: string) => (
    <>
      <option value={CURRENT}>Current filters</option>
      <option value={REST}>Rest of data (complement of A)</option>
      {cohorts.map((c) => (
        <option key={c.name} value={c.name} disabled={c.name === exclude}>
          {c.name}
        </option>
      ))}
    </>
  );

  return (
    <div className="compare-panel">
      <div className="compare-row">
        <label>Group A
          <select value={aKey} onChange={(e) => setAKey(e.target.value)}>
            {options(bKey)}
          </select>
        </label>
        <span className="compare-vs">vs</span>
        <label>Group B
          <select value={bKey} onChange={(e) => setBKey(e.target.value)}>
            {options(aKey)}
          </select>
        </label>
        <button className="primary" onClick={run} disabled={busy}>
          {busy ? "Comparing…" : "Compare"}
        </button>
        <button className="quiet" onClick={onClose}>✕</button>
      </div>

      {error && <div className="settings-hint">Compare failed: {error}</div>}

      {result && (
        <>
          <div className="settings-hint" style={{ margin: "4px 0 8px" }}>
            A: {result.a_n.toLocaleString()} rows · B:{" "}
            {result.b_n.toLocaleString()} rows
            {result.n_overlap > 0 &&
              ` · ⚠ ${result.n_overlap} rows in both groups`}
            {" "}· ranked by significance, Benjamini-Hochberg q-values
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>variable</th><th>group A</th><th>group B</th>
                <th>p</th><th>q (FDR)</th><th>note</th>
              </tr>
            </thead>
            <tbody>
              {result.results.map((r) => (
                <tr key={r.column}
                    className={r.q != null && r.q < 0.05 ? "cmp-sig" : ""}>
                  <td>{r.column}</td>
                  <td>{summaryText(r, "a")}</td>
                  <td>{summaryText(r, "b")}</td>
                  <td>{fmtP(r.p)}</td>
                  <td>{fmtP(r.q)}</td>
                  <td className="cmp-note">{r.note ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
