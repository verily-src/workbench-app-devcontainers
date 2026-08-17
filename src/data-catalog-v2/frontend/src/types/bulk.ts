export type BulkMode = "technical" | "semantic" | "both";

export interface BulkStartResponse {
  batch_id: string;
  total: number;
  mode: string;
}

export interface TableJobStatus {
  fq_table: string;
  technical: string;
  semantic: string;
  tech_error: string;
  sem_error: string;
  tech_duration_s: number;
  sem_duration_s: number;
}

export interface BulkPhaseSummary {
  done: number;
  failed: number;
  skipped: number;
  running: number;
}

export interface BulkError {
  table: string;
  phase: string;
  error: string;
}

export interface BulkWarning {
  table: string;
  phase: string;
  message: string;
}

export interface BulkStatusResponse {
  batch_id: string;
  status: string;
  mode: string;
  total: number;
  technical: BulkPhaseSummary;
  semantic: BulkPhaseSummary;
  errors: BulkError[];
  warnings: BulkWarning[];
  started_at: string;
  finished_at: string;
  tables: TableJobStatus[];
}
