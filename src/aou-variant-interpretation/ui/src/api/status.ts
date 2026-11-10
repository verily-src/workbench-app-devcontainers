import { apiFetch } from "./client";

export interface TableStatus {
  /** As "project.dataset.table". */
  table: string;
  accessible: boolean;
  /** Why the check failed; null when accessible. */
  detail?: string | null;
}

export interface BigQueryStatus {
  /** True when every table is accessible. */
  accessible: boolean;
  tables: TableStatus[];
}

export const fetchStatus = () => apiFetch<BigQueryStatus>("/status");
