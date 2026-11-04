// Tree-shaken ECharts: register only what the dashboard draws. Importing the
// whole "echarts" package put ~1 MB in the dataset view chunk.
import * as echarts from "echarts/core";
import { BarChart, HeatmapChart, ScatterChart } from "echarts/charts";
import { GeoComponent, GridComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([BarChart, HeatmapChart, ScatterChart, GeoComponent, GridComponent,
  TooltipComponent, VisualMapComponent, CanvasRenderer]);

export { echarts };
export type { EChartsOption } from "echarts";
export type { EChartsType as ECharts } from "echarts/core";
