import type { AxisFormat, ChartReference, ChartSpec, ChartStyle, Parameter } from "./types";

/** Styles per data kind. The first is the default (no `style` saved). */
export const CHART_STYLES: Partial<Record<ChartSpec["kind"], { style: ChartStyle; label: string }[]>> = {
  bar: [{ style: "bar", label: "Bar" }, { style: "column", label: "Column" },
        { style: "line", label: "Line" }, { style: "area", label: "Area" },
        { style: "pie", label: "Pie" }, { style: "donut", label: "Donut" }],
  histogram: [{ style: "column", label: "Histogram" }, { style: "line", label: "Histogram (line)" },
              { style: "area", label: "Histogram (area)" }],
};
export const styleOf = (spec: Pick<ChartSpec, "kind" | "style">): ChartStyle | undefined => {
  const styles = CHART_STYLES[spec.kind];
  if (!styles) return undefined;
  return styles.some((s) => s.style === spec.style) ? spec.style : styles[0].style;
};
/** Which axes hold numbers for the chart as drawn (pie and donut have none). */
export function numericAxes(spec: Pick<ChartSpec, "kind" | "style">): { x: boolean; y: boolean } {
  const style = styleOf(spec);
  if (spec.kind === "scatter") return { x: true, y: true };
  if (spec.kind === "histogram" || spec.kind === "box") return { x: false, y: true };
  if (spec.kind === "bar") {
    if (style === "pie" || style === "donut") return { x: false, y: false };
    return style === "bar" ? { x: true, y: false } : { x: false, y: true };
  }
  return { x: false, y: false };
}

/** Axes a reference line can sit on, default first. A histogram's x holds the field's
 *  values (bins), so a threshold such as "HbA1c 6.5" goes there. */
export function referenceAxes(spec: Pick<ChartSpec, "kind" | "style">): ("x" | "y")[] {
  if (spec.kind === "histogram") return ["x", "y"];
  if (spec.kind === "scatter") return ["y", "x"];
  const { x, y } = numericAxes(spec);
  return [...(x ? ["x" as const] : []), ...(y ? ["y" as const] : [])];
}

const compact = (value: number) =>
  new Intl.NumberFormat("en", { notation: "compact", maximumSignificantDigits: 4 }).format(value);

/** A value as the axis format asks: percent (×100), fixed decimals, then the unit. */
export function formatNumber(value: number, format?: AxisFormat): string {
  if (!Number.isFinite(value)) return "";
  if (!format || (format.decimals === undefined && !format.unit && !format.percent)) return compact(value);
  const n = format.percent ? value * 100 : value;
  const text = format.decimals === undefined ? compact(n)
    : n.toLocaleString("en", { minimumFractionDigits: format.decimals, maximumFractionDigits: format.decimals });
  const unit = format.unit ? `${/^[A-Za-z]/.test(format.unit) ? " " : ""}${format.unit}` : "";
  return `${text}${format.percent ? "%" : ""}${unit}`;
}

/** A reference with its parameter values filled in; undefined when it has no usable value. */
export function resolveReference(ref: ChartReference, parameters: Parameter[] = []):
    { value: number; to?: number; label?: string } | undefined {
  const param = (name?: string) => {
    const p = name ? parameters.find((item) => item.name === name && item.kind === "number") : undefined;
    return p && Number.isFinite(Number(p.value)) ? Number(p.value) : undefined;
  };
  const value = param(ref.param) ?? ref.value;
  const to = param(ref.to_param) ?? ref.to;
  if (value === undefined || !Number.isFinite(value)) return undefined;
  return { value, ...(to !== undefined && Number.isFinite(to) ? { to } : {}), label: ref.label };
}

/** Drop reference bindings to a removed parameter (the references keep their last values). */
export function unbindChartParameter(charts: ChartSpec[], name: string, last?: number): ChartSpec[] {
  return charts.map((chart) => !chart.references?.some((r) => r.param === name || r.to_param === name) ? chart : {
    ...chart, references: chart.references.map((r) => {
      const next = { ...r };
      if (r.param === name) { delete next.param; next.value = last ?? r.value; }
      if (r.to_param === name) { delete next.to_param; next.to = last ?? r.to; }
      return next;
    }).filter((r) => r.value !== undefined || r.param !== undefined),
  });
}

