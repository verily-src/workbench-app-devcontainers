import * as echarts from "echarts";
import { useEffect, useRef } from "react";
import { getPalette, type Palette } from "../palette";
import type { BarDatum, PersonBarDatum, ChartResult, ChartSpec, HistDatum } from "../types";

const INK_SOFT = "#5f6368";
const GRID_LINE = "#e8eaed";
const FONT = "Inter, sans-serif";

const AXIS = {
  axisLine: { show: false },
  axisTick: { show: false },
  axisLabel: { color: INK_SOFT, fontFamily: FONT, fontSize: 11 },
  splitLine: { lineStyle: { color: GRID_LINE } },
};

function barOption(data: (BarDatum | PersonBarDatum)[], pal: Palette, compactCategoryLabels = false): echarts.EChartsOption {
  const cats = data.map((d) => d.category);
  const singleSeries = data.length > 0 && "value" in data[0];
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "value", ...AXIS },
    yAxis: { type: "category", data: cats, ...AXIS,
             ...(compactCategoryLabels ? { axisLabel: { ...AXIS.axisLabel, width: 140, overflow: "truncate" as const } } : {}),
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

function histogramOption(data: HistDatum[], pal: Palette): echarts.EChartsOption {
  const labels = data.map((d) => `${trim(d.lo)}–${trim(d.hi)}`);
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: labels, ...AXIS,
             axisLabel: { ...AXIS.axisLabel, interval: 5 },
             splitLine: { show: false } },
    yAxis: { type: "value", ...AXIS },
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
                       pal: Palette): echarts.EChartsOption {
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "value", name: x, ...AXIS },
    yAxis: { type: "value", name: y, ...AXIS },
    tooltip: { trigger: "item" },
    series: [{ type: "scatter", data, symbolSize: 6,
               itemStyle: { color: pal.accent, opacity: 0.45 } }],
  };
}

function heatmapOption(data: [string, string, number][],
                       pal: Palette): echarts.EChartsOption {
  const xs = [...new Set(data.map((d) => d[0]))];
  const ys = [...new Set(data.map((d) => d[1]))];
  const max = Math.max(1, ...data.map((d) => d[2]));
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: xs, ...AXIS,
             axisLabel: { ...AXIS.axisLabel, rotate: 45 },
             splitLine: { show: false } },
    yAxis: { type: "category", data: ys, ...AXIS,
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
  readOnly?: boolean;
  compactCategoryLabels?: boolean;
}

export function ChartCard({ spec, result, palette, kinds, onTapCategory,
                            columnLabels = {}, onChangeKind, onToggleWide,
                            onClose, readOnly = false, compactCategoryLabels = false }: Props) {
  const pal = getPalette(palette);
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts>();

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current);
    const observer = new ResizeObserver(() => chart.current?.resize());
    observer.observe(ref.current);
    return () => { observer.disconnect(); chart.current?.dispose(); };
  }, []);

  useEffect(() => {
    if (!chart.current || !result) return;
    let option: echarts.EChartsOption;
    switch (result.kind) {
      case "bar":
        option = barOption(result.data as (BarDatum | PersonBarDatum)[], pal, compactCategoryLabels);
        break;
      case "histogram":
        option = histogramOption(result.data as HistDatum[], pal);
        break;
      case "scatter":
        option = scatterOption(result.data as number[][],
                               columnLabels[spec.x] ?? spec.x,
                               columnLabels[spec.y ?? ""] ?? spec.y ?? "", pal);
        break;
      case "heatmap":
        option = heatmapOption(result.data as [string, string, number][], pal);
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
  }, [result, spec, pal, onTapCategory, columnLabels, readOnly, compactCategoryLabels]);

  const height = result?.kind === "bar"
    ? Math.min(Math.max(170, (result.data.length as number) * 26 + 60), 430)
    : 240;

  return (
    <div className={`chart-card${spec.wide ? " wide" : ""}`}>
      <div className="head">
        <span className="title">
          {columnLabels[spec.x] ?? spec.x}{spec.y
            ? ` × ${columnLabels[spec.y] ?? spec.y}` : ""}
        </span>
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
        {!readOnly && <>
          <button className="quiet" title="Toggle width"
                  onClick={onToggleWide}>⤢</button>
          <button className="quiet" title="Remove chart"
                  onClick={onClose}>✕</button>
        </>}
      </div>
      <div ref={ref} style={{ width: "100%", height }} />
    </div>
  );
}
