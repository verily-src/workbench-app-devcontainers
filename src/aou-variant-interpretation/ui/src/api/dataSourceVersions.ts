import { apiFetch } from "./client";

export interface DataSourceVersion {
  name: string;
  version: string;
  /** What VIA takes from the source, as a sentence fragment. */
  description: string | null;
  url: string | null;
}

export const fetchDataSourceVersions = () => apiFetch<DataSourceVersion[]>("/sources");
