import type { Counts, FilterState, FiltersResponse, SampleRow } from "./types";

function buildParams(filters: FilterState): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of [
    "tissue_type",
    "tissue_type_detail",
    "autolysis_score",
    "current_material_type",
    "sample_collection_kit",
  ] as const) {
    for (const v of filters[key]) {
      params.append(key, v);
    }
  }
  for (const key of [
    "rin_number_min",
    "rin_number_max",
    "total_ischemic_time_min",
    "total_ischemic_time_max",
    "paxgene_time_min",
    "paxgene_time_max",
  ] as const) {
    const val = filters[key];
    if (val !== null) params.append(key, String(val));
  }
  return params;
}

export async function fetchSamples(filters: FilterState): Promise<SampleRow[]> {
  const res = await fetch(`/api/samples?${buildParams(filters)}`);
  if (!res.ok) throw new Error(`Failed to fetch samples: ${res.status}`);
  return res.json();
}

export async function fetchFilters(
  filters: FilterState,
): Promise<FiltersResponse> {
  const res = await fetch(`/api/filters?${buildParams(filters)}`);
  if (!res.ok) throw new Error(`Failed to fetch filters: ${res.status}`);
  return res.json();
}

export async function fetchCounts(filters: FilterState): Promise<Counts> {
  const res = await fetch(`/api/counts?${buildParams(filters)}`);
  if (!res.ok) throw new Error(`Failed to fetch counts: ${res.status}`);
  return res.json();
}

export async function seedData(): Promise<{ seeded: number }> {
  const res = await fetch("/api/seed", { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Failed to seed: ${res.status}`);
  }
  return res.json();
}

export function exportUrl(filters: FilterState): string {
  return `/api/export?${buildParams(filters)}`;
}

export interface Datasource {
  id: string;
  name: string;
  database: string | null;
  rw_endpoint: string | null;
  resource_type: string;
}

export interface DatasourcesResponse {
  resources: Datasource[];
  active: string | null;
  has_local: boolean;
}

export async function fetchDatasources(): Promise<DatasourcesResponse> {
  const res = await fetch("/api/datasources");
  if (!res.ok) throw new Error(`Failed to fetch datasources: ${res.status}`);
  return res.json();
}

export async function connectResource(resourceId: string): Promise<{ connected: string }> {
  const res = await fetch(`/api/connect?resource_id=${encodeURIComponent(resourceId)}`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Failed to connect: ${res.status}`);
  }
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
  output: string;
}

export async function prepareSalmon(filters: FilterState): Promise<SalmonPrepareResponse> {
  const res = await fetch(`/api/salmon/prepare?${buildParams(filters)}`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Failed to prepare: ${res.status}`);
  }
  return res.json();
}

export async function submitSalmon(filters: FilterState): Promise<SalmonSubmitResponse> {
  const res = await fetch(`/api/salmon/submit?${buildParams(filters)}`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Failed to submit: ${res.status}`);
  }
  return res.json();
}
