export interface SampleRow {
  id: number;
  subject_id: string;
  gtex_sample_id: string;
  specimen_id: string | null;
  tissue_type: string;
  tissue_type_detail: string;
  autolysis_score: string | null;
  current_material_type: string | null;
  sample_collection_kit: string | null;
  rin_number: number | null;
  total_ischemic_time: number | null;
  paxgene_time: number | null;
  tissue_location: string | null;
  bss_collection_site: string | null;
  original_material_type: string | null;
  srr_id: string | null;
  fastq1_path: string | null;
  fastq2_path: string | null;
}

export interface FilterOption {
  value: string;
  label: string;
  count: number;
}

export interface RangeFilter {
  min: number | null;
  max: number | null;
}

export interface FiltersResponse {
  tissue_type: FilterOption[];
  tissue_type_detail: FilterOption[];
  autolysis_score: FilterOption[];
  current_material_type: FilterOption[];
  sample_collection_kit: FilterOption[];
  rin_number: RangeFilter;
  total_ischemic_time: RangeFilter;
  paxgene_time: RangeFilter;
}

export interface Counts {
  samples: number;
  subjects: number;
  fastq_pairs: number;
}

export interface FilterState {
  tissue_type: string[];
  tissue_type_detail: string[];
  autolysis_score: string[];
  current_material_type: string[];
  sample_collection_kit: string[];
  rin_number_min: number | null;
  rin_number_max: number | null;
  total_ischemic_time_min: number | null;
  total_ischemic_time_max: number | null;
  paxgene_time_min: number | null;
  paxgene_time_max: number | null;
}

export const EMPTY_FILTERS: FilterState = {
  tissue_type: [],
  tissue_type_detail: [],
  autolysis_score: [],
  current_material_type: [],
  sample_collection_kit: [],
  rin_number_min: null,
  rin_number_max: null,
  total_ischemic_time_min: null,
  total_ischemic_time_max: null,
  paxgene_time_min: null,
  paxgene_time_max: null,
};
