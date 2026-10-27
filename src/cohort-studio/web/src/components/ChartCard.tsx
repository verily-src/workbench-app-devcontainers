import "./ChartCard.css";
import * as echarts from "echarts";
import { useEffect, useRef, useState } from "react";
import { getPalette, type Palette } from "../palette";
import type { BarDatum, PersonBarDatum, ChartResult, ChartSpec, HistDatum } from "../types";

const INK_SOFT = "#5f6368";
const GRID_LINE = "#e8eaed";
const FONT = "Inter, sans-serif";

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

function barOption(data: (BarDatum | PersonBarDatum)[], pal: Palette, compactCategoryLabels = false, ink = INK_SOFT, grid = GRID_LINE): echarts.EChartsOption {
  const axis = AXIS(ink, grid);
  const cats = data.map((d) => d.category);
  const singleSeries = data.length > 0 && "value" in data[0];
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "value", ...axis },
    yAxis: { type: "category", data: cats, ...axis,
             ...(compactCategoryLabels ? { axisLabel: { ...axis.axisLabel, width: 140, overflow: "truncate" as const } } : {}),
             splitLine: { show: false } },
    tooltip: { trigger: "axis", axisPointer: { type: "none" },
      ...(compactCategoryLabels ? { formatter: (items: unknown) => {
        const item = Array.isArray(items) ? items[0] as { axisValue?: string; value?: number } : items as { axisValue?: string; value?: number };
        return `${item?.axisValue ?? ""}<br/>persons: ${item?.value ?? ""}`;
      } } : {}) },
    series: singleSeries ? [
      { type: "bar", name: "persons", data: data.map((d) =>
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

function histogramOption(data: HistDatum[], pal: Palette, ink = INK_SOFT, grid = GRID_LINE): echarts.EChartsOption {
  const axis = AXIS(ink, grid);
  const labels = data.map((d) => `${trim(d.lo)}–${trim(d.hi)}`);
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: labels, ...axis,
             axisLabel: { ...axis.axisLabel, interval: 5 },
             splitLine: { show: false } },
    yAxis: { type: "value", ...axis },
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
                       pal: Palette, ink = INK_SOFT, grid = GRID_LINE): echarts.EChartsOption {
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
                       pal: Palette, ink = INK_SOFT, grid = GRID_LINE): echarts.EChartsOption {
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

const trim = (n: number) => (Math.abs(n) >= 100 ? n.toFixed(0)
  : Math.round(n * 100) / 100).toString();

interface Props {
  spec: ChartSpec;
  columnLabels?: Record<string, string>;
  result?: ChartResult;
  palette: string;

  kinds: ChartSpec["kind"][];
  onTapCategory: (column: string, value: string) => void;
  onChangeKind: (kind: ChartSpec["kind"]) => void;
  onToggleWide: () => void;
  onClose: () => void;
  onRename?: (title: string) => void;
  readOnly?: boolean;
  compactCategoryLabels?: boolean;
}

export function ChartCard({ spec, result, palette, kinds, onTapCategory,
                            columnLabels = {}, onChangeKind, onToggleWide,
                            onClose, onRename, readOnly = false, compactCategoryLabels = false }: Props) {
  const pal = getPalette(palette);
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts>();
  const [themeVersion, setThemeVersion] = useState(0);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

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
    const chartPalette: Palette = dark
      ? { ...pal, accent: lighten(pal.accent, 0.35),
          muted: styles.getPropertyValue("--chart-muted").trim() || pal.muted,
          ramp: ramp.length === 4 ? ramp : pal.ramp }
      : pal;
    let option: echarts.EChartsOption;
    switch (result.kind) {
      case "bar":
        option = barOption(result.data as (BarDatum | PersonBarDatum)[], chartPalette, compactCategoryLabels, ink, grid);
        break;
      case "histogram":
        option = histogramOption(result.data as HistDatum[], chartPalette, ink, grid);
        break;
      case "scatter":
        option = scatterOption(result.data as number[][],
                               columnLabels[spec.x] ?? spec.x,
                               columnLabels[spec.y ?? ""] ?? spec.y ?? "", chartPalette, ink, grid);
        break;
      case "heatmap":
        option = heatmapOption(result.data as [string, string, number][], chartPalette, ink, grid);
        break;
      default:
        return;
    }
    chart.current.setOption(option, true);
    chart.current.off("click");
    if (result.kind === "bar" && !readOnly) {
      const bars = result.data as BarDatum[];
      chart.current.on("click", (params) => {
        const cat = bars[params.dataIndex]?.category;
        if (cat && cat !== "Other") onTapCategory(spec.x, cat);
      });
    }
  }, [result, spec, pal, onTapCategory, columnLabels, readOnly, compactCategoryLabels, themeVersion]);

  const height = result?.kind === "bar"
    ? Math.min(Math.max(170, (result.data.length as number) * 26 + 60), 430)
    : 240;

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
          {spec.title || `${columnLabels[spec.x] ?? spec.x}${spec.y
            ? ` × ${columnLabels[spec.y] ?? spec.y}` : ""}`}
        </span>}
        {result?.sampled && <span className="badge" title="This chart uses sampled data">
          Sampled
        </span>}
        {!readOnly && kinds.length > 1 && (
          <select className="chart-kind" title="Chart type" value={spec.kind}
                  onChange={(e) =>
                    onChangeKind(e.target.value as ChartSpec["kind"])}>
            {kinds.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        )}
        {onRename && <button className="quiet" title="Rename chart" aria-label="Rename chart"
          onClick={() => { setTitleDraft(spec.title || columnLabels[spec.x] || spec.x); setEditingTitle(true); }}>✎</button>}
        {!readOnly && <>
          <button className="quiet" title="Toggle width"
                  onClick={onToggleWide}>⤢</button>
          <button className="quiet" title="Remove chart"
                  onClick={onClose}>✕</button>
        </>}
      </div>
      <div ref={ref} className="chart-plot" style={{ width: "100%", height }} />
    </div>
  );
}
