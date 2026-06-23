import type { Counts, FilterState, FiltersResponse, SampleRow } from "./types";

const BASE = import.meta.env.BASE_URL.replace(/\/+$/, "");

const DEFAULT_TIMEOUT_MS = 30_000;

async function fetchWithTimeout(
  input: RequestInfo | URL,
  init?: RequestInit & { timeoutMs?: number },
): Promise<Response> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...fetchInit } = init ?? {};
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...fetchInit, signal: controller.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(
        `Request timed out after ${timeoutMs / 1000} seconds. The datasource may be unreachable.`,
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

async function extractError(res: Response, fallback: string): Promise<never> {
  const body = await res.json().catch(() => null);
  throw new Error(body?.detail ?? `${fallback} (HTTP ${res.status})`);
}

function buildParams(filters: FilterState): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, val] of Object.entries(filters)) {
    if (Array.isArray(val)) {
      for (const v of val) params.append(key, v);
    } else if (val !== null) {
      params.append(key, String(val));
    }
  }
  return params;
}

export async function fetchSamples(filters: FilterState): Promise<SampleRow[]> {
  const res = await fetchWithTimeout(`${BASE}/api/samples?${buildParams(filters)}`);
  if (!res.ok) await extractError(res, "Failed to fetch samples");
  return res.json();
}

export async function fetchFilters(
  filters: FilterState,
): Promise<FiltersResponse> {
  const res = await fetchWithTimeout(`${BASE}/api/filters?${buildParams(filters)}`);
  if (!res.ok) await extractError(res, "Failed to fetch filters");
  return res.json();
}

export async function fetchCounts(filters: FilterState): Promise<Counts> {
  const res = await fetchWithTimeout(`${BASE}/api/counts?${buildParams(filters)}`);
  if (!res.ok) await extractError(res, "Failed to fetch counts");
  return res.json();
}

export async function seedData(): Promise<{ seeded: number }> {
  const res = await fetchWithTimeout(`${BASE}/api/seed`, {
    method: "POST",
    timeoutMs: 120_000,
  });
  if (!res.ok) await extractError(res, "Failed to seed data");
  return res.json();
}

export function exportUrl(filters: FilterState): string {
  return `${BASE}/api/export?${buildParams(filters)}`;
}

export interface ColumnMapping {
  column: string;
  type: string;
  filter: string;
  label: string;
}

export interface AuroraTable {
  name: string;
  type: string;
}

export async function listAuroraTables(resourceId: string): Promise<AuroraTable[]> {
  const res = await fetchWithTimeout(
    `${BASE}/api/schema/tables?resource_id=${encodeURIComponent(resourceId)}`,
    { timeoutMs: 120_000 },
  );
  if (!res.ok) await extractError(res, "Failed to list tables");
  return res.json();
}

export async function inferSchema(body: {
  source_type: "file" | "aurora";
  s3_path?: string;
  folder_id?: string;
  resource_id?: string;
  table?: string;
}): Promise<{ mappings: ColumnMapping[] }> {
  const res = await fetchWithTimeout(`${BASE}/api/schema/infer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    timeoutMs: 120_000,
  });
  if (!res.ok) await extractError(res, "Failed to infer schema");
  return res.json();
}

export async function confirmSchema(body: {
  mappings: ColumnMapping[];
  folder_id?: string;
  source_name?: string;
  table_name?: string;
}): Promise<{ confirmed: boolean; columns: number }> {
  const res = await fetchWithTimeout(`${BASE}/api/schema/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await extractError(res, "Failed to confirm schema");
  return res.json();
}

export async function fetchActiveSchema(): Promise<{ mappings: ColumnMapping[] }> {
  const res = await fetchWithTimeout(`${BASE}/api/schema/active`);
  if (!res.ok) await extractError(res, "Failed to fetch active schema");
  return res.json();
}

export interface CohortSummary {
  name: string;
  description: string;
  sampleCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface CohortFull extends CohortSummary {
  filters: FilterState;
}

export async function listCohorts(): Promise<CohortSummary[]> {
  const res = await fetchWithTimeout(`${BASE}/api/cohorts`);
  if (!res.ok) await extractError(res, "Failed to list cohorts");
  return res.json();
}

export async function getCohort(name: string): Promise<CohortFull> {
  const res = await fetchWithTimeout(`${BASE}/api/cohorts/${encodeURIComponent(name)}`);
  if (!res.ok) await extractError(res, "Failed to load cohort");
  return res.json();
}

export async function saveCohort(
  name: string, description: string, filters: FilterState, sampleCount: number,
): Promise<CohortFull> {
  const res = await fetchWithTimeout(`${BASE}/api/cohorts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description, filters, sampleCount }),
  });
  if (!res.ok) await extractError(res, "Failed to save cohort");
  return res.json();
}

export async function deleteCohort(name: string): Promise<void> {
  const res = await fetchWithTimeout(`${BASE}/api/cohorts/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
  if (!res.ok) await extractError(res, "Failed to delete cohort");
}

export async function cohortExists(name: string): Promise<boolean> {
  const res = await fetchWithTimeout(`${BASE}/api/cohorts/${encodeURIComponent(name)}/exists`);
  if (!res.ok) return false;
  const data = await res.json();
  return data.exists;
}

export interface Datasource {
  id: string;
  name: string;
  database: string | null;
  rw_endpoint: string | null;
  resource_type: string;
}

export interface S3Folder {
  id: string;
  name: string;
  resource_type: string;
}

export interface DatasourcesResponse {
  resources: Datasource[];
  s3_folders: S3Folder[];
  active: string | null;
  has_local: boolean;
}

export async function fetchDatasources(): Promise<DatasourcesResponse> {
  const res = await fetchWithTimeout(`${BASE}/api/datasources`);
  if (!res.ok) await extractError(res, "Failed to fetch datasources");
  return res.json();
}

export async function refreshDatasources(): Promise<DatasourcesResponse> {
  const res = await fetchWithTimeout(`${BASE}/api/datasources/refresh`, { method: "POST" });
  if (!res.ok) await extractError(res, "Failed to refresh datasources");
  return res.json();
}

export interface S3File {
  key: string;
  name: string;
  size: number;
  s3_path: string;
}

export async function listS3Files(folderId: string): Promise<S3File[]> {
  const res = await fetchWithTimeout(
    `${BASE}/api/s3/files?folder_id=${encodeURIComponent(folderId)}`,
    { timeoutMs: 120_000 },
  );
  if (!res.ok) await extractError(res, "Failed to list S3 files");
  return res.json();
}

export async function connectResource(
  resourceId: string, cohortFolder?: string, seedFrom?: string,
): Promise<{ connected: string; seeded?: number }> {
  const params = new URLSearchParams({ resource_id: resourceId });
  if (cohortFolder) params.set("cohort_folder", cohortFolder);
  if (seedFrom) params.set("seed_from", seedFrom);
  const res = await fetchWithTimeout(
    `${BASE}/api/connect?${params}`,
    { method: "POST", timeoutMs: 15_000 },
  );
  if (!res.ok) await extractError(res, "Failed to connect");
  return res.json();
}

export interface SalmonPrepareResponse {
  sample_count: number;
  samples_with_fastq: number;
  samples_without_fastq: number;
  preview: { sample_name: string; input_files: string }[];
}

export interface SalmonSubmitResponse {
  job_id: string;
  samples_submitted: number;
  status: string;
}

export interface SalmonStatusResponse {
  job_id: string;
  status: string;
  output?: string;
  error?: string;
}

export async function prepareSalmon(filters: FilterState): Promise<SalmonPrepareResponse> {
  const res = await fetchWithTimeout(`${BASE}/api/salmon/prepare?${buildParams(filters)}`, { method: "POST" });
  if (!res.ok) await extractError(res, "Failed to prepare Salmon job");
  return res.json();
}

export async function submitSalmon(filters: FilterState): Promise<SalmonSubmitResponse> {
  const res = await fetchWithTimeout(`${BASE}/api/salmon/submit?${buildParams(filters)}`, { method: "POST" });
  if (!res.ok) await extractError(res, "Failed to submit Salmon job");
  return res.json();
}

export async function checkSalmonStatus(jobId: string): Promise<SalmonStatusResponse> {
  const res = await fetchWithTimeout(`${BASE}/api/salmon/status/${encodeURIComponent(jobId)}`);
  if (!res.ok) await extractError(res, "Failed to check Salmon status");
  return res.json();
}
