import "./ChartCard.css";
import { echarts } from "../echarts";
import type { EChartsOption, ECharts } from "../echarts";
import { useEffect, useRef, useState } from "react";
import { getPalette, type Palette } from "../palette";
import type { AxisSettings, BarDatum, BoxDatum, PersonBarDatum, ChartMeasure, ChartReference, ChartResult, ChartSpec, ChartStyle,
  ColumnProfile, Parameter,
  HistDatum, SeriesBarDatum } from "../types";
import { AxisEditor } from "./AxisEditor";
import { MarksMenu } from "./MarksMenu";
import { Popover } from "./Popover";
import { formatNumber, numericAxes, referenceAxes, resolveReference, styleOf } from "../chartStyles";
import type { ChartMarks, MarkType } from "../types";

const INK_SOFT = "#5f6368";
const GRID_LINE = "#e8eaed";
const FONT = "Inter, sans-serif";
let worldMap: Promise<void> | undefined;
function loadWorldMap(): Promise<void> {
  if (!worldMap) worldMap = fetch("/maps/world.geojson").then(response => {
    if (!response.ok) throw new Error("Map unavailable");
    return response.json();
  }).then(data => { echarts.registerMap("cohort-world", data); }).catch(error => { worldMap = undefined; throw error; });
  return worldMap;
}

function lighten(color: string, amount: number): string {
  const value = color.match(/^#([0-9a-f]{6})$/i)?.[1];
  if (!value) return color;
  const channels = [0, 2, 4].map((offset) =>
    Math.round(parseInt(value.slice(offset, offset + 2), 16) * (1 - amount) + 255 * amount));
  return `#${channels.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;
}

const AXIS = (ink = INK_SOFT, grid = GRID_LINE) => ({
  axisLine: { show: false },
  axisTick: { show: false },
  axisLabel: { color: ink, fontFamily: FONT, fontSize: 11 },
  splitLine: { lineStyle: { color: grid } },
});

function barOption(data: (BarDatum | PersonBarDatum)[], pal: Palette, compactCategoryLabels = false, ink = INK_SOFT, grid = GRID_LINE,
                   valueName = "persons"): EChartsOption {
  const axis = AXIS(ink, grid);
  const cats = data.map((d) => d.category);
  const singleSeries = data.length > 0 && "value" in data[0];
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "value", ...axis, axisLabel: { ...axis.axisLabel, hideOverlap: true,
      formatter: (value: number) => compactNumber(value) } },
    yAxis: { type: "category", data: cats, ...axis,
             ...(compactCategoryLabels ? { axisLabel: { ...axis.axisLabel, width: 140, overflow: "truncate" as const } } : {}),
             splitLine: { show: false } },
    tooltip: { trigger: "axis", axisPointer: { type: "none" },
      ...(compactCategoryLabels ? { formatter: (items: unknown) => {
        const item = Array.isArray(items) ? items[0] as { axisValue?: string; value?: number } : items as { axisValue?: string; value?: number };
        return `${item?.axisValue ?? ""}<br/>${valueName}: ${item?.value ?? ""}`;
      } } : {}) },
    series: singleSeries ? [
      { type: "bar", name: valueName, data: data.map((d) =>
        "value" in d ? d.value : d.selected),
        itemStyle: { color: pal.accent, borderRadius: 3 }, barWidth: "62%" },
    ] : [
      { type: "bar", name: "all", data: data.map((d) => "all" in d ? d.all : 0),
        itemStyle: { color: pal.muted, borderRadius: 3 }, barWidth: "62%",
        emphasis: { itemStyle: { color: pal.muted } } },
      { type: "bar", name: "selected", data: data.map((d) => "selected" in d ? d.selected : 0),
        itemStyle: { color: pal.accent, borderRadius: 3 }, barWidth: "62%",
        barGap: "-100%", cursor: "pointer" },
    ],
  };
}

const compactNumber = (value: number) => new Intl.NumberFormat("en", { notation: "compact", maximumSignificantDigits: 4 }).format(value);

function histogramOption(data: HistDatum[], pal: Palette, ink = INK_SOFT, grid = GRID_LINE): EChartsOption {
  const axis = AXIS(ink, grid);
  const labels = data.map((d) => `${trim(d.lo)}–${trim(d.hi)}`);
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: labels, ...axis,
             axisLabel: { ...axis.axisLabel, interval: "auto", hideOverlap: true,
               formatter: (_value: string, index: number) => compactNumber(data[index]?.lo ?? 0) },
             splitLine: { show: false } },
    yAxis: { type: "value", ...axis, axisLabel: { ...axis.axisLabel, hideOverlap: true,
      formatter: (value: number) => compactNumber(value) } },
    tooltip: { trigger: "axis", axisPointer: { type: "none" } },
    series: [
      { type: "bar", name: "all", data: data.map((d) => d.all),
        itemStyle: { color: pal.muted }, barWidth: "78%",
        emphasis: { itemStyle: { color: pal.muted } } },
      { type: "bar", name: "selected", data: data.map((d) => d.selected),
        itemStyle: { color: pal.accent }, barWidth: "78%", barGap: "-100%" },
    ],
  };
}

function scatterOption(data: number[][], x: string, y: string,
                       pal: Palette, ink = INK_SOFT, grid = GRID_LINE): EChartsOption {
  const axis = AXIS(ink, grid);
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "value", name: x, ...axis },
    yAxis: { type: "value", name: y, ...axis },
    tooltip: { trigger: "item" },
    series: [{ type: "scatter", data, symbolSize: 6,
               itemStyle: { color: pal.accent, opacity: 0.45 } }],
  };
}

function heatmapOption(data: [string, string, number][],
                       pal: Palette, ink = INK_SOFT, grid = GRID_LINE): EChartsOption {
  const axis = AXIS(ink, grid);
  const xs = [...new Set(data.map((d) => d[0]))];
  const ys = [...new Set(data.map((d) => d[1]))];
  const max = Math.max(1, ...data.map((d) => d[2]));
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: xs, ...axis,
             axisLabel: { ...axis.axisLabel, rotate: 45 },
             splitLine: { show: false } },
    yAxis: { type: "category", data: ys, ...axis,
             splitLine: { show: false } },
    tooltip: {},
    visualMap: { show: false, min: 0, max,
                 inRange: { color: pal.ramp } },
    series: [{ type: "heatmap", data }],
  };
}

// ---- Chart styles: other ways to draw the same bar/histogram counts ----

// A validated categorical order (fixed, never cycled) for pie and donut slices;
// beyond 6 slices the tail folds into "Other".
const SLICE_COLORS = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"],
};
const MAX_SLICES = 6;

type Counts = { cats: string[]; all: number[] | null; selected: (number | null)[]; name?: string };

function barCounts(data: (BarDatum | PersonBarDatum)[]): Counts {
  const single = data.length > 0 && "value" in data[0];
  return {
    cats: data.map((d) => d.category),
    all: single ? null : data.map((d) => ("all" in d ? d.all : 0)),
    selected: data.map((d) => ("value" in d ? d.value : d.selected)),
  };
}

/** Lines and areas read left to right, so categories go in natural order ("Other" last). */
function naturalOrder(counts: Counts): Counts {
  const idx = counts.cats.map((_, i) => i);
  const numeric = counts.cats.every((c) => c === "Other" || (c.trim() !== "" && !Number.isNaN(Number(c))));
  idx.sort((a, b) => {
    const ca = counts.cats[a], cb = counts.cats[b];
    if (ca === "Other") return 1;
    if (cb === "Other") return -1;
    return numeric ? Number(ca) - Number(cb) : ca.localeCompare(cb, undefined, { numeric: true });
  });
  return { cats: idx.map((i) => counts.cats[i]), all: counts.all && idx.map((i) => counts.all![i]),
           selected: idx.map((i) => counts.selected[i]), name: counts.name };
}

function seriesOption(counts: Counts, style: "column" | "line" | "area", pal: Palette, ink: string, grid: string,
                      labelFor?: (index: number) => string): EChartsOption {
  const axis = AXIS(ink, grid);
  const many = counts.cats.length > 40;
  const valueAxis = { type: "value" as const, ...axis, axisLabel: { ...axis.axisLabel, hideOverlap: true,
    formatter: (value: number) => compactNumber(value) } };
  const categoryAxis = { type: "category" as const, data: counts.cats, ...axis, boundaryGap: style === "column",
    axisLabel: { ...axis.axisLabel, hideOverlap: true, interval: "auto" as const,
      ...(labelFor ? { formatter: (_v: string, i: number) => labelFor(i) } : {}) },
    splitLine: { show: false } };
  const line = (name: string, data: (number | null)[], color: string, faint: boolean) => ({
    type: "line" as const, name, data, color, showSymbol: !many && counts.cats.length <= 24, symbolSize: 8,
    lineStyle: { width: 2, color, cap: "round" as const, join: "round" as const, opacity: faint ? 0.9 : 1 },
    itemStyle: { color },
    ...(style === "area" ? { areaStyle: { color, opacity: faint ? 0.18 : 0.12 } } : {}),
    emphasis: { focus: "series" as const },
  });
  const bar = (name: string, data: (number | null)[], color: string, overlay: boolean) => ({
    type: "bar" as const, name, data, barMaxWidth: 24, itemStyle: { color, borderRadius: [4, 4, 0, 0] },
    ...(overlay ? { barGap: "-100%" } : {}), emphasis: { itemStyle: { color } },
  });
  const series = style === "column"
    ? [...(counts.all ? [bar("all", counts.all, pal.muted, false)] : []),
       bar(counts.all ? "selected" : counts.name ?? "persons", counts.selected, pal.accent, Boolean(counts.all))]
    : [...(counts.all ? [line("all", counts.all, pal.muted, true)] : []),
       line(counts.all ? "selected" : counts.name ?? "persons", counts.selected, pal.accent, false)];
  return {
    grid: { left: 8, right: 16, top: counts.all && style !== "column" ? 28 : 8, bottom: 8, containLabel: true },
    xAxis: categoryAxis, yAxis: valueAxis,
    tooltip: { trigger: "axis", axisPointer: { type: style === "column" ? "shadow" : "line" } },
    ...(counts.all && style !== "column" ? { legend: { top: 0, right: 8, itemWidth: 14, itemHeight: 2,
      textStyle: { color: ink, fontFamily: FONT, fontSize: 11 } } } : {}),
    series: series as EChartsOption["series"],
  };
}

const OTHER_COLOR = { light: "#bdc1c6", dark: "#5f6368" };

/** Category order for drawing: lines and areas read left to right ("Other" last). */
function categoryOrder(cats: string[], natural: boolean): number[] {
  const idx = cats.map((_, i) => i);
  if (!natural) return idx;
  const numeric = cats.every((c) => c === "Other" || (c.trim() !== "" && !Number.isNaN(Number(c))));
  return idx.sort((a, b) => {
    const ca = cats[a], cb = cats[b];
    if (ca === "Other") return 1;
    if (cb === "Other") return -1;
    return numeric ? Number(ca) - Number(cb) : ca.localeCompare(cb, undefined, { numeric: true });
  });
}

/** One series per value of the Split by field, in the fixed categorical order. */
function splitOption(result: ChartResult, style: ChartStyle, dark: boolean, ink: string, grid: string,
                     surface: string, stack: boolean, format: (value: number) => string): { option: EChartsOption; cats: string[] } {
  const data = result.data as SeriesBarDatum[];
  const names = result.series ?? [];
  const axis = AXIS(ink, grid);
  const order = categoryOrder(data.map((d) => d.category), style === "line" || style === "area");
  const cats = order.map((i) => data[i].category);
  const colors = SLICE_COLORS[dark ? "dark" : "light"];
  const horizontal = style === "bar";
  const bars = style === "bar" || style === "column" || style === "pie" || style === "donut";
  const radius = horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0];
  const many = cats.length > 24;
  const series = names.map((name, s) => {
    const color = name === result.other_series ? OTHER_COLOR[dark ? "dark" : "light"] : colors[s % colors.length];
    const values = order.map((i) => data[i].values[s] ?? null);
    return bars
      ? { type: "bar" as const, name, data: values, barMaxWidth: 24, ...(stack ? { stack: "total" } : {}),
          itemStyle: { color, borderRadius: stack ? 0 : radius, ...(stack ? { borderColor: surface, borderWidth: 1 } : {}) },
          emphasis: { focus: "series" as const } }
      : { type: "line" as const, name, data: values, color, connectNulls: false,
          showSymbol: !many, symbolSize: 8, ...(stack && style === "area" ? { stack: "total" } : {}),
          lineStyle: { width: 2, color, cap: "round" as const, join: "round" as const }, itemStyle: { color },
          ...(style === "area" ? { areaStyle: { color, opacity: stack ? 0.3 : 0.1 } } : {}),
          emphasis: { focus: "series" as const } };
  });
  const valueAxis = { type: "value" as const, ...axis, axisLabel: { ...axis.axisLabel, hideOverlap: true,
    formatter: (value: number) => format(value) } };
  const categoryAxis = { type: "category" as const, data: cats, ...axis, boundaryGap: bars,
    axisLabel: { ...axis.axisLabel, hideOverlap: true, interval: "auto" as const }, splitLine: { show: false } };
  return {
    cats,
    option: {
      grid: { left: 8, right: 16, top: names.length > 1 ? 30 : 8, bottom: 8, containLabel: true },
      xAxis: horizontal ? valueAxis : categoryAxis,
      yAxis: horizontal ? categoryAxis : valueAxis,
      tooltip: { trigger: "axis", axisPointer: { type: bars ? "shadow" : "line" },
        valueFormatter: (value: unknown) => (value === null || value === undefined ? "—" : format(Number(value))) },
      ...(names.length > 1 ? { legend: { type: "scroll", top: 0, left: 8, right: 8, itemWidth: 14, itemHeight: 8,
        textStyle: { color: ink, fontFamily: FONT, fontSize: 11 } } } : {}),
      series: series as EChartsOption["series"],
    },
  };
}

const AGG_LABEL: Record<string, string> = {
  count: "Rows", count_distinct: "Distinct", sum: "Sum of", mean: "Mean", median: "Median",
  min: "Minimum", max: "Maximum",
};
/** "Mean HbA1c", "Distinct patient_id"; undefined for plain row counts. */
export function measureLabel(measure: ChartMeasure | undefined, labels: Record<string, string>): string | undefined {
  if (!measure || measure.agg === "count" || !measure.column) return undefined;
  return `${AGG_LABEL[measure.agg]} ${labels[measure.column] ?? measure.column}`;
}

function pieOption(counts: Counts, donut: boolean, dark: boolean, ink: string, surface: string): { option: EChartsOption; cats: string[]; folded: boolean } {
  const rows = counts.cats.map((name, i) => ({ name, value: counts.selected[i] ?? 0 }))
    .filter((r) => r.value > 0);
  const named = rows.filter((r) => r.name !== "Other").sort((a, b) => b.value - a.value);
  const other = rows.filter((r) => r.name === "Other").reduce((sum, r) => sum + r.value, 0);
  const head = named.length + (other ? 1 : 0) > MAX_SLICES ? named.slice(0, MAX_SLICES - 1) : named;
  const tail = named.slice(head.length).reduce((sum, r) => sum + r.value, 0) + other;
  const colors = SLICE_COLORS[dark ? "dark" : "light"];
  const slices = [...head.map((r, i) => ({ ...r, itemStyle: { color: colors[i] } })),
    ...(tail ? [{ name: "Other", value: tail, itemStyle: { color: dark ? "#5f6368" : "#bdc1c6" } }] : [])];
  return {
    cats: slices.map((s) => s.name),
    folded: named.length > head.length,
    option: {
      tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
      legend: { type: "scroll", orient: "vertical", right: 4, top: "middle",
        textStyle: { color: ink, fontFamily: FONT, fontSize: 11 } },
      series: [{ type: "pie", radius: donut ? ["48%", "72%"] : "72%", center: ["38%", "52%"],
        data: slices, avoidLabelOverlap: true,
        itemStyle: { borderColor: surface, borderWidth: 2, borderRadius: donut ? 4 : 0 },
        label: { color: ink, fontFamily: FONT, fontSize: 11, formatter: "{d}%" },
        labelLine: { length: 6, length2: 6 } }],
    },
  };
}

const SIZE_SCALE = { s: 0.7, l: 1.4 } as const;
const scalePct = (value: unknown, k: number) =>
  typeof value === "string" && value.endsWith("%") ? `${Math.min(95, Math.round(parseFloat(value) * k))}%` : value;

/** Mark settings applied to any built option: size scales bars, lines and dots;
 *  labels print values in text ink (never the series color). */
function applyMarks(option: EChartsOption, marks: ChartMarks | undefined, ink: string, horizontal: boolean,
                    format: (value: number) => string = compactNumber) {
  if (!marks || !option.series) return;
  const k = marks.size ? SIZE_SCALE[marks.size] : 1;
  const list = (Array.isArray(option.series) ? option.series : [option.series]) as Record<string, any>[];
  for (const s of list) {
    if (s.type === "bar") {
      if (s.barWidth) s.barWidth = scalePct(s.barWidth, k);
      if (s.barMaxWidth) s.barMaxWidth = Math.round(s.barMaxWidth * k);
    } else if (s.type === "line") {
      s.lineStyle = { ...(s.lineStyle ?? {}), width: 2 * k };
      s.symbolSize = Math.round(8 * k);
    } else if (s.type === "scatter") {
      s.symbolSize = Math.round((typeof s.symbolSize === "number" ? s.symbolSize : 6) * k);
    } else if (s.type === "pie") {
      if (marks.labels) s.label = { ...(s.label ?? {}), formatter: "{b} · {d}%" };
      continue;
    }
    if (marks.labels && s.name !== "all" && (s.type === "bar" || s.type === "line")) {
      s.label = { show: true, position: horizontal ? "right" : "top", color: ink, fontFamily: FONT, fontSize: 10,
        formatter: (p: { value: number | null }) => (p.value === null || p.value === undefined ? "" : format(Number(p.value))) };
    }
  }
}

/** Dim the categories outside a chart's selection (bar, line and pie data share the category order). */
function highlightSelection(option: EChartsOption, cats: string[], selection: string[]) {
  const chosen = new Set(selection);
  if (!chosen.size || !cats.some((c) => chosen.has(c)) || !option.series) return;
  const list = (Array.isArray(option.series) ? option.series : [option.series]) as Record<string, any>[];
  for (const s of list) {
    if (!Array.isArray(s.data) || !["bar", "line", "pie"].includes(s.type)) continue;
    s.data = s.data.map((d: unknown, i: number) => {
      if (cats[i] === undefined) return d;
      const item = d !== null && typeof d === "object" && !Array.isArray(d) ? d as Record<string, any> : { value: d };
      return { ...item, itemStyle: { ...(item.itemStyle ?? {}), opacity: chosen.has(cats[i]) ? 1 : 0.3 } };
    });
  }
}

const NO_SELECTION: string[] = [];

const escapeHtml = (text: string) => text.replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

/** Box plots: whiskers at the furthest values within 1.5 IQR; extremes and outliers in the tooltip. */
function boxOption(data: BoxDatum[], field: string, pal: Palette, ink: string, grid: string,
                   format: (value: number) => string): EChartsOption {
  const axis = AXIS(ink, grid);
  const cats = data.map((d) => d.category ?? field);
  return {
    grid: { left: 8, right: 16, top: 12, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: cats, ...axis, axisLabel: { ...axis.axisLabel, hideOverlap: true, interval: "auto" },
             splitLine: { show: false } },
    yAxis: { type: "value", scale: true, ...axis, axisLabel: { ...axis.axisLabel, hideOverlap: true,
      formatter: (value: number) => format(value) } },
    tooltip: { trigger: "item", formatter: (p: unknown) => {
      const d = data[(p as { dataIndex: number }).dataIndex];
      if (!d) return "";
      // The tooltip is HTML: escape group names and formatted units (they come from the data and the user).
      const f = (value: number) => escapeHtml(format(value));
      return [`<b>${escapeHtml(cats[(p as { dataIndex: number }).dataIndex])}</b>`, `median ${f(d.median)}`,
        `quartiles ${f(d.q1)} – ${f(d.q3)}`, `whiskers ${f(d.low)} – ${f(d.high)}`,
        `min ${f(d.min)} · max ${f(d.max)}`,
        `${d.n.toLocaleString("en")} values${d.outliers ? ` · ${d.outliers.toLocaleString("en")} outside 1.5 IQR` : ""}`].join("<br/>");
    } },
    series: [{ type: "boxplot", name: field, data: data.map((d) => [d.low, d.q1, d.median, d.q3, d.high]),
      boxWidth: [8, 40], itemStyle: { color: lighten(pal.accent, 0.82), borderColor: pal.accent, borderWidth: 1.5 },
      emphasis: { itemStyle: { borderWidth: 2 } } }],
  };
}

type Marks = { lines: Record<string, unknown>[]; bands: Record<string, unknown>[][] };
type Placed = Marks & { bins: Marks & { lo: number; hi: number } | null; extent: { x: number[]; y: number[] } };
/** Reference lines and bands as markLine/markArea items. A histogram's x axis is a category axis
 *  of bins, so x references go on a hidden value axis spanning the bin edges (`bins`). */
function placeReferences(references: ChartReference[] | undefined, parameters: Parameter[], axes: ("x" | "y")[],
                         result: ChartResult, spec: ChartSpec): Placed {
  const placed: Placed = { lines: [], bands: [], bins: null, extent: { x: [], y: [] } };
  const hist = result.kind === "histogram" ? result.data as HistDatum[] : [];
  for (const ref of references ?? []) {
    const resolved = resolveReference(ref, parameters);
    const axis = ref.axis && axes.includes(ref.axis) ? ref.axis : axes[0];
    if (!resolved || !axis) continue;
    const fmt = (value: number) => formatNumber(value, (axis === "x" ? spec.x_axis : spec.y_axis)?.format);
    let target: Marks = placed;
    if (result.kind === "histogram" && axis === "x") {
      if (!hist.length) continue;
      placed.bins ??= { lines: [], bands: [], lo: hist[0].lo, hi: hist[hist.length - 1].hi };
      target = placed.bins;
    } else {
      placed.extent[axis].push(resolved.value, ...(resolved.to !== undefined ? [resolved.to] : []));
    }
    const key = axis === "x" ? "xAxis" : "yAxis";
    if (resolved.to === undefined) {
      target.lines.push({ name: resolved.label || fmt(resolved.value), [key]: resolved.value });
    } else {
      const [a, b] = [resolved.value, resolved.to].sort((p, q) => p - q);
      target.bands.push([{ name: resolved.label || `${fmt(a)} – ${fmt(b)}`, [key]: a }, { [key]: b }]);
    }
  }
  return placed;
}

const trim = (n: number) => (Math.abs(n) >= 100 ? n.toFixed(0)
  : Math.round(n * 100) / 100).toString();

const NO_PARAMETERS: Parameter[] = [];

interface Props {
  spec: ChartSpec;
  columnLabels?: Record<string, string>;
  result?: ChartResult;
  palette: string;

  kinds: ChartSpec["kind"][];
  /** A click on a category; `additive` (Ctrl, ⌘ or Shift) adds or removes it instead of selecting only it. */
  onTapCategory: (column: string, value: string, additive: boolean) => void;
  /** Values of this chart's field that the tab filters on (the chart's selection). */
  selection?: string[];
  onClearSelection?: () => void;
  onChangeKind: (kind: ChartSpec["kind"], style?: ChartStyle, mark?: MarkType) => void;
  onMarksChange?: (marks: ChartMarks | undefined) => void;
  onToggleWide: () => void;
  onClose: () => void;
  /** Reorder (undefined at the ends) and copy this chart. */
  onMove?: (delta: -1 | 1) => void;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
  onDuplicate?: () => void;
  onRename?: (title: string) => void;
  onAxesChange?: (x: AxisSettings, y: AxisSettings, references?: ChartReference[]) => void;
  /** Tab parameters, for reference lines that follow one. */
  parameters?: Parameter[];
  readOnly?: boolean;
  compactCategoryLabels?: boolean;
  /** The tab's fields, for the Measure and Split by controls. */
  fields?: ColumnProfile[];
  /** Data-affecting edits (measure, series), which requery. */
  onDataChange?: (changes: Partial<ChartSpec>) => void;
}

function defaultTitle(spec: ChartSpec, labels: Record<string, string>): string {
  const x = labels[spec.x] ?? spec.x;
  const measure = measureLabel(spec.measure, labels);
  const base = measure ? `${measure} by ${x}` : spec.kind === "box" && spec.y ? `${x} by ${labels[spec.y] ?? spec.y}`
    : `${x}${spec.y ? ` × ${labels[spec.y] ?? spec.y}` : ""}`;
  return spec.series ? `${base}, split by ${labels[spec.series] ?? spec.series}` : base;
}

export function ChartCard({ spec, result, palette, kinds, onTapCategory,
                            columnLabels = {}, onChangeKind, onMarksChange, onToggleWide,
                            onMove, canMoveUp = false, canMoveDown = false, onDuplicate,
                            onClose, onRename, onAxesChange, readOnly = false, compactCategoryLabels = false,
                            fields, onDataChange, parameters = NO_PARAMETERS,
                            selection = NO_SELECTION, onClearSelection }: Props) {
  const selectionKey = selection.join("\u0000");
  const pal = getPalette(palette);
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<ECharts>();
  const [themeVersion, setThemeVersion] = useState(0);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [editingAxes, setEditingAxes] = useState(false);
  const [mapStatus, setMapStatus] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    if (result?.kind !== "map") return;
    let cancelled = false;
    setMapStatus("loading");
    loadWorldMap().then(() => { if (!cancelled) setMapStatus("ready"); })
      .catch(() => { if (!cancelled) setMapStatus("error"); });
    return () => { cancelled = true; };
  }, [result?.kind]);

  useEffect(() => {
    const root = document.documentElement;
    const update = () => setThemeVersion((value) => value + 1);
    const observer = new MutationObserver(update);
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", update);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", update);
    };
  }, []);

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current);
    const observer = new ResizeObserver(() => chart.current?.resize());
    observer.observe(ref.current);
    return () => { observer.disconnect(); chart.current?.dispose(); };
  }, []);

  useEffect(() => {
    if (!chart.current || !result) return;
    const styles = getComputedStyle(document.documentElement);
    const ink = styles.getPropertyValue("--chart-ink").trim() || INK_SOFT;
    const grid = styles.getPropertyValue("--chart-grid").trim() || GRID_LINE;
    const dark = styles.colorScheme === "dark";
    const ramp = ["--chart-ramp-1", "--chart-ramp-2", "--chart-ramp-3", "--chart-ramp-4"]
      .map((name) => styles.getPropertyValue(name).trim()).filter(Boolean) as
      [string, string, string, string];
    const markColor = spec.marks?.color;
    const basePalette: Palette = markColor ? { ...pal, accent: markColor } : pal;
    const chartPalette: Palette = dark
      ? { ...basePalette, accent: lighten(basePalette.accent, markColor ? 0.15 : 0.35),
          muted: styles.getPropertyValue("--chart-muted").trim() || pal.muted,
          ramp: ramp.length === 4 ? ramp : pal.ramp }
      : basePalette;
    let option: EChartsOption;
    const style = styleOf({ kind: result.kind as ChartSpec["kind"], style: spec.style });
    let clickCats: string[] | null = null;
    const horizontal = result.kind === "bar" && style === "bar";
    const valueFormat = (horizontal ? spec.x_axis : spec.y_axis)?.format;
    // Folded groups ("Other") stand for many values, so a click never filters on them.
    const folded = new Set<string>(result.measure ? (result.other_category ? [result.other_category] : []) : ["Other"]);
    switch (result.kind) {
      case "bar": {
        const data = result.data as (BarDatum | PersonBarDatum)[];
        const surface = styles.getPropertyValue("--card").trim() || (dark ? "#1f2023" : "#ffffff");
        const valueName = measureLabel(result.measure, columnLabels);
        if (result.series) {
          const additive = !result.measure || result.measure.agg === "count" || result.measure.agg === "sum";
          const split = splitOption(result, style ?? "bar", dark, ink, grid, surface,
            Boolean(spec.marks?.stack) && additive && style !== "line", (value) => formatNumber(value, valueFormat));
          option = split.option;
          clickCats = split.cats;
        } else if (style === "pie" || style === "donut") {
          const pie = pieOption(barCounts(data), style === "donut", dark, ink, surface);
          option = pie.option;
          clickCats = pie.cats;
          if (pie.folded) folded.add("Other");   // the pie folded smaller slices into "Other"
        } else if (style === "column" || style === "line" || style === "area") {
          const base = { ...barCounts(data), name: valueName };
          const counts = style === "column" ? base : naturalOrder(base);
          option = seriesOption(counts, style, chartPalette, ink, grid);
          clickCats = counts.cats;
        } else {
          option = barOption(data, chartPalette, compactCategoryLabels, ink, grid, valueName);
          clickCats = data.map((d) => d.category);
        }
        break;
      }
      case "histogram": {
        const data = result.data as HistDatum[];
        option = style === "line" || style === "area"
          ? seriesOption({ cats: data.map((d) => `${trim(d.lo)}–${trim(d.hi)}`), all: data.map((d) => d.all),
                           selected: data.map((d) => d.selected) }, style, chartPalette, ink, grid,
                         (i) => compactNumber(data[i]?.lo ?? 0))
          : histogramOption(data, chartPalette, ink, grid);
        break;
      }
      case "scatter":
        option = scatterOption(result.data as number[][],
                               columnLabels[spec.x] ?? spec.x,
                               columnLabels[spec.y ?? ""] ?? spec.y ?? "", chartPalette, ink, grid);
        break;
      case "heatmap":
        option = heatmapOption(result.data as [string, string, number][], chartPalette, ink, grid);
        break;
      case "map":
        if (mapStatus !== "ready") return;
        option = {
          geo: { map: "cohort-world", roam: true, itemStyle: { areaColor: grid, borderColor: ink, borderWidth: 0.5 },
            emphasis: { disabled: true } },
          tooltip: { trigger: "item" },
          series: [{ type: "scatter", coordinateSystem: "geo", data: result.data as number[][],
            symbolSize: 7, itemStyle: { color: chartPalette.accent, opacity: 0.75 } }],
        };
        break;
      case "box":
        option = boxOption(result.data as BoxDatum[], columnLabels[spec.x] ?? spec.x, chartPalette, ink, grid,
          (value) => formatNumber(value, spec.y_axis?.format));
        break;
      default:
        return;
    }
    const drawn = { kind: result.kind as ChartSpec["kind"], style: spec.style };
    const refs = placeReferences(spec.references, parameters, referenceAxes(drawn), result, spec);
    const configure = (axis: unknown, settings: AxisSettings | undefined, numeric: boolean, vertical: boolean,
                       extent: number[]) => ({
      ...(axis as object),
      ...(settings?.label ? { name: settings.label, nameLocation: "middle", nameGap: vertical ? 64 : 32,
        nameTextStyle: { color: ink, fontFamily: FONT } } : {}),
      ...(numeric && settings?.scale === "log" ? { type: "log", logBase: 10 } : {}),
      ...(numeric && settings?.format ? { axisLabel: { ...((axis as { axisLabel?: object }).axisLabel ?? {}),
        formatter: (value: number) => formatNumber(value, settings.format) } } : {}),
      // Keep reference lines in view unless the user fixed the bounds.
      ...(numeric && extent.length && settings?.scale !== "log" ? {
        min: (e: { min: number; max: number }) => {
          const low = (axis as { scale?: boolean }).scale ? e.min : Math.min(0, e.min);
          const ref = Math.min(...extent);
          return ref < low ? ref - 0.05 * (Math.max(e.max, ...extent) - ref || 1) : undefined;
        },
        max: (e: { min: number; max: number }) => {
          const ref = Math.max(...extent);
          return ref > e.max ? ref + 0.05 * (ref - Math.min(e.min, ...extent) || 1) : undefined;
        } } : {}),
      ...(numeric && settings?.min !== undefined ? { min: settings.min } : {}),
      ...(numeric && settings?.max !== undefined ? { max: settings.max } : {}),
    });
    applyMarks(option, spec.marks, ink, horizontal, (value) => formatNumber(value, valueFormat));
    const hasAxes = result.kind !== "map" && option.xAxis !== undefined;
    const isValue = (axis: unknown) => (axis as { type?: string } | undefined)?.type === "value";
    if (hasAxes) {
      option.xAxis = configure(option.xAxis, spec.x_axis, isValue(option.xAxis), false, refs.extent.x) as EChartsOption["xAxis"];
      option.yAxis = configure(option.yAxis, spec.y_axis, isValue(option.yAxis), true, refs.extent.y) as EChartsOption["yAxis"];
      const label = { color: ink, fontFamily: FONT, fontSize: 10, formatter: (p: { name?: string }) => p.name ?? "" };
      const attach = (series: Record<string, unknown>, marks: { lines: unknown[]; bands: unknown[] }) => {
        if (marks.lines.length) series.markLine = { silent: true, symbol: "none", animation: false,
          lineStyle: { color: ink, width: 1, type: "solid", opacity: 0.75 },
          label: { ...label, position: "insideEndTop" }, data: marks.lines };
        if (marks.bands.length) series.markArea = { silent: true, animation: false,
          itemStyle: { color: ink, opacity: 0.08 }, label: { ...label, position: "insideTop" }, data: marks.bands };
      };
      const list = (Array.isArray(option.series) ? option.series : [option.series]) as Record<string, unknown>[];
      if (list[0]) attach(list[0], refs);
      if (refs.bins) {
        // A hidden value axis over the bin edges places x references at exact values. Line and area
        // histograms have no boundary gap: their first and last bin centers sit at the grid edges.
        const half = (result.data as HistDatum[])[0] ? ((result.data as HistDatum[])[0].hi - (result.data as HistDatum[])[0].lo) / 2 : 0;
        const centered = (option.xAxis as { boundaryGap?: boolean }).boundaryGap === false;
        option.xAxis = [option.xAxis as object, { type: "value", show: false,
          min: refs.bins.lo + (centered ? half : 0), max: refs.bins.hi - (centered ? half : 0) }] as EChartsOption["xAxis"];
        const holder: Record<string, unknown> = { type: "line", name: "references", xAxisIndex: 1, data: [], silent: true,
          tooltip: { show: false } };
        attach(holder, refs.bins);
        option.series = [...list, holder] as EChartsOption["series"];
      }
    }
    if (valueFormat && option.tooltip && !(option.tooltip as { formatter?: unknown }).formatter)
      option.tooltip = { ...(option.tooltip as object),
        valueFormatter: (value: unknown) => (value === null || value === undefined ? "—" : formatNumber(Number(value), valueFormat)) };
    if (hasAxes && (spec.x_axis?.label || spec.y_axis?.label)) option.grid = {
      ...(option.grid as object),
      left: spec.y_axis?.label ? 72 : 8, right: 16,
      bottom: spec.x_axis?.label ? 48 : 8, containLabel: true,
    };
    if (result.kind === "bar" && clickCats) highlightSelection(option, clickCats, selection);
    chart.current.setOption(option, true);
    chart.current.off("click");
    if (result.kind === "bar" && !readOnly && clickCats) {
      const cats = clickCats;
      chart.current.on("click", (params) => {
        const cat = cats[params.dataIndex];
        const native = (params.event as { event?: MouseEvent } | undefined)?.event;
        const additive = Boolean(native && (native.ctrlKey || native.metaKey || native.shiftKey));
        if (cat && !folded.has(cat)) onTapCategory(spec.x, cat, additive);
      });
    }
  }, [result, spec, pal, onTapCategory, columnLabels, readOnly, compactCategoryLabels, themeVersion, mapStatus, parameters,
      selectionKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const drawnStyle = styleOf(spec);
  const height = result?.kind === "bar" && (drawnStyle === "pie" || drawnStyle === "donut") ? 260
    : result?.kind === "bar" && drawnStyle === "bar" && result.series
    ? Math.min(Math.max(220, result.data.length * (result.series.length * 7 + 12) + 70), 600)
    : result?.kind === "bar" && drawnStyle === "bar"
    ? Math.min(Math.max(170, (result.data.length as number) * 26 + 60), 430)
    : result?.kind === "map" ? 340 : result?.kind === "box" ? 280 : 240;

  return (
    <div className={`chart-card${spec.wide ? " wide" : ""}`}>
      <div className="head">
        {editingTitle ? <input aria-label="Chart title" maxLength={120} value={titleDraft}
          autoFocus onChange={(event) => setTitleDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") { onRename?.(titleDraft.trim()); setEditingTitle(false); }
            if (event.key === "Escape") setEditingTitle(false);
          }} onBlur={() => { onRename?.(titleDraft.trim()); setEditingTitle(false); }} /> :
        <span className="title">
          {spec.title || defaultTitle(spec, columnLabels)}
        </span>}
        {result?.sampled && <span className="badge" title="This chart uses sampled data">
          Sampled
        </span>}
        {result?.kind === "bar" && selection.length > 0 && onClearSelection && !readOnly &&
          <span className="chart-selection" title={selection.join(", ")}>
            {selection.length === 1 ? selection[0] : `${selection.length} selected`}
            <button type="button" className="quiet" aria-label="Clear selection"
                    title="Clear selection (Esc)" onClick={onClearSelection}>✕</button>
          </span>}
        {!readOnly && <MarksMenu spec={spec} kinds={kinds} fields={fields} onData={onDataChange}
          onChoose={(mark, choice) => onChangeKind(choice.kind, choice.style, mark)}
          onMarks={(marks) => onMarksChange?.(Object.values(marks).some((v) => v !== undefined) ? marks : undefined)} />}
        {onRename && <button className="quiet" title="Rename chart" aria-label="Rename chart"
          onClick={() => { setTitleDraft(spec.title || columnLabels[spec.x] || spec.x); setEditingTitle(true); }}>✎</button>}
        {onAxesChange && (numericAxes(spec).x || numericAxes(spec).y || spec.kind === "heatmap") && <button type="button" className="quiet" title="Edit axes" aria-label="Edit axes"
          aria-expanded={editingAxes} onClick={() => setEditingAxes(value => !value)}>⚙</button>}
        {!readOnly && <>
          {(

            <Popover className="chart-actions" ariaLabel="Chart actions" label={<span aria-hidden>⋯</span>}>
              {(close) => <div className="popover-menu">
                <button type="button" onClick={() => { onToggleWide(); close(); }}>
                  {spec.wide ? "Make narrow" : "Make wide"}</button>
                {onMove && <button type="button" disabled={!canMoveUp}
                                   onClick={() => { onMove(-1); close(); }}>Move earlier</button>}
                {onMove && <button type="button" disabled={!canMoveDown}
                                   onClick={() => { onMove(1); close(); }}>Move later</button>}
                {onDuplicate && <button type="button" onClick={() => { onDuplicate(); close(); }}>Duplicate</button>}
              </div>}
            </Popover>
          )}
          <button className="quiet" title="Remove chart"
                  onClick={onClose}>✕</button>
        </>}
      </div>
      {result?.kind === "map" && <div className="axis-scale-note">Longitude and latitude; up to 2,000 valid points.</div>}
      {result?.kind === "map" && mapStatus === "error" && <div role="alert">Could not load the map.</div>}
      {editingAxes && onAxesChange && <AxisEditor spec={spec}
        onCancel={() => setEditingAxes(false)} parameters={parameters}
        onApply={(x, y, references) => { onAxesChange(x, y, references); setEditingAxes(false); }} />}
      {(numericAxes(spec).x && spec.x_axis?.scale === "log" ||
        numericAxes(spec).y && spec.y_axis?.scale === "log") &&
        <div className="axis-scale-note">Log scale shows positive values only.</div>}
      <div ref={ref} className="chart-plot" data-chart-style={drawnStyle ?? spec.kind}
           style={{ width: "100%", height }} />
    </div>
  );
}
