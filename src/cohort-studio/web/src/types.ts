export interface Source {
  kind: "aurora" | "s3" | "bq" | "catalog";
  id: string;
  label: string;
  omop?: { cdm_schema: string; vocab_schema: string | null; version: string | null; persons: number };
  uuid?: string;
}

export interface TableInfo {
  name: string;
  table?: string;
  schema?: string;
  detail: string;
  sql?: string | null;
}

export interface ColumnProfile {
  name: string;
  filter_kind: "categorical" | "range" | "none";
  dtype: string;
  logical_type?: "number" | "text" | null;
  label?: string;
  values?: string[];
  min?: number;
  max?: number;
}

export interface ColumnSetting {
  name: string;
  logical_type: "number" | "text" | null;
  label?: string;
  filter_kind: "categorical" | "range" | "none" | null;
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
export interface PersonBarDatum { category: string; value: number }
export interface HistDatum { lo: number; hi: number; all: number; selected: number }

export interface ChartResult {
  kind: string;
  x: string;
  y?: string;
  sampled?: boolean;
  data: BarDatum[] | PersonBarDatum[] | HistDatum[] | number[][] | [string, string, number][];
}

export interface QueryResult {
  total: number;
  filtered: number;
  entity?: { column: string; total: number; filtered: number } | null;
  scope: "database" | "loaded";
  sampled?: boolean;
  cache?: { hit: boolean; as_of: string; ttl_seconds: number };
  columns?: ColumnProfile[];
  charts: ChartResult[];
  rows: { page: number; page_size: number; columns: string[]; data: unknown[][] };
}

export interface DerivedSpec {
  op: "bin" | "formula" | "map";
  name: string;
  column?: string;
  breaks?: number[];
  labels?: string[];
  left?: string;
  operator?: "+" | "-" | "*" | "/";
  right?: string;
  mapping?: Record<string, string>;
  default?: string;
}

export type SourceRef =
  | { kind: "omop_cohort"; resource_id: string; spec: OmopSpec;
      membership_mode: "live"; name?: string; settings?: ColumnSetting[] }
  | { kind: "sql"; resource_id: string; sql: string; name?: string }
  | { kind: "aurora" | "s3" | "bq" | "catalog"; resource_id: string;
      table: string; schema?: string; uuid?: string; settings?: ColumnSetting[] }
  | { kind: "derived"; base: SourceRef; spec: DerivedSpec;
      settings?: ColumnSetting[] }
  | { kind: "join"; base: SourceRef; allow_loaded?: boolean; steps: {
      source: SourceRef; how: JoinHow; conditions: JoinCondition[];
      columns: string[] | null; alias: string;
    }[] };

export interface SavedViewEntry {
  kind: "aurora" | "s3";
  resource_id: string;
  store_label: string;
  name: string;
}

export interface SavedViewStoreError {
  kind: "aurora" | "s3";
  resource_id: string;
  label: string;
  error: string;
}

export interface SavedViewList {
  views: SavedViewEntry[];
  unavailable: SavedViewStoreError[];
}


export interface SqlPreview {
  source_ref: Extract<SourceRef, { kind: "sql" }>;
  columns: string[];
  sample: unknown[][];
  rows: number;
  truncated: boolean;
}

export interface ChatMsg {
  role: "user" | "assistant";
  content: string;
  message_id?: number;
  actions?: string[];
}

export type JoinHow = "left" | "inner" | "right" | "full" | "semi" | "anti";
export type JoinOp = "=" | "!=" | "<" | "<=" | ">" | ">=";

export interface JoinCondition { left: string; op: JoinOp; right: string }

export interface JoinStep {
  right_id: string;
  how: JoinHow;
  conditions: JoinCondition[];
  columns: string[] | null;
  alias: string;
}

export type JoinEngine = "aurora" | "duckdb";

export interface JoinStepStats {
  right_rows: number;
  rows: number;
  truncated: boolean;
  rows_before: number;
  growth: number | null;
  fanout: boolean;
}

export interface JoinStats {
  engine: JoinEngine;
  base_rows: number;
  rows: number;
  total_rows: number;
  truncated: boolean;
  steps: JoinStepStats[];
  notes: string[];
  capped_inputs: string[];
}

export interface JoinConditionCheck { problem: string | null; note: string | null }

export interface JoinValidation {
  ok: boolean;
  engine: JoinEngine;
  engine_reason: string;
  generated_sql?: { engine: JoinEngine; sql: string;
    parameters: Record<string, unknown>; staged_inputs?: string[] } | null;
  capped_inputs: string[];
  problems: string[];
  steps: { problems: string[]; notes: string[]; conditions: JoinConditionCheck[] }[];
}

export interface JoinPreview extends JoinStats {
  columns: string[];
  sample: unknown[][];
  sample_truncated?: boolean;
}

export interface JoinSuggestion {
  left: string;
  right: string;
  overlap: number;
  score: number;
}

export interface JoinRecommendation {
  keys: { left: string; right: string }[];
  method: "foreign_key" | "exact_name" | "jev";
  evidence: string[];
  confidence: number | null;
}

export interface Cohort {
  name: string;
  filters: Filter[];
}

export interface FilterAskHistoryEntry {
  question: string;
  answer?: string;
  error?: string;
}

export interface Dataset {
  id: string;
  title: string;
  source: string;
  sourceRef?: SourceRef;
  entityColumn?: string;
  queryScope?: "database" | "loaded";
  refreshNonce?: number;
  refreshing?: boolean;
  columns: ColumnProfile[];
  filters: Filter[];
  charts: ChartSpec[];
  cohorts?: Cohort[];
  page: number;
  result?: QueryResult;
  chat?: ChatMsg[];
  chatSessionId?: string;
  filterAskHistory?: FilterAskHistoryEntry[];
}

export type OmopDomain = "condition" | "drug" | "procedure" | "measurement"
  | "observation" | "visit" | "device" | "death";
export interface OmopInfo {
  cdm: boolean;
  cdm_schema?: string;
  vocab_schema?: string | null;
  version?: string | null;
  tables?: { name: string; schema: string; domain: string; rows: number; approx: boolean }[];
}
export interface OmopConcept {
  concept_id: number;
  concept_name: string;
  vocabulary_id: string;
  domain_id: string;
  persons: number | null;
}
export interface OmopCriterion {
  domain: OmopDomain;
  concept_ids: number[];
  descendants?: boolean;
  exclude?: boolean;
  min_count?: number;
  start?: string;
  end?: string;
  value_min?: number;
  value_max?: number;
  index_relation?: "before" | "after";
}
export interface OmopSpec {
  criteria: OmopCriterion[];
  require_observation: boolean;
  demographics: { gender_concept_ids?: number[]; age_min?: number; age_max?: number;
    year_of_birth_min?: number; year_of_birth_max?: number };
}
export interface OmopCount {
  persons: number;
  total_persons: number;
  attrition: { label: string; persons: number }[];
}
export interface OmopSummary {
  scope: "database";
  persons: number;
  total_persons: number;
  attrition: { label: string; persons: number }[];
  charts: {
    gender: { category: string; concept_id: number | null; persons: number }[];
    age_at_index: { category: string; lo: number | null; hi: number | null; persons: number }[];
    domains: { domain: OmopDomain; label: string;
      concepts: { concept_id: number; label: string; persons: number }[] }[];
  };
}
