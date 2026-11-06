/** The chart "Marks" card: pick how a chart is drawn (Automatic, Bar, Line, …)
 *  and its mark settings (Color, Size, Labels). Inspired by Tableau's Marks
 *  card, limited to what our chart data supports. */
import type { ReactNode } from "react";
import type { ChartMarks, ChartSpec, ChartStyle, MarkType } from "../types";
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
};
export const MARK_LABEL: Record<MarkType, string> = {
  automatic: "Automatic", bar: "Bar", column: "Column", line: "Line", area: "Area", pie: "Pie",
  donut: "Donut", circle: "Circle", density: "Density", map: "Map",
};
const ORDER: MarkType[] = ["automatic", "bar", "column", "line", "area", "pie", "donut", "circle", "density", "map"];

/** What each mark draws for a chart whose fields allow `kinds`; a string is why it can't. */
export function resolveMark(mark: MarkType, kinds: ChartSpec["kind"][], hasY: boolean): Choice | string {
  const has = (k: ChartSpec["kind"]) => kinds.includes(k);
  switch (mark) {
    case "automatic":
      return hasY ? { kind: has("scatter") ? "scatter" : "heatmap" }
        : { kind: has("histogram") ? "histogram" : "bar" };
    case "bar": return hasY ? "Bar shows one field." : { kind: "bar", style: "bar" };
    case "column":
      return hasY ? "Column shows one field." : has("histogram") ? { kind: "histogram", style: "column" } : { kind: "bar", style: "column" };
    case "line": case "area":
      return hasY ? `${MARK_LABEL[mark]} shows one field.`
        : { kind: has("histogram") ? "histogram" : "bar", style: mark };
    case "pie": case "donut":
      return hasY ? `${MARK_LABEL[mark]} shows one field.` : { kind: "bar", style: mark };
    case "circle": return has("scatter") ? { kind: "scatter" } : "Circle needs two numeric fields.";
    case "density": return has("heatmap") ? { kind: "heatmap" } : "Density needs a second field.";
    case "map": return has("map") ? { kind: "map" } : "Map needs numeric longitude and latitude fields.";
  }
}

/** The mark a saved chart shows as selected. */
export function currentMark(spec: ChartSpec): MarkType {
  if (spec.mark) return spec.mark;
  if (spec.kind === "scatter") return "circle";
  if (spec.kind === "heatmap") return "density";
  if (spec.kind === "map") return "map";
  if (spec.kind === "histogram") return spec.style === "line" || spec.style === "area" ? spec.style : "column";
  return (spec.style as MarkType | undefined) ?? "bar";
}

export const MARK_COLORS = ["#087a6a", "#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#e87ba4"];

export function MarksMenu({ spec, kinds, onChoose, onMarks }: {
  spec: ChartSpec; kinds: ChartSpec["kind"][];
  onChoose: (mark: MarkType, choice: Choice) => void;
  onMarks: (marks: ChartMarks) => void;
}) {
  const mark = currentMark(spec);
  const marks = spec.marks ?? {};
  const pie = spec.kind === "bar" && (spec.style === "pie" || spec.style === "donut");
  // Only offer settings the renderer applies to this chart.
  const noColor = pie || spec.kind === "heatmap";
  const noSize = pie || spec.kind === "heatmap";
  const noLabels = spec.kind === "map" || spec.kind === "heatmap" || spec.kind === "scatter";
  return (
    <Popover className="marks-menu" ariaLabel="Marks"
             label={<>{ICONS[mark]}<span>{MARK_LABEL[mark]}</span><span aria-hidden>▾</span></>}>
      {(close) => <>
        <div className="marks-title">Marks</div>
        <div className="marks-list" role="radiogroup" aria-label="Mark type">
          {ORDER.map((m) => {
            const choice = resolveMark(m, kinds, Boolean(spec.y));
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
          <fieldset className="marks-prop" disabled={noColor}
                    title={pie ? "Pie and donut slices use a fixed color order" : spec.kind === "heatmap" ? "Density uses the theme's color scale" : undefined}>
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
