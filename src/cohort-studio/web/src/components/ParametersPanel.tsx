/** Tab parameters: named numbers and dates that filters can follow
 *  ("age ≥ min_age", "visit from index_date"). Changing one updates every
 *  filter bound to it. */
import { useState } from "react";
import type { Parameter } from "../types";
import { PARAM_NAME } from "../params";

export function ParametersPanel({ parameters, onChange }: {
  parameters: Parameter[]; onChange: (next: Parameter[]) => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Parameter["kind"]>("number");
  const trimmed = name.trim();
  const problem = !trimmed ? null
    : !PARAM_NAME.test(trimmed) ? "Use letters, digits and _ (start with a letter)."
      : parameters.some((p) => p.name === trimmed) ? "That name is taken." : null;
  const set = (index: number, value: number | string) =>
    onChange(parameters.map((p, i) => (i === index ? { ...p, value } : p)));
  return (
    <div className="parameters" role="group" aria-label="Parameters">
      {parameters.map((p, i) => (
        <div key={p.name} className="parameter-row">
          <span className="parameter-name" title={`${p.kind} parameter`}>{p.name}</span>
          {p.kind === "number" ? (
            <input type="number" step="any" aria-label={`Parameter ${p.name}`} value={String(p.value)}
                   onChange={(e) => { if (e.target.value !== "" && Number.isFinite(Number(e.target.value))) set(i, Number(e.target.value)); }} />
          ) : (
            <input type="date" aria-label={`Parameter ${p.name}`} value={String(p.value)}
                   onChange={(e) => { if (e.target.value) set(i, e.target.value); }} />
          )}
          <button type="button" className="quiet" aria-label={`Remove parameter ${p.name}`} title="Remove parameter"
                  onClick={() => onChange(parameters.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <form className="parameter-add" onSubmit={(e) => {
        e.preventDefault();
        if (!trimmed || problem) return;
        const value = kind === "number" ? 0 : new Date().toISOString().slice(0, 10);
        onChange([...parameters, { name: trimmed, kind, value }]);
        setName("");
      }}>
        <input aria-label="New parameter name" placeholder="e.g. min_age" value={name} maxLength={40}
               onChange={(e) => setName(e.target.value)} />
        <select aria-label="New parameter type" value={kind} onChange={(e) => setKind(e.target.value as Parameter["kind"])}>
          <option value="number">Number</option>
          <option value="date">Date</option>
        </select>
        <button type="submit" disabled={!trimmed || Boolean(problem)}>Add</button>
      </form>
      {problem && <div className="settings-hint" role="alert">{problem}</div>}
    </div>
  );
}
