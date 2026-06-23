export type SampleRow = Record<string, unknown> & { id: number };

export interface FilterOption {
  value: string;
  label: string;
  count: number;
}

export interface RangeFilter {
  min: number | null;
  max: number | null;
}

export type FiltersResponse = Record<string, FilterOption[] | RangeFilter>;

export interface Counts {
  samples: number;
  subjects?: number;
  fastq_pairs?: number;
}

export type FilterState = Record<string, string[] | number | null>;

// --- Chart types ---

export type FieldDataType = "categorical" | "numeric";

export type ChartType =
  | "bar" | "pie"
  | "histogram" | "boxplot" | "kde"
  | "scatter" | "cat-boxplot" | "heatmap";

export interface FieldMeta {
  key: string;
  label: string;
  dataType: FieldDataType;
}

export interface ChartConfig {
  id: string;
  fieldKey: string;
  chartType: ChartType;
  field2Key?: string;
}

export interface KdePoint {
  x: number;
  density: number;
}

export interface HistogramBin {
  binStart: number;
  binEnd: number;
  label: string;
  count: number;
}

export interface BoxPlotStats {
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
  outliers: number[];
  count: number;
}

export function buildFieldMeta(mappings: ColumnMapping[]): FieldMeta[] {
  return mappings
    .filter((m) => m.filter !== "none")
    .map((m) => ({
      key: m.column,
      label: m.label,
      dataType: (m.filter === "range" ? "numeric" : "categorical") as FieldDataType,
    }));
}

export const DEFAULT_CHART_TYPE: Record<FieldDataType, ChartType> = {
  categorical: "bar",
  numeric: "histogram",
};

export const CHART_TYPES_FOR: Record<FieldDataType, ChartType[]> = {
  categorical: ["bar", "pie"],
  numeric: ["histogram", "kde", "boxplot"],
};

export const CHART_TYPES_2D: ChartType[] = ["scatter", "cat-boxplot", "heatmap"];

// --- Filter state ---

import type { ColumnMapping } from "./api";

export function buildEmptyFilters(mappings: ColumnMapping[]): FilterState {
  const state: FilterState = {};
  for (const m of mappings) {
    if (m.filter === "categorical") state[m.column] = [];
    if (m.filter === "range") {
      state[`${m.column}_min`] = null;
      state[`${m.column}_max`] = null;
    }
  }
  return state;
}
