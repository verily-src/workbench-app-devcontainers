export type TableSourceKind = "aurora" | "postgres" | "s3" | "bq" | "catalog" | "athena";

export interface Source {
  kind: TableSourceKind;
  id: string;
  label: string;
  omop?: { cdm_schema: string; vocab_schema: string | null; version: string | null; persons: number;
          /** Every CDM schema in the database; cdm_schema above is the default. */
          cdm_schemas?: { cdm_schema: string; persons: number | null }[] };
  uuid?: string;
  read_only?: boolean;
}

export interface TableInfo {
  name: string;
  table?: string;
  schema?: string;
  detail: string;
  sql?: string | null;
  /** Planner estimate for database tables (never a full COUNT). */
  rows?: number;
  rows_estimated?: boolean;
  /** On-disk size: table + indexes + TOAST for databases, object size for files. */
  bytes?: number;
  columns?: number;
  /** Last ANALYZE time (databases). */
  analyzed?: string;
  /** Last modified time (files). */
  modified?: string;
}

export interface ColumnProfile {
  name: string;
  profile_sampled?: boolean;
  filter_kind: "categorical" | "range" | "date" | "none";
  dtype: string;
  /** Earliest/latest date (YYYY-MM-DD) for date columns. */
  min_date?: string;
  max_date?: string;
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
  filter_kind: "categorical" | "range" | "date" | "none" | null;
}

export type DateUnit = "day" | "week" | "month" | "year";

export interface Filter {
  column: string;
  kind: "categorical" | "range" | "date" | "any";
  values?: string[];
  min?: number;
  max?: number;
  /** kind "date": YYYY-MM-DD bounds (end inclusive), or the last N units. */
  start?: string;
  end?: string;
  last?: number;
  unit?: DateUnit;
  /** kind "any": rows matching every filter of at least one group (OR of ANDs). */
  groups?: Filter[][];
  /** Bounds that follow a tab parameter; min/max/start/end hold its current value. */
  param?: ParamBinding;
}

export interface ParamBinding { min?: string; max?: string; start?: string; end?: string }

/** A named value filters can follow (index_date, min_age, …). */
export interface Parameter { name: string; kind: "number" | "date"; value: number | string }

export interface AxisFormat { decimals?: number; unit?: string; percent?: boolean }
export interface ChartReference { axis?: "x" | "y"; value?: number; param?: string; to?: number; to_param?: string; label?: string }

export interface AxisSettings {
  label?: string;
  scale?: "linear" | "log";
  min?: number;
  max?: number;
  /** Display-only number format for a value axis, its tooltips and labels. */
  format?: AxisFormat;
}

/** Fields of a joined result: dropped and renamed after joining. */
export interface JoinOutput { exclude?: string[]; rename?: Record<string, string> }

/** How a chart is drawn; the data (kind) stays the same, so no requery. */
export type ChartStyle = "bar" | "column" | "line" | "area" | "pie" | "donut";

/** The Marks menu choice (what the user picked); kind/style hold what it draws. */
export type MarkType = "automatic" | "bar" | "column" | "line" | "area" | "pie" | "donut"
  | "circle" | "density" | "map" | "box";
/** Mark settings: series color, mark size, and value labels. */
export interface ChartMarks { color?: string; size?: "s" | "l"; labels?: boolean; stack?: boolean }

export type MeasureAgg = "count" | "count_distinct" | "sum" | "mean" | "median" | "min" | "max";
/** What each bar or point measures; count (the default) keeps the all-vs-selected overlay. */
export interface ChartMeasure { agg: MeasureAgg; column?: string | null }

export interface ChartSpec {
  kind: "bar" | "histogram" | "scatter" | "heatmap" | "map" | "box";
  mark?: MarkType;
  marks?: ChartMarks;
  /** bar kind: bar (default), column, line, area, pie, donut. histogram: column (default), line, area. */
  style?: ChartStyle;
  x: string;
  y?: string;
  wide?: boolean;
  title?: string;
  x_axis?: AxisSettings;
  y_axis?: AxisSettings;
  /** Data-affecting (bar kind): the measure, and a field that splits it into series. */
  measure?: ChartMeasure;
  series?: string;
  /** Display only: reference lines (value) and bands (value to `to`); a param follows a number parameter. */
  references?: ChartReference[];
}

export interface BarDatum { category: string; all: number; selected: number }
export interface PersonBarDatum { category: string; value: number | null }
/** One value per series (ChartResult.series), in the same order. */
export interface SeriesBarDatum { category: string; values: (number | null)[] }
export interface HistDatum { lo: number; hi: number; all: number; selected: number }
/** One box: quartiles, 1.5 IQR whiskers (low/high), extremes and the outlier count. category is null when ungrouped. */
export interface BoxDatum { category: string | null; n: number; min: number; q1: number; median: number; q3: number;
  max: number; low: number; high: number; outliers: number }

export interface ChartResult {
  kind: string;
  x: string;
  y?: string;
  sampled?: boolean;
  measure?: ChartMeasure;
  series_column?: string;
  series?: string[];
  /** Labels of the folded "Other" category and series (measured bar results). */
  other_category?: string;
  other_series?: string;
  data: BarDatum[] | PersonBarDatum[] | SeriesBarDatum[] | HistDatum[] | BoxDatum[] | number[][] | [string, string, number][];
}

export interface QueryResult {
  total: number;
  filtered: number;
  entity?: { column: string; total: number; filtered: number } | null;
  scope: "database" | "loaded";
  sampled?: boolean;
  cache?: { hit: boolean; as_of: string; ttl_seconds: number };
  columns?: ColumnProfile[];
  charts: (ChartResult | null)[];
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

export interface GrainDefinition {
  entity: "person" | "sample" | "variant" | "event" | "summary" | "other";
  keys: string[];
}
export interface GrainInfo {
  definition: GrainDefinition | null;
  persistent: boolean;
  missing_columns: string[];
  source_ref?: SourceRef;
}
export interface GrainCheck extends GrainInfo {
  status: "empty" | "unique_non_null" | "violated";
  rows: number; distinct_keys: number; null_key_rows: number; duplicate_key_rows: number;
  scope: "database" | "loaded" | "sample"; checked_at: string;
}
export interface PerformanceSummary {
  scope: string; retention_days: number; max_events: number; dropped_events_since_restart: number;
  groups: {event: string; name: string; count: number; failed: number;
           p95_ms: number | null; p50_ms?: number | null; max_ms?: number | null}[];
  /** App-wide dashboard query cache counters since the app started. */
  cache?: {hits: number; misses: number; hit_rate: number | null; entries: number;
           bytes: number; max_entries: number; max_bytes: number};
}
export type SourceRef = ({ grain?: GrainDefinition } & (
  | { kind: "materialized"; resource_id: string; materialized_id: string;
      settings?: ColumnSetting[] }
  | { kind: "omop_cohort"; resource_id: string; spec: OmopSpec;
      membership_mode: "live"; name?: string; settings?: ColumnSetting[];
      /** CDM schema when the database has several; omitted = default schema. */
      cdm_schema?: string }
  | { kind: "sql"; resource_id: string; sql: string; name?: string }
  | { kind: TableSourceKind; resource_id: string;
      table: string; schema?: string; uuid?: string; settings?: ColumnSetting[] }
  | { kind: "derived"; base: SourceRef; spec: DerivedSpec;
      settings?: ColumnSetting[] }
  | { kind: "group_summary"; base: SourceRef; filters?: Filter[];
      spec: { group_by: string[]; measure?: string | null };
      settings?: ColumnSetting[] }
  | { kind: "join"; base: SourceRef; allow_loaded?: boolean;
      base_filters?: JoinFilter[]; output?: JoinOutput; steps: {
      source: SourceRef; how: JoinHow; conditions: JoinCondition[];
      columns: string[] | null; alias: string; filters?: JoinFilter[];
    }[] }));

export interface SavedViewInfo {
  name: string;
  materialized_sources: number;
  refreshed_at: string | null;
  refresh_mode?: string | null;
}

export interface SavedViewEntry extends SavedViewInfo {
  kind: "aurora" | "s3";
  resource_id: string;
  store_label: string;
  /** Latest published revision; null or absent for an unpublished draft. */
  published_revision?: number | null;
  published_at?: string | null;
  /** True when the draft differs from the latest published revision. */
  draft_changed?: boolean | null;
  /** Revisions could not be read; the view may still be published. */
  publication_unknown?: boolean;
}

/** An immutable published revision of a saved view. */
export interface ViewRevision {
  name: string;
  revision: number;
  published_at: string | null;
  published_by: string | null;
  note: string | null;
}

export interface SavedViewStoreError {
  kind: "aurora" | "s3";
  resource_id: string;
  label: string;
  error: string;
}

export interface SavedViewList {
  pending?: { kind: string; resource_id: string; label: string }[];
  views: SavedViewEntry[];
  unavailable: SavedViewStoreError[];
}

export interface SavedViewJob {
  materialized_sources?: number;
  job_id: string;
  status: "queued" | "running" | "complete" | "failed";
  name: string;
  completed_sources: number;
  total_sources: number;
  error?: string | null;
}

/** Schema metadata for SQL editor autocomplete (GET /api/sql/completions). */
export interface SqlCompletions {
  resource_id: string;
  schemas: { name: string; omop?: { role: "cdm" | "vocabulary"; vocab_schema?: string | null; default?: boolean } }[];
  tables: { schema: string; name: string; kind: string; omop?: boolean;
    columns: { name: string; type: string }[] }[];
  column_count: number;
  truncated: boolean;
  limits: { tables: number; columns: number };
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

export type JoinFilterOp = "=" | "!=" | "<" | "<=" | ">" | ">=" | "in" | "not in"
  | "is null" | "is not null" | "contains";
export type JoinFilterValue = string | number | boolean;

/** A constant-value filter on one join input, applied before joining. */
export interface JoinFilter {
  column: string;
  op: JoinFilterOp;
  value?: JoinFilterValue | JoinFilterValue[] | null;
}

export interface JoinStep {
  right_id: string;
  how: JoinHow;
  conditions: JoinCondition[];
  columns: string[] | null;
  alias: string;
  /** Filters on this step's table, applied before it is joined. */
  filters?: JoinFilter[];
}

export type JoinEngine = "aurora" | "duckdb";

export interface JoinStepStats {
  right_rows: number;
  rows: number;
  truncated: boolean;
  rows_before: number;
  growth: number | null;
  fanout: boolean;
  /** Rows are PostgreSQL planner estimates, not counts. */
  estimated?: boolean;
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
  /** Final rows ÷ base rows across all steps. */
  growth_total?: number;
  /** growth_total crossed the warning threshold (10×). */
  large_growth?: boolean;
}

export interface JoinConditionCheck { problem: string | null; note: string | null }

export interface JoinValidation {
  ok: boolean;
  engine: JoinEngine;
  engine_reason: string;
  generated_sql?: { engine: JoinEngine; sql: string; display_sql?: string; copyable_sql?: string;
    copyable_sql_error?: string | null;
    parameters: Record<string, unknown>; staged_inputs?: string[] } | null;
  capped_inputs: string[];
  problems: string[];
  base_filters?: { problem: string | null }[];
  steps: { problems: string[]; notes: string[]; conditions: JoinConditionCheck[];
    filters?: { problem: string | null }[] }[];
}

export interface JoinPreview extends Omit<JoinStats, "base_rows" | "rows" | "total_rows"> {
  base_rows: number | null;
  rows: number | null;
  total_rows: number | null;
  sample_only?: boolean;
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

export interface SourceInfo {
  format: "vcf";
  reference: string | null;
  sample_count: number;
  calls: number;
  source_resource_id: string;
  source_path: string;
  object_version: string | null;
  object_etag: string | null;
  note: string;
}

export interface Dataset {
  id: string;
  /** Set on tabs opened from a published saved-view revision (viewer mode). */
  publishedRevision?: number;
  title: string;
  source: string;
  sourceRef?: SourceRef;
  sourceInfo?: SourceInfo | null;
  entityColumn?: string;
  queryScope?: "database" | "loaded";
  refreshNonce?: number;
  refreshing?: boolean;
  queryLoading?: boolean;
  queryError?: string;
  columns: ColumnProfile[];
  filters: Filter[];
  charts: ChartSpec[];
  cohorts?: Cohort[];
  page: number;
  sort?: { column: string; direction: "asc" | "desc" };
  result?: QueryResult;
  chat?: ChatMsg[];
  chatSessionId?: string;
  filterAskHistory?: FilterAskHistoryEntry[];
  groupSummary?: { group_by: string[]; measure: string | null };
  parameters?: Parameter[];
  /** Charts per row: 0 = auto (fill the screen), 1–4 = fixed equal columns. */
  chartColumns?: 0 | 1 | 2 | 3 | 4;
  /** Set when this tab is a saved extract table; null once checked and it isn't. */
  extract?: ExtractInfo | null;
  /** A Refresh extract job is running for this tab. */
  extractRefreshing?: boolean;
}

export interface ExtractInfo {
  table: string;
  title: string;
  rows: number;
  created_at: string;
  refreshed_at: string;
  /** False when its inputs (for example an upload) can't be reopened. */
  refreshable: boolean;
  identity_verified?: boolean;
  identity_token?: string;
  /** The source recipe it was built from (join or SQL); Data Builder reopens it to edit. */
  recipe?: SourceRef | null;
  /** Scheduled refresh; null when off. Times are UTC ISO strings. */
  schedule?: ExtractSchedule | null;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_run_status?: "running" | "ok" | "failed" | "skipped" | null;
  last_run_error?: string | null;
}

/** weekday: 0 = Monday … 6 = Sunday; hour/minute are wall-clock time in tz. */
export interface ExtractSchedule {
  every: "off" | "hourly" | "daily" | "weekly";
  minute?: number;
  hour?: number;
  weekday?: number;
  tz?: string;
}

export type OmopDomain = "condition" | "drug" | "procedure" | "measurement"
  | "observation" | "visit" | "device" | "death";
export interface OmopInfo {
  cdm: boolean;
  cdm_schema?: string;
  default_cdm_schema?: string;
  cdm_schemas?: { cdm_schema: string; vocab_schema: string | null; persons: number | null;
                  default: boolean }[];
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
