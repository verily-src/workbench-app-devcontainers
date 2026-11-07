// Tree-shaken ECharts: register only what the dashboard draws. Importing the
// whole "echarts" package put ~1 MB in the dataset view chunk.
import * as echarts from "echarts/core";
import { BarChart, BoxplotChart, HeatmapChart, LineChart, PieChart, ScatterChart } from "echarts/charts";
import { GeoComponent, GridComponent, LegendComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent,
  VisualMapComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([BarChart, BoxplotChart, HeatmapChart, LineChart, PieChart, ScatterChart, GeoComponent, GridComponent,
  LegendComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent, VisualMapComponent, CanvasRenderer]);

// Lets browser tests map chart coordinates to screen pixels (e.g. under zoom).
(window as unknown as { __studioEcharts?: typeof echarts }).__studioEcharts = echarts;

/** ECharts reads pointer positions from event.offsetX/Y. Under the app's CSS
 *  `zoom` (UI scale "comfortable"/"large") Chrome reports those in zoomed
 *  pixels while the chart lays out in unzoomed ones, so clicks and tooltips
 *  land ~12% off. Rescale them before ECharts sees the event. */
const POINTER_EVENTS = ["click", "dblclick", "contextmenu", "mousedown", "mouseup", "mousemove", "mouseout",
  "mouseover", "pointerdown", "pointerup", "pointermove", "pointerout", "pointerover", "wheel"];
export function correctZoomedPointer(host: HTMLElement): () => void {
  const fix = (event: Event) => {
    const e = event as MouseEvent;
    if (typeof e.offsetX !== "number" || !host.offsetWidth) return;
    const scale = host.getBoundingClientRect().width / host.offsetWidth;
    if (!Number.isFinite(scale) || Math.abs(scale - 1) < 0.001) return;
    const x = e.offsetX / scale;
    const y = e.offsetY / scale;
    Object.defineProperty(e, "offsetX", { configurable: true, get: () => x });
    Object.defineProperty(e, "offsetY", { configurable: true, get: () => y });
  };
  POINTER_EVENTS.forEach((name) => host.addEventListener(name, fix, { capture: true }));
  return () => POINTER_EVENTS.forEach((name) => host.removeEventListener(name, fix, { capture: true }));
}

export { echarts };
export type { EChartsOption } from "echarts";
export type { EChartsType as ECharts } from "echarts/core";
