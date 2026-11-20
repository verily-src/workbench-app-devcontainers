export interface ApiConfig {
  billing_project: string;
  data_project: string;
  data_project_name?: string;
  profile_bucket: string;
  gemini_model: string | null;
  configured: boolean;
}

export interface WorkspaceInfo {
  id: string;
  name: string;
  gcp_project: string;
  role: string;
}

export interface WorkspaceDataset {
  id: string;
  project_id: string;
  dataset_id: string;
  num_tables: number | null;
  type: string;
  location: string;
}

export type ProfilingState = "none" | "running" | "available" | "failed";

export interface TableProfiling {
  technical: ProfilingState;
  semantic: ProfilingState;
}

export interface CatalogTable {
  fq_table: string;
  project_id: string;
  dataset_id: string;
  table_id: string;
  row_count: number | null;
  size_bytes: number | null;
  table_type: string;
  column_count: number;
  creation_time?: string | null;
  profiling: TableProfiling;
  business_name?: string | null;
  table_definition?: string | null;
}

export interface CatalogDataset {
  dataset_id: string;
  tables: CatalogTable[];
}

export interface CatalogResponse {
  project_id: string;
  profile_bucket: string;
  datasets: CatalogDataset[];
}
