import { useState } from "react";
import { api } from "../api";
import type { Dataset } from "../types";

interface Props {
  dataset: Dataset;
  onUpdate: (changes: Partial<Dataset>) => void;
  onClose: () => void;
}

type Op = "bin" | "formula" | "map";

// Structured derived columns — no free-text formulas. Three shapes cover
// the common cases: bin a number into ranges, arithmetic on columns, or
// remap categorical values.
export function DeriveColumn({ dataset, onUpdate, onClose }: Props) {
  const numeric = dataset.columns
    .filter((c) => c.filter_kind === "range").map((c) => c.name);
  const categorical = dataset.columns
    .filter((c) => c.filter_kind === "categorical").map((c) => c.name);

  const [op, setOp] = useState<Op>("bin");
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  // bin
  const [binCol, setBinCol] = useState(numeric[0] ?? "");
  const [breaks, setBreaks] = useState("0, 18, 65, 120");
  const [labels, setLabels] = useState("");
  // formula
  const [left, setLeft] = useState(numeric[0] ?? "");
  const [operator, setOperator] = useState("/");
  const [right, setRight] = useState(numeric[1] ?? numeric[0] ?? "");
  // map
  const [mapCol, setMapCol] = useState(categorical[0] ?? "");
  const [mapText, setMapText] = useState("");
  const [mapDefault, setMapDefault] = useState("");

  const submit = async () => {
    if (!name.trim()) { setStatus("Name the new column."); return; }
    let spec: Record<string, unknown> = { op, name: name.trim() };
    if (op === "bin") {
      const b = breaks.split(",").map((s) => Number(s.trim()))
        .filter((n) => !Number.isNaN(n));
      const l = labels.trim()
        ? labels.split(",").map((s) => s.trim()) : undefined;
      spec = { ...spec, column: binCol, breaks: b, labels: l };
    } else if (op === "formula") {
      spec = { ...spec, left, operator, right };
    } else {
      const mapping: Record<string, string> = {};
      for (const line of mapText.split("\n")) {
        const [k, v] = line.split("=").map((s) => s.trim());
        if (k && v) mapping[k] = v;
      }
      spec = { ...spec, column: mapCol, mapping,
               default: mapDefault.trim() || undefined };
    }
    setBusy(true); setStatus("");
    try {
      const out = await api.derive(dataset.id, spec);
      onUpdate({ columns: out.columns });
      setStatus(`Added "${out.name}".`);
      setName("");
    } catch (e) {
      setStatus(`Failed: ${(e as Error).message}`);
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
        {status && <span className="ask-note">{status}</span>}
      </div>
    </div>
  );
}
