export interface Source {
  kind: "aurora" | "s3" | "bq";
  id: string;
  label: string;
}

export interface TableInfo {
  name: string;
  detail: string;
}

export interface ColumnProfile {
  name: string;
  filter_kind: "categorical" | "range" | "none";
  dtype: string;
  values?: string[];
  min?: number;
  max?: number;
}

export interface Filter {
  column: string;
  kind: "categorical" | "range";
  values?: string[];
  min?: number;
  max?: number;
}

export interface ChartSpec {
  kind: "bar" | "histogram" | "scatter" | "heatmap";
  x: string;
  y?: string;
  wide?: boolean;
}

export interface BarDatum { category: string; all: number; selected: number }
export interface HistDatum { lo: number; hi: number; all: number; selected: number }

export interface ChartResult {
  kind: string;
  x: string;
  y?: string;
  data: BarDatum[] | HistDatum[] | number[][] | [string, string, number][];
}

export interface QueryResult {
  total: number;
  filtered: number;
  charts: ChartResult[];
  rows: { page: number; page_size: number; columns: string[]; data: unknown[][] };
}

export interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  actions?: string[];
}

export interface Dataset {
  id: string;
  title: string;
  source: string;
  columns: ColumnProfile[];
  filters: Filter[];
  charts: ChartSpec[];
  page: number;
  result?: QueryResult;
  chat?: ChatMsg[];
}
