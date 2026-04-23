// Schema types matching docs/schema.json structure

export interface Column {
  name: string;
  type: string;
  nullable: boolean;
  ordinal_position: number;
  clinical_label: string;
  clinical_domain: string;
  description: string;
  is_candidate_endpoint: boolean;
  is_candidate_exposure: boolean;
  is_candidate_confounder: boolean;
}

export interface Table {
  name: string;
  dataset: string;
  domain: string;
  row_count: number;
  size_mb: number;
  last_modified: string;
  description: string;
  partition_column: string | null;
  columns: Column[];
}

export interface Dataset {
  name: string;
  tables: Table[];
}

export interface Schema {
  data_project: string;
  app_project: string;
  extracted_at: string;
  datasets: Dataset[];
}

let cachedSchema: Schema | null = null;

export async function loadSchema(): Promise<Schema> {
  if (cachedSchema) {
    return cachedSchema;
  }

  try {
    const response = await fetch('/docs/schema.json');
    if (!response.ok) {
      throw new Error(`Failed to load schema: ${response.statusText}`);
    }
    const schema: Schema = await response.json();
    cachedSchema = schema;
    return schema;
  } catch (error) {
    console.error('Error loading schema:', error);
    throw error;
  }
}

// Utility functions for schema queries

export function getAllTables(schema: Schema): Table[] {
  return schema.datasets.flatMap(ds => ds.tables);
}

export function getAllColumns(schema: Schema): Column[] {
  return getAllTables(schema).flatMap(table => table.columns);
}

export function getColumnsByDomain(schema: Schema, domain: string): Column[] {
  return getAllColumns(schema).filter(col => col.clinical_domain === domain);
}

export function getCandidateEndpoints(schema: Schema): Column[] {
  return getAllColumns(schema).filter(col => col.is_candidate_endpoint);
}

export function getCandidateExposures(schema: Schema): Column[] {
  return getAllColumns(schema).filter(col => col.is_candidate_exposure);
}

export function getCandidateConfounders(schema: Schema): Column[] {
  return getAllColumns(schema).filter(col => col.is_candidate_confounder);
}

export function getTotalRowCount(schema: Schema): number {
  return getAllTables(schema).reduce((sum, table) => sum + table.row_count, 0);
}

export function getDatasetByName(schema: Schema, name: string): Dataset | undefined {
  return schema.datasets.find(ds => ds.name === name);
}

export function getTableByName(schema: Schema, datasetName: string, tableName: string): Table | undefined {
  const dataset = getDatasetByName(schema, datasetName);
  return dataset?.tables.find(table => table.name === tableName);
}
