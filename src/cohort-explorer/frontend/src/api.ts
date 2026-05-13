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
  if (!res.ok) throw new Error(`Failed to seed: ${res.status}`);
  return res.json();
}

export function exportUrl(filters: FilterState): string {
  return `/api/export?${buildParams(filters)}`;
}
