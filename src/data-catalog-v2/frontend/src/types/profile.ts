export interface TechColumn {
  name: string;
  data_type: string;
  nullable?: boolean;
  null_count?: number;
  null_percent?: number;
  distinct_count?: number;
  top_values?: string[];
  value_counts?: Record<string, number>;
  string_stats?: { min_length?: number; max_length?: number; avg_length?: number };
  numeric_stats?: { min?: number; max?: number; median?: number; stddev?: number };
  pattern?: string;
  anomalies?: string[];
}

export interface TechProfile {
  table: string;
  row_count: number;
  size_bytes?: number | null;
  profiled_at: string;
  validation: { status: string; anomalies?: string[]; warnings?: string[] };
  columns: TechColumn[];
}

export interface TerminologyBinding {
  system: string;
  code: string;
  display: string;
}

export interface ConceptBinding {
  system: string;
  code: string;
  display: string;
  confidence: string;
}

export interface CodeSystemBinding {
  system: string;
  display: string;
  confidence: string;
}

export interface StructuralLink {
  source_column: string;
  target_table: string;
  target_column: string;
  link_type: "entity_key" | "foreign_key" | "shared_dimension" | "temporal" | string;
  cardinality: string;
  confidence: string;
}

export interface PrimaryKeyInfo {
  columns: string[];
  pk_type: "single" | "composite" | "none" | "";
  confidence: "high" | "medium" | "low";
}

export interface SemanticDomainInfo {
  primary: string;
  sub_domain: string;
}

export interface SemColumn {
  name: string;
  definition: string;
  terminology_bindings: TerminologyBinding[];
  concept_binding?: ConceptBinding | null;
  code_system_binding?: CodeSystemBinding | null;
  sensitivity: string;
  join_paths: string[];
  confidence: string;
  unit_of_measure: string;
  measurement_method?: string;
  value_set_binding?: string[];
}

export interface ColumnMeta {
  fq_column: string;
  column?: string;
  fq_table?: string;
  definition?: string;
  measurement_method?: string;
}

export interface TerminologyEntry {
  system: string;
  code: string;
  display: string;
  concept_key: string;
  source_columns: string[];
  columns_meta: ColumnMeta[];
  tables_count: number;
  columns_count: number;
}

export interface TerminologyResponse {
  entries: TerminologyEntry[];
  total: number;
  updated_at: string;
}

export interface TerminologySlimEntry {
  system: string;
  code: string;
  display: string;
  concept_key: string;
  source_columns: string[];
  tables_count: number;
  columns_count: number;
}

export interface TerminologySlimResponse {
  entries: TerminologySlimEntry[];
  total: number;
  updated_at: string;
}

export interface SemProfile {
  table: string;
  profiled_at: string;
  model_used: string;
  business_name?: string;
  table_definition?: string;
  primary_key?: PrimaryKeyInfo;
  granularity?: string;
  semantic_domain?: SemanticDomainInfo;
  entity_anchor?: string;
  entity_type?: string;
  cohort_dimensions?: string[];
  structural_links?: StructuralLink[];
  validation: { status: string; issues?: string[]; warnings?: string[] };
  columns: SemColumn[];
}
