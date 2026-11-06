import type { ChartSpec, ChartStyle } from "./types";

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
  if (spec.kind === "histogram") return { x: false, y: true };
  if (spec.kind === "bar") {
    if (style === "pie" || style === "donut") return { x: false, y: false };
    return style === "bar" ? { x: true, y: false } : { x: false, y: true };
  }
  return { x: false, y: false };
}

