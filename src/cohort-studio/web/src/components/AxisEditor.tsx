import { useState } from "react";
import type { AxisSettings, ChartSpec } from "../types";

type Draft = { label: string; scale: "linear" | "log"; min: string; max: string };
function draft(axis?: AxisSettings): Draft {
  return { label: axis?.label ?? "", scale: axis?.scale ?? "linear",
    min: axis?.min?.toString() ?? "", max: axis?.max?.toString() ?? "" };
}

export function AxisEditor({ spec, onApply, onCancel }: {
  spec: ChartSpec;
  onApply: (x: AxisSettings, y: AxisSettings) => void;
  onCancel: () => void;
}) {
  const [x, setX] = useState(() => draft(spec.x_axis));
  const [y, setY] = useState(() => draft(spec.y_axis));
  const [error, setError] = useState("");
  const xNumeric = spec.kind === "bar" || spec.kind === "scatter";
  const yNumeric = spec.kind === "histogram" || spec.kind === "scatter";
  const build = (value: Draft, numeric: boolean): AxisSettings => {
    const label = value.label.trim() || undefined;
    if (!numeric) return { label };
    const min = value.min.trim() === "" ? undefined : Number(value.min);
    const max = value.max.trim() === "" ? undefined : Number(value.max);
    if ((min !== undefined && !Number.isFinite(min)) || (max !== undefined && !Number.isFinite(max)))
      throw new Error("Axis bounds must be finite numbers.");
    if (min !== undefined && max !== undefined && min >= max)
      throw new Error("Axis minimum must be less than maximum.");
    if (value.scale === "log" && ((min !== undefined && min <= 0) || (max !== undefined && max <= 0)))
      throw new Error("Log scale bounds must be positive.");
    return { label, scale: value.scale, min, max };
  };
  const fields = (axis: "X" | "Y", value: Draft, update: (value: Draft) => void, numeric: boolean) =>
    <fieldset><legend>{axis} axis</legend>
      <label>Label<input aria-label={`${axis} axis label`} maxLength={120} value={value.label}
        onChange={e => update({ ...value, label: e.target.value })} placeholder="Default" /></label>
      {numeric && <>
        <label>Scale<select aria-label={`${axis} axis scale`} value={value.scale}
          onChange={e => update({ ...value, scale: e.target.value as Draft["scale"] })}>
          <option value="linear">Linear</option><option value="log">Logarithmic</option>
        </select></label>
        <label>Minimum<input aria-label={`${axis} axis minimum`} type="number" step="any" value={value.min}
          onChange={e => update({ ...value, min: e.target.value })} placeholder="Auto" /></label>
        <label>Maximum<input aria-label={`${axis} axis maximum`} type="number" step="any" value={value.max}
          onChange={e => update({ ...value, max: e.target.value })} placeholder="Auto" /></label>
      </>}
    </fieldset>;
  return <form className="axis-editor" aria-label="Chart axes" onSubmit={e => {
    e.preventDefault();
    try { onApply(build(x, xNumeric), build(y, yNumeric)); }
    catch (caught) { setError((caught as Error).message); }
  }}>
    <div className="axis-editor-fields">{fields("X", x, setX, xNumeric)}{fields("Y", y, setY, yNumeric)}</div>
    {((xNumeric && x.scale === "log") || (yNumeric && y.scale === "log")) &&
      <p>Log scales show positive values only.</p>}
    {error && <p role="alert">{error}</p>}
    <div><button type="submit" className="primary">Apply</button> <button type="button" onClick={onCancel}>Cancel</button></div>
  </form>;
}
