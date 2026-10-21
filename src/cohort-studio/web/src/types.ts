export interface Source {
  kind: "aurora" | "s3" | "bq" | "catalog";
  id: string;
  label: string;
  omop?: { cdm_schema: string; vocab_schema: string | null; version: string | null; persons: number };
  uuid?: string;
}

export interface TableInfo {
  name: string;
  detail: string;
  sql?: string | null;
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
  capped_inputs: string[];
  problems: string[];
  steps: { problems: string[]; notes: string[]; conditions: JoinConditionCheck[] }[];
}

export interface JoinPreview extends JoinStats {
  columns: string[];
  sample: unknown[][];
}

export interface JoinSuggestion {
  left: string;
  right: string;
  overlap: number;
  score: number;
}

export interface Cohort {
  name: string;
  filters: Filter[];
}

export interface Dataset {
  id: string;
  title: string;
  source: string;
  sourceRef?: { kind: string; resource_id: string; table: string;
                uuid?: string };
  columns: ColumnProfile[];
  filters: Filter[];
  charts: ChartSpec[];
  cohorts?: Cohort[];
  page: number;
  result?: QueryResult;
  chat?: ChatMsg[];
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
