/** The chart "Marks" card: pick how a chart is drawn (Automatic, Bar, Line, …)
 *  and its mark settings (Color, Size, Labels). Inspired by Tableau's Marks
 *  card, limited to what our chart data supports. */
import type { ReactNode } from "react";
import type { ChartMarks, ChartMeasure, ChartSpec, ChartStyle, ColumnProfile, MarkType, MeasureAgg } from "../types";
import { Popover } from "./Popover";

type Choice = { kind: ChartSpec["kind"]; style?: ChartStyle };

const I = (d: ReactNode) => (
  <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor"
       strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">{d}</svg>
);
const ICONS: Record<MarkType, ReactNode> = {
  automatic: I(<><rect x="2.5" y="2.5" width="11" height="11" rx="1.5" /><path d="M5.5 5.5h5M8 5.5v5" /></>),
  bar: I(<path d="M2.5 4h7M2.5 8h11M2.5 12h5" strokeWidth="2" />),
  column: I(<path d="M4 13.5V8M8 13.5V3M12 13.5V6" strokeWidth="2" />),
  line: I(<path d="M2 12l4-5 3 3 5-6" />),
  area: I(<path d="M2 13.5V11l4-5 3 3 5-5v9.5z" />),
  pie: I(<><circle cx="8" cy="8" r="5.5" /><path d="M8 8V2.5M8 8l4.5 3" /></>),
  donut: I(<><circle cx="8" cy="8" r="5.5" /><circle cx="8" cy="8" r="2.5" /></>),
  circle: I(<><circle cx="5" cy="10" r="1.6" /><circle cx="10" cy="5" r="1.6" /><circle cx="11.5" cy="11" r="1.6" /></>),
  density: I(<><rect x="2.5" y="2.5" width="5" height="5" /><rect x="8.5" y="2.5" width="5" height="5" fill="currentColor" opacity=".35" />
    <rect x="2.5" y="8.5" width="5" height="5" fill="currentColor" opacity=".7" /><rect x="8.5" y="8.5" width="5" height="5" /></>),
  map: I(<><path d="M2 4l4-1.5 4 1.5 4-1.5v9.5L10 13.5 6 12 2 13.5z" /><path d="M6 2.5V12M10 4v9.5" /></>),
  box: I(<><rect x="4.5" y="5" width="7" height="6" rx="1" /><path d="M8 2v3M8 11v3M6 2h4M6 14h4M4.5 8h7" /></>),
};
export const MARK_LABEL: Record<MarkType, string> = {
  automatic: "Automatic", bar: "Bar", column: "Column", line: "Line", area: "Area", pie: "Pie",
  donut: "Donut", circle: "Circle", density: "Density", map: "Map", box: "Box",
};
const ORDER: MarkType[] = ["automatic", "bar", "column", "line", "area", "pie", "donut", "box", "circle", "density", "map"];

/** A measure other than row count, or a Split by field: drawn from grouped (bar) data, never bins. */
export function isMeasured(spec: Pick<ChartSpec, "measure" | "series">): boolean {
  return Boolean(spec.series) || Boolean(spec.measure && spec.measure.agg !== "count");
}

/** What each mark draws for a chart whose fields allow `kinds`; a string is why it can't. */
export function resolveMark(mark: MarkType, kinds: ChartSpec["kind"][], hasY: boolean,
                            data: Pick<ChartSpec, "measure" | "series"> = {}): Choice | string {
  const has = (k: ChartSpec["kind"]) => kinds.includes(k);
  const measured = isMeasured(data);
  const binned = has("histogram") && !measured;
  switch (mark) {
    case "automatic":
      return hasY ? { kind: has("scatter") ? "scatter" : "heatmap" }
        : { kind: binned ? "histogram" : "bar" };
    case "bar": return hasY ? "Bar shows one field." : { kind: "bar", style: "bar" };
    case "column":
      return hasY ? "Column shows one field." : binned ? { kind: "histogram", style: "column" } : { kind: "bar", style: "column" };
    case "line": case "area":
      return hasY ? `${MARK_LABEL[mark]} shows one field.`
        : { kind: binned ? "histogram" : "bar", style: mark };
    case "pie": case "donut":
      if (hasY) return `${MARK_LABEL[mark]} shows one field.`;
      if (data.series) return `${MARK_LABEL[mark]} shows one series; clear Split by.`;
      if (data.measure && !["count", "sum"].includes(data.measure.agg))
        return `${MARK_LABEL[mark]} shows parts of a whole: use a count or sum.`;
      return { kind: "bar", style: mark };
    case "circle": return has("scatter") ? { kind: "scatter" } : "Circle needs two numeric fields.";
    case "density": return has("heatmap") ? { kind: "heatmap" } : "Density needs a second field.";
    case "map": return has("map") ? { kind: "map" } : "Map needs numeric longitude and latitude fields.";
    case "box": return has("box") ? { kind: "box" } : "Box needs a numeric field (and an optional group).";
  }
}

/** The mark a saved chart shows as selected. */
export function currentMark(spec: ChartSpec): MarkType {
  if (spec.mark) return spec.mark;
  if (spec.kind === "scatter") return "circle";
  if (spec.kind === "heatmap") return "density";
  if (spec.kind === "map") return "map";
  if (spec.kind === "box") return "box";
  if (spec.kind === "histogram") return spec.style === "line" || spec.style === "area" ? spec.style : "column";
  return (spec.style as MarkType | undefined) ?? "bar";
}

export const MARK_COLORS = ["#087a6a", "#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#e87ba4"];

export const MEASURE_LABEL: Record<MeasureAgg, string> = {
  count: "Count rows", count_distinct: "Count distinct", sum: "Sum", mean: "Mean", median: "Median",
  min: "Minimum", max: "Maximum",
};
const NUMERIC_DTYPE = /int|float|double|decimal|numeric|real/i;
/** Fields a measure can use: numbers for sum/mean/…, any field for count distinct. */
export function measureFields(fields: ColumnProfile[], agg: MeasureAgg, x: string): ColumnProfile[] {
  if (agg === "count") return [];
  if (agg === "count_distinct") return fields.filter((f) => f.name !== x);
  return fields.filter((f) => f.filter_kind === "range" || NUMERIC_DTYPE.test(f.dtype));
}
/** Fields that can split a chart into series: categorical ones other than the chart field. */
export const seriesFields = (fields: ColumnProfile[], x: string, y?: string) =>
  fields.filter((f) => f.filter_kind === "categorical" && f.name !== x && f.name !== y);

/** Spec changes for a new measure/series; histograms become grouped bars (bins only count). */
export function dataChanges(spec: ChartSpec, measure: ChartMeasure | undefined,
                            series: string | undefined): Partial<ChartSpec> {
  const changes: Partial<ChartSpec> = { measure: measure && measure.agg !== "count" ? measure : undefined, series };
  if (!isMeasured(changes)) return changes;
  if (spec.kind === "histogram") return { ...changes, kind: "bar", style: spec.style ?? "column" };
  const pie = spec.style === "pie" || spec.style === "donut";
  if (pie && typeof resolveMark(spec.style as MarkType, ["bar"], false, changes) === "string")
    return { ...changes, style: "column", mark: "column" };
  return changes;
}

function DataControls({ spec, fields, onData }: {
  spec: ChartSpec; fields: ColumnProfile[]; onData: (changes: Partial<ChartSpec>) => void;
}) {
  const agg = spec.measure?.agg ?? "count";
  const column = spec.measure?.column ?? "";
  const choices = measureFields(fields, agg, spec.x);
  const splits = seriesFields(fields, spec.x, spec.y);
  const additive = agg === "count" || agg === "sum";
  const stackable = Boolean(spec.series) && additive && spec.style !== "line";
  const label = (f: ColumnProfile) => f.label || f.name;
  return <>
    <fieldset className="marks-prop">
      <legend>Measure</legend>
      <div className="marks-data">
        <select aria-label="Measure" value={agg} onChange={(e) => {
          const next = e.target.value as MeasureAgg;
          const options = measureFields(fields, next, spec.x);
          const keep = options.some((f) => f.name === column) ? column : options[0]?.name;
          if (next !== "count" && !keep) return;
          onData(dataChanges(spec, { agg: next, column: next === "count" ? undefined : keep }, spec.series));
        }}>
          {(Object.keys(MEASURE_LABEL) as MeasureAgg[]).map((a) => (
            <option key={a} value={a} disabled={a !== "count" && measureFields(fields, a, spec.x).length === 0}>
              {MEASURE_LABEL[a]}</option>))}
        </select>
        {agg !== "count" && <select aria-label="Measure field" value={column}
          onChange={(e) => onData(dataChanges(spec, { agg, column: e.target.value }, spec.series))}>
          {choices.map((f) => <option key={f.name} value={f.name}>{label(f)}</option>)}
        </select>}
      </div>
    </fieldset>
    <fieldset className="marks-prop">
      <legend>Split by</legend>
      <div className="marks-data">
        <select aria-label="Split by" value={spec.series ?? ""}
          onChange={(e) => onData(dataChanges(spec, spec.measure, e.target.value || undefined))}>
          <option value="">None</option>
          {splits.map((f) => <option key={f.name} value={f.name}>{label(f)}</option>)}
        </select>
        {stackable && <label className="marks-toggle">
          <input type="checkbox" checked={Boolean(spec.marks?.stack)}
                 onChange={(e) => onData({ marks: { ...(spec.marks ?? {}), stack: e.target.checked || undefined } })} />
          Stack
        </label>}
      </div>
    </fieldset>
  </>;
}

export function MarksMenu({ spec, kinds, onChoose, onMarks, fields, onData }: {
  spec: ChartSpec; kinds: ChartSpec["kind"][];
  onChoose: (mark: MarkType, choice: Choice) => void;
  onMarks: (marks: ChartMarks) => void;
  fields?: ColumnProfile[];
  onData?: (changes: Partial<ChartSpec>) => void;
}) {
  const mark = currentMark(spec);
  const marks = spec.marks ?? {};
  const pie = spec.kind === "bar" && (spec.style === "pie" || spec.style === "donut");
  const dataControls = Boolean(fields && onData) && !spec.y && (spec.kind === "bar" || spec.kind === "histogram");
  // Only offer settings the renderer applies to this chart.
  const noColor = pie || spec.kind === "heatmap" || Boolean(spec.series);
  const noSize = pie || spec.kind === "heatmap" || spec.kind === "box";
  const noLabels = spec.kind === "map" || spec.kind === "heatmap" || spec.kind === "scatter" || spec.kind === "box";
  return (
    <Popover className="marks-menu" ariaLabel="Marks"
             label={<>{ICONS[mark]}<span>{MARK_LABEL[mark]}</span><span aria-hidden>▾</span></>}>
      {(close) => <>
        <div className="marks-title">Marks</div>
        <div className="marks-list" role="radiogroup" aria-label="Mark type">
          {ORDER.map((m) => {
            const choice = resolveMark(m, kinds, Boolean(spec.y), spec);
            const reason = typeof choice === "string" ? choice : null;
            return (
              <button key={m} type="button" role="radio" aria-checked={m === mark}
                      className={m === mark ? "on" : undefined} disabled={Boolean(reason)}
                      title={reason ?? undefined}
                      onClick={() => { if (typeof choice !== "string") { onChoose(m, choice); close(); } }}>
                {ICONS[m]}<span>{MARK_LABEL[m]}</span>
              </button>
            );
          })}
        </div>
        <div className="marks-props">
          {dataControls && <DataControls spec={spec} fields={fields!} onData={onData!} />}
          <fieldset className="marks-prop" disabled={noColor}
                    title={pie || spec.series ? "Slices and series use a fixed color order" : spec.kind === "heatmap" ? "Density uses the theme's color scale" : undefined}>
            <legend>Color</legend>
            <div className="marks-swatches">
              {MARK_COLORS.map((c, i) => (
                <button key={c} type="button" aria-label={i === 0 ? "Theme color" : `Color ${c}`}
                        aria-pressed={(marks.color ?? MARK_COLORS[0]) === c}
                        style={{ background: i === 0 ? "var(--accent)" : c }}
                        onClick={() => onMarks({ ...marks, color: i === 0 ? undefined : c })} />
              ))}
            </div>
          </fieldset>
          <fieldset className="marks-prop" disabled={noSize}>
            <legend>Size</legend>
            <div className="marks-seg" role="radiogroup" aria-label="Mark size">
              {(["s", "m", "l"] as const).map((v) => (
                <button key={v} type="button" role="radio" aria-checked={(marks.size ?? "m") === v}
                        onClick={() => onMarks({ ...marks, size: v === "m" ? undefined : v })}>
                  {v.toUpperCase()}</button>
              ))}
            </div>
          </fieldset>
          <fieldset className="marks-prop" disabled={noLabels}>
            <legend>Labels</legend>
            <label className="marks-toggle">
              <input type="checkbox" checked={Boolean(marks.labels)}
                     onChange={(e) => onMarks({ ...marks, labels: e.target.checked || undefined })} />
              Show values
            </label>
          </fieldset>
        </div>
      </>}
    </Popover>
  );
}
