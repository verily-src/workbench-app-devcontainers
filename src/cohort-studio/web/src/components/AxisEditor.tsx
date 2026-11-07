import { formatNumber, numericAxes, referenceAxes } from "../chartStyles";
import { useState } from "react";
import type { AxisFormat, AxisSettings, ChartReference, ChartSpec, Parameter } from "../types";

type Draft = { label: string; scale: "linear" | "log"; min: string; max: string;
  decimals: string; unit: string; percent: boolean };
function draft(axis?: AxisSettings): Draft {
  return { label: axis?.label ?? "", scale: axis?.scale ?? "linear",
    min: axis?.min?.toString() ?? "", max: axis?.max?.toString() ?? "",
    decimals: axis?.format?.decimals?.toString() ?? "", unit: axis?.format?.unit ?? "",
    percent: Boolean(axis?.format?.percent) };
}

type RefDraft = { axis: "x" | "y"; value: string; param: string; to: string; label: string; to_param?: string };
const refDraft = (ref: ChartReference, axis: "x" | "y"): RefDraft => ({
  axis: ref.axis ?? axis, value: ref.value?.toString() ?? "", param: ref.param ?? "",
  to: ref.to?.toString() ?? "", label: ref.label ?? "", ...(ref.to_param ? { to_param: ref.to_param } : {}) });

const MAX_REFERENCES = 5;

export function AxisEditor({ spec, onApply, onCancel, parameters = [] }: {
  spec: ChartSpec;
  onApply: (x: AxisSettings, y: AxisSettings, references?: ChartReference[]) => void;
  onCancel: () => void;
  parameters?: Parameter[];
}) {
  const [x, setX] = useState(() => draft(spec.x_axis));
  const [y, setY] = useState(() => draft(spec.y_axis));
  const axes = referenceAxes(spec);
  const [refs, setRefs] = useState<RefDraft[]>(() => (spec.references ?? []).map((r) => refDraft(r, axes[0] ?? "y")));
  const [error, setError] = useState("");
  const numbers = parameters.filter((p) => p.kind === "number");
  // The drawn style decides the numeric axis (a categorical Line has numbers on Y).
  const { x: xNumeric, y: yNumeric } = numericAxes(spec);
  const number = (text: string, what: string) => {
    if (text.trim() === "") return undefined;
    const value = Number(text);
    if (!Number.isFinite(value)) throw new Error(`${what} must be a finite number.`);
    return value;
  };
  const build = (value: Draft, numeric: boolean): AxisSettings => {
    const label = value.label.trim() || undefined;
    if (!numeric) return { label };
    const min = number(value.min, "Axis bounds");
    const max = number(value.max, "Axis bounds");
    if (min !== undefined && max !== undefined && min >= max)
      throw new Error("Axis minimum must be less than maximum.");
    if (value.scale === "log" && ((min !== undefined && min <= 0) || (max !== undefined && max <= 0)))
      throw new Error("Log scale bounds must be positive.");
    const format: AxisFormat = {
      ...(value.decimals !== "" ? { decimals: Number(value.decimals) } : {}),
      ...(value.unit.trim() ? { unit: value.unit.trim() } : {}),
      ...(value.percent ? { percent: true } : {}),
    };
    return { label, scale: value.scale, min, max, ...(Object.keys(format).length ? { format } : {}) };
  };
  const buildRefs = (): ChartReference[] | undefined => {
    const out = refs.map((r, i): ChartReference => {
      const value = number(r.value, `Reference ${i + 1} value`);
      const to = number(r.to, `Reference ${i + 1} band end`);
      if (value === undefined && !r.param) throw new Error(`Reference ${i + 1} needs a value or a parameter.`);
      return { ...(axes.length > 1 ? { axis: r.axis } : {}), ...(value !== undefined ? { value } : {}),
        ...(r.param ? { param: r.param } : {}), ...(to !== undefined ? { to } : {}),
        ...(r.to_param ? { to_param: r.to_param } : {}),
        ...(r.label.trim() ? { label: r.label.trim() } : {}) };
    });
    return out.length ? out : undefined;
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
        <label>Decimals<select aria-label={`${axis} axis decimals`} value={value.decimals}
          onChange={e => update({ ...value, decimals: e.target.value })}>
          <option value="">Auto</option>
          {[0, 1, 2, 3, 4].map((d) => <option key={d} value={d}>{d}</option>)}
        </select></label>
        <label>Units<input aria-label={`${axis} axis units`} maxLength={16} value={value.unit}
          onChange={e => update({ ...value, unit: e.target.value })} placeholder="e.g. mg/dL" /></label>
        <label className="axis-check"><input type="checkbox" aria-label={`${axis} axis percent`} checked={value.percent}
          onChange={e => update({ ...value, percent: e.target.checked })} /> Percent (×100)</label>
        <p className="axis-sample">Shows {formatNumber(1234.5678 / (value.percent ? 10000 : 1), {
          decimals: value.decimals === "" ? undefined : Number(value.decimals), unit: value.unit.trim() || undefined,
          percent: value.percent })}</p>
      </>}
    </fieldset>;
  const setRef = (i: number, change: Partial<RefDraft>) =>
    setRefs((list) => list.map((r, j) => (j === i ? { ...r, ...change } : r)));
  return <form className="axis-editor" aria-label="Chart axes" onSubmit={e => {
    e.preventDefault();
    try { onApply(build(x, xNumeric), build(y, yNumeric), buildRefs()); }
    catch (caught) { setError((caught as Error).message); }
  }}>
    <div className="axis-editor-fields">{fields("X", x, setX, xNumeric)}{fields("Y", y, setY, yNumeric)}</div>
    {((xNumeric && x.scale === "log") || (yNumeric && y.scale === "log")) &&
      <p>Log scales show positive values only.</p>}
    {axes.length > 0 && <fieldset className="axis-references"><legend>Reference lines</legend>
      {refs.map((r, i) => <div className="axis-reference" key={i} role="group" aria-label={`Reference ${i + 1}`}>
        {axes.length > 1 && <label>Axis<select aria-label="Reference axis" value={r.axis}
          onChange={e => setRef(i, { axis: e.target.value as "x" | "y" })}>
          {axes.map((a) => <option key={a} value={a}>{a.toUpperCase()}</option>)}</select></label>}
        <label>Value<input aria-label="Reference value" type="number" step="any" value={r.value}
          onChange={e => setRef(i, { value: e.target.value })} placeholder={r.param ? "From parameter" : ""} /></label>
        {numbers.length > 0 && <label>Parameter<select aria-label="Reference parameter" value={r.param}
          onChange={e => setRef(i, { param: e.target.value })}>
          <option value="">None</option>
          {numbers.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}</select></label>}
        <label>Band to<input aria-label="Reference band end" type="number" step="any" value={r.to}
          onChange={e => setRef(i, { to: e.target.value })} placeholder="Line" /></label>
        {numbers.length > 0 && <label>Band to parameter<select aria-label="Reference band parameter" value={r.to_param ?? ""}
          onChange={e => setRef(i, { to_param: e.target.value || undefined })}>
          <option value="">None</option>
          {numbers.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}</select></label>}
        <label>Label<input aria-label="Reference label" maxLength={60} value={r.label}
          onChange={e => setRef(i, { label: e.target.value })} placeholder="e.g. HbA1c 6.5" /></label>
        <button type="button" className="quiet" aria-label={`Remove reference ${i + 1}`}
          onClick={() => setRefs((list) => list.filter((_, j) => j !== i))}>✕</button>
      </div>)}
      {refs.length < MAX_REFERENCES && <button type="button"
        onClick={() => setRefs((list) => [...list, { axis: axes[0], value: "", param: "", to: "", label: "" }])}>
        + Reference line</button>}
    </fieldset>}
    {error && <p role="alert">{error}</p>}
    <div><button type="submit" className="primary">Apply</button> <button type="button" onClick={onCancel}>Cancel</button></div>
  </form>;
}
