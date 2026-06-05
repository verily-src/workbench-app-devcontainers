export interface SampleRow {
  id: number;
  subject_id: string;
  gtex_sample_id: string;
  specimen_id: string | null;
  tissue_type: string;
  tissue_type_detail: string;
  autolysis_score: string | null;
  current_material_type: string | null;
  sample_collection_kit: string | null;
  rin_number: number | null;
  total_ischemic_time: number | null;
  paxgene_time: number | null;
  tissue_location: string | null;
  bss_collection_site: string | null;
  original_material_type: string | null;
  srr_id: string | null;
  fastq1_path: string | null;
  fastq2_path: string | null;
}

export interface FilterOption {
  value: string;
  label: string;
  count: number;
}

export interface RangeFilter {
  min: number | null;
  max: number | null;
}

export interface FiltersResponse {
  tissue_type: FilterOption[];
  tissue_type_detail: FilterOption[];
  autolysis_score: FilterOption[];
  current_material_type: FilterOption[];
  sample_collection_kit: FilterOption[];
  rin_number: RangeFilter;
  total_ischemic_time: RangeFilter;
  paxgene_time: RangeFilter;
}

export interface Counts {
  samples: number;
  subjects: number;
  fastq_pairs: number;
}

export interface FilterState {
  tissue_type: string[];
  tissue_type_detail: string[];
  autolysis_score: string[];
  current_material_type: string[];
  sample_collection_kit: string[];
  rin_number_min: number | null;
  rin_number_max: number | null;
  total_ischemic_time_min: number | null;
  total_ischemic_time_max: number | null;
  paxgene_time_min: number | null;
  paxgene_time_max: number | null;
}

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

export const FIELD_META: FieldMeta[] = [
  { key: "tissue_type", label: "Tissue Type", dataType: "categorical" },
  { key: "tissue_type_detail", label: "Tissue Detail", dataType: "categorical" },
  { key: "autolysis_score", label: "Autolysis Score", dataType: "categorical" },
  { key: "current_material_type", label: "Material Type", dataType: "categorical" },
  { key: "sample_collection_kit", label: "Collection Kit", dataType: "categorical" },
  { key: "rin_number", label: "RIN Number", dataType: "numeric" },
  { key: "total_ischemic_time", label: "Ischemic Time", dataType: "numeric" },
  { key: "paxgene_time", label: "PAXgene Time", dataType: "numeric" },
];

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

export const EMPTY_FILTERS: FilterState = {
  tissue_type: [],
  tissue_type_detail: [],
  autolysis_score: [],
  current_material_type: [],
  sample_collection_kit: [],
  rin_number_min: null,
  rin_number_max: null,
  total_ischemic_time_min: null,
  total_ischemic_time_max: null,
  paxgene_time_min: null,
  paxgene_time_max: null,
};
