export interface CohortDimension {
  column: string;
  definition: string;
  values: string[];
  data_type: string;
}

export interface CohortTable {
  fq_table: string;
  business_name: string;
  entity_anchor: string;
  entity_type: string;
  dimensions: CohortDimension[];
  joinable_tables: string[];
}

export interface CohortDimensionsResponse {
  tables: CohortTable[];
}

export interface CohortFilter {
  column: string;
  operator: string;
  value: string;
}

export interface CohortJoin {
  target_table: string;
  join_column: string;
  filters: CohortFilter[];
}

export interface CohortRequest {
  base_table: string;
  entity_column: string;
  filters: CohortFilter[];
  joins: CohortJoin[];
  mode: "count" | "preview";
}

export interface CohortCountResult {
  sql: string;
  count: number;
}

export interface CohortPreviewResult {
  sql: string;
  columns: { name: string; type: string }[];
  rows: unknown[][];
  row_count: number;
}

export interface TermFilterRow {
  concept_key: string;
  fq_table: string;
  column: string;
  operator: string;
  value: string;
}

export interface TerminologyCohortRequest {
  filters: TermFilterRow[];
  mode: "count" | "preview";
}

export interface NLCohortRequest {
  query: string;
  mode: "generate" | "execute";
}

export interface NLCohortResult {
  sql: string;
  explanation: string;
  count?: number;
  preview_sql?: string;
  columns?: { name: string; type: string }[];
  rows?: unknown[][];
  row_count?: number;
}
