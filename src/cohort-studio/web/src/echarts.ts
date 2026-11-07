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

export { echarts };
export type { EChartsOption } from "echarts";
export type { EChartsType as ECharts } from "echarts/core";
