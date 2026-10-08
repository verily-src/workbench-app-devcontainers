import type {
  ChartSpec, ChatMsg, Cohort, ColumnProfile, Dataset, Filter, QueryResult,
  Source, TableInfo,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      const body = await resp.json();
      detail = body.detail ?? detail;
    } catch { /* non-JSON error body */ }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export interface MCPConnection {
  name: string;
  label: string;
  url: string;
  enabled: boolean;
  note: string;
  token_set: boolean;
  authorization_token?: string;
}

export interface ProviderConfig {
  model: string;
  api_key_set: boolean;
  api_key_hint: string | null;
  api_key_source: string | null;
}

export type Provider = "anthropic" | "openai" | "gemini";

export interface AppConfig {
  llm: {
    provider: Provider;
    providers: Record<Provider, ProviderConfig>;
    // Flattened active-provider fields for convenience.
    model: string;
    api_key_set: boolean;
    api_key_hint: string | null;
    api_key_source: string | null;
  };
  mcp: { available: boolean; path: string };
  mcp_connections: MCPConnection[];
  chart_palette: string;
}

export interface AgentTurn {
  ts: string;
  trace_id: string;
  provider: string;
  model: string;
  dataset: string;
  prompt: string;
  latency_ms: number;
  total_tokens: number;
  tool_calls: string;
  status: string;
}

export interface WorkflowJob {
  run_id: string;
  name: string;
  status: string;
  workflow_type: string | null;
  engine_type: string | null;
  created_by: string | null;
  created_date: string | null;
  end_time: string | null;
  output_bucket_uuid: string | null;
  output_bucket_path: string | null;
  output_bucket_name: string | null;
  output_bucket_resource: string | null;
  status_message: string | null;
}

export interface WorkflowList {
  available: boolean;
  jobs: WorkflowJob[];
  running_count: number;
}

export interface CompareGroupSummary {
  n: number;
  median?: number | null;
  mean?: number | null;
  top?: { value: string; pct: number }[];
}

export interface CompareRow {
  column: string;
  kind: "range" | "categorical";
  a: CompareGroupSummary;
  b: CompareGroupSummary;
  p: number | null;
  q: number | null;
  test?: string;
  note?: string | null;
}

export interface CompareResult {
  a_n: number;
  b_n: number;
  n_overlap: number;
  results: CompareRow[];
}

export interface OpenResult {
  dataset_id: string;
  source: string;
  rows: number;
  columns: ColumnProfile[];
}

export const api = {
  datasources: () =>
    request<{ ready: boolean; sources: Source[] }>("/api/datasources"),

  tables: (kind: string, resourceId: string) =>
    request<TableInfo[]>(
      `/api/tables?kind=${kind}&resource_id=${encodeURIComponent(resourceId)}`),

  openDataset: (kind: string, resourceId: string, table: string) =>
    request<OpenResult>("/api/datasets/open",
      post({ kind, resource_id: resourceId, table })),

  uploadDataset: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<OpenResult>("/api/datasets/upload",
      { method: "POST", body: form });
  },

  query: (datasetId: string, filters: Filter[], charts: ChartSpec[],
          page: number) =>
    request<QueryResult>(`/api/datasets/${datasetId}/query`,
      post({ filters, charts: charts.map(({ kind, x, y }) => ({ kind, x, y })),
             page, page_size: 50 })),

  join: (leftId: string, rightId: string, leftOn: string, rightOn: string,
         how: string) =>
    request<OpenResult>("/api/datasets/join", post({
      left_id: leftId, right_id: rightId, left_on: leftOn,
      right_on: rightOn, how })),

  compare: (datasetId: string, filtersA: Filter[], filtersB: Filter[],
            bIsRest: boolean) =>
    request<CompareResult>(`/api/datasets/${datasetId}/compare`, post({
      filters_a: filtersA, filters_b: filtersB, b_is_rest: bIsRest })),

  derive: (datasetId: string, spec: Record<string, unknown>) =>
    request<{ name: string; rows: number; columns: ColumnProfile[] }>(
      `/api/datasets/${datasetId}/derive`, post(spec)),

  closeDataset: (datasetId: string) =>
    request<{ ok: boolean }>(`/api/datasets/${datasetId}`,
      { method: "DELETE" }),

  seedGtex: (resourceId: string) =>
    request<{ rows: number }>(
      `/api/seed/gtex?resource_id=${encodeURIComponent(resourceId)}`,
      { method: "POST" }),

  version: () => request<{ sha: string }>("/api/version"),

  config: () => request<AppConfig>("/api/config"),

  updateConfig: (body: {
    provider?: Provider; model?: string; api_key?: string;
    mcp_connections?: MCPConnection[]; chart_palette?: string;
  }) => request<AppConfig>("/api/config",
    { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) }),

  testLlm: () =>
    request<{ ok: boolean; provider: string; model: string;
              display_name: string }>(
      "/api/config/llm/test", { method: "POST" }),

  agentTurns: () =>
    request<{ turns: AgentTurn[] }>("/api/agent/turns"),

  workflows: (refresh = false) =>
    request<WorkflowList>(`/api/workflows${refresh ? "?refresh=true" : ""}`),

  chat: (datasetId: string, message: string, history: ChatMsg[],
         filters: Filter[], charts: ChartSpec[]) =>
    request<{ reply: string; filters: Filter[]; charts: ChartSpec[];
              actions: string[] }>(
      `/api/datasets/${datasetId}/chat`,
      post({ message,
             history: history.map(({ role, content }) => ({ role, content })),
             filters,
             charts: charts.map(({ kind, x, y }) => ({ kind, x, y })) })),

  materialize: (datasetId: string, resourceId: string, table: string) =>
    request<{ table: string; resource_id: string; rows: number }>(
      `/api/datasets/${datasetId}/materialize`,
      post({ resource_id: resourceId, table })),

  ask: (datasetId: string, question: string, filters: Filter[]) =>
    request<{ filters: Filter[]; explanation: string }>(
      `/api/datasets/${datasetId}/ask`, post({ question, filters })),

  adminUpdate: () =>
    request<{ started: boolean }>("/api/admin/update", { method: "POST" }),

  listViews: (kind: string, resourceId: string) =>
    request<{ name: string }[]>(
      `/api/views?kind=${kind}&resource_id=${encodeURIComponent(resourceId)}`),

  getView: (kind: string, resourceId: string, name: string) =>
    request<{
      version?: number; active?: number;
      datasets: Array<{
        source: { kind: string; resource_id: string; table: string };
        title?: string; filters: Filter[]; charts: ChartSpec[];
        cohorts?: Cohort[];
      }>;
    }>(`/api/views/one?kind=${kind}&resource_id=${encodeURIComponent(resourceId)}`
       + `&name=${encodeURIComponent(name)}`),

  saveView: (kind: string, resourceId: string, name: string,
             datasets: Dataset[], active: number) =>
    request<{ name: string }>("/api/views", post({
      kind, resource_id: resourceId, name, active,
      datasets: datasets.map((d) => ({
        source: d.sourceRef,
        title: d.title,
        filters: d.filters,
        charts: d.charts.map((c: ChartSpec) => ({ kind: c.kind, x: c.x, y: c.y })),
        cohorts: d.cohorts ?? [],
      })),
    })),

  deleteView: (kind: string, resourceId: string, name: string) =>
    request<{ ok: boolean }>(
      `/api/views?kind=${kind}&resource_id=${encodeURIComponent(resourceId)}`
      + `&name=${encodeURIComponent(name)}`, { method: "DELETE" }),

  lineage: () =>
    request<{ columns: string[]; data: unknown[][] }>("/api/lineage"),

  export: async (datasetId: string, filters: Filter[]) => {
    const resp = await fetch(`/api/datasets/${datasetId}/export`,
      post({ filters }));
    if (!resp.ok) throw new Error(`${resp.status}`);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "cohort.tsv";
    a.click();
    URL.revokeObjectURL(url);
  },
};
