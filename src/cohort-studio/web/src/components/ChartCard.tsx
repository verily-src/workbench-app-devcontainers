import * as echarts from "echarts";
import { useEffect, useRef } from "react";
import { getPalette, type Palette } from "../palette";
import type { BarDatum, ChartResult, ChartSpec, HistDatum } from "../types";

const INK_SOFT = "#5f6368";
const GRID_LINE = "#e8eaed";
const FONT = "Inter, sans-serif";

const AXIS = {
  axisLine: { show: false },
  axisTick: { show: false },
  axisLabel: { color: INK_SOFT, fontFamily: FONT, fontSize: 11 },
  splitLine: { lineStyle: { color: GRID_LINE } },
};

function barOption(data: BarDatum[], pal: Palette): echarts.EChartsOption {
  const cats = data.map((d) => d.category);
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "value", ...AXIS },
    yAxis: { type: "category", data: cats, ...AXIS,
             splitLine: { show: false } },
    tooltip: { trigger: "axis", axisPointer: { type: "none" } },
    series: [
      { type: "bar", name: "all", data: data.map((d) => d.all),
        itemStyle: { color: pal.muted, borderRadius: 3 }, barWidth: "62%",
        emphasis: { itemStyle: { color: pal.muted } } },
      { type: "bar", name: "selected", data: data.map((d) => d.selected),
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
  result?: ChartResult;
  palette: string;
  onTapCategory: (column: string, value: string) => void;
  onToggleWide: () => void;
  onClose: () => void;
}

export function ChartCard({ spec, result, palette, onTapCategory,
                            onToggleWide, onClose }: Props) {
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
        option = barOption(result.data as BarDatum[], pal);
        break;
      case "histogram":
        option = histogramOption(result.data as HistDatum[], pal);
        break;
      case "scatter":
        option = scatterOption(result.data as number[][],
                               spec.x, spec.y ?? "", pal);
        break;
      case "heatmap":
        option = heatmapOption(result.data as [string, string, number][], pal);
        break;
      default:
        return;
    }
    chart.current.setOption(option, true);
    chart.current.off("click");
    if (result.kind === "bar") {
      const bars = result.data as BarDatum[];
      chart.current.on("click", (params) => {
        const cat = bars[params.dataIndex]?.category;
        if (cat && cat !== "Other") onTapCategory(spec.x, cat);
      });
    }
  }, [result, spec, pal, onTapCategory]);

  const height = result?.kind === "bar"
    ? Math.min(Math.max(170, (result.data.length as number) * 26 + 60), 430)
    : 240;

  return (
    <div className={`chart-card${spec.wide ? " wide" : ""}`}>
      <div className="head">
        <span className="title">
          {spec.x}{spec.y ? ` × ${spec.y}` : ""}
        </span>
        <button className="quiet" title="Toggle width"
                onClick={onToggleWide}>⤢</button>
        <button className="quiet" title="Remove chart"
                onClick={onClose}>✕</button>
      </div>
      <div ref={ref} style={{ width: "100%", height }} />
    </div>
  );
}
