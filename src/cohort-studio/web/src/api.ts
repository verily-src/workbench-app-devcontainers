import type {
  ChartSpec, ChatMsg, Cohort, ColumnProfile, Dataset, Filter, JoinPreview,
  ColumnSetting, JoinStats, JoinStep, JoinSuggestion, JoinRecommendation, JoinValidation, QueryResult, Source,
  SourceRef, GrainDefinition, GrainInfo, GrainCheck, PerformanceSummary,
  TableInfo, OmopInfo, OmopConcept, OmopSpec, OmopCount, OmopSummary, SqlPreview,
  SavedViewJob, SavedViewList,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    let detail = `${resp.status}`;
    let code: string | undefined;
    try {
      const body = await resp.json();
      code = typeof body.code === "string" ? body.code : undefined;
      if (Array.isArray(body.detail)) {
        detail = body.detail.map((issue: { msg?: string }) =>
          issue.msg || "Invalid request").join("; ");
      } else if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (body.detail && typeof body.detail === "object") {
        code = typeof body.detail.code === "string" ? body.detail.code : code;
        detail = typeof body.detail.message === "string"
          ? body.detail.message : detail;
      }
    } catch {  }
    throw new ApiError(resp.status, code, detail);
  }
  return resp.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(readonly status: number, readonly code: string | undefined,
              message: string) {
    super(message);
    this.name = "ApiError";
  }
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

import { notifyDataReady } from "./notifications";

export interface DataJob {
  job_id: string; kind: string; status: string; result?: OpenResult;
  error?: string | { code?: string; message?: string }; status_code?: number;
}

export function pendingDataJobs(): string[] {
  try { return JSON.parse(sessionStorage.getItem("studio-data-jobs") || "[]") as string[]; }
  catch { return []; }
}

export function forgetDataJob(id: string) {
  try { sessionStorage.setItem("studio-data-jobs", JSON.stringify(pendingDataJobs().filter(value => value !== id))); }
  catch { /* Storage can be disabled by the browser. */ }
}

let dataSubmissions: Promise<unknown> = Promise.resolve();

async function dataJob<T>(kind: string, body: unknown): Promise<T> {
  const started = dataSubmissions.then(() => request<DataJob>(`/api/data-jobs/${kind}`, post(body)));
  dataSubmissions = started.catch(() => undefined);
  let job = await started;
  try { sessionStorage.setItem("studio-data-jobs", JSON.stringify([...pendingDataJobs(), job.job_id])); } catch { }
  const notify = (value: DataJob | null) => window.dispatchEvent(
    new CustomEvent("studio-data-job", { detail: { id: job.job_id, job: value } }));
  try {
    while (["queued", "running", "cancelling"].includes(job.status)) {
      notify(job);
      await new Promise(resolve => setTimeout(resolve, 750));
      job = await request<DataJob>(`/api/data-jobs/${job.job_id}`);
    }
    forgetDataJob(job.job_id);
    if (job.status === "complete") { notifyDataReady(job.kind, job.job_id); return job.result as T; }
    if (job.status === "cancelled") throw new Error("Operation cancelled.");
    if (job.status === "interrupted") throw new Error("The app restarted. Retry the operation.");
    const detail = job.error;
    throw new ApiError(job.status_code ?? 500,
      typeof detail === "object" ? detail.code : undefined,
      typeof detail === "object" ? detail.message ?? "Data operation failed." : detail ?? "Data operation failed.");
  } finally { notify(null); }
}

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
  api_key_source: string | null;
  auth_method: "api_key" | "iam" | "adc";
  region: string | null;
  project?: string | null;
  location?: string | null;
  configured?: boolean;
  endpoint_host?: string | null;
}

export type Provider = "anthropic" | "openai" | "gemini" | "openrouter" | "bedrock" | "vertexai" | "openweight";

export interface AppConfig {
  llm: {
    provider: Provider;
    providers: Record<Provider, ProviderConfig>;

    model: string;
    api_key_set: boolean;
    api_key_source: string | null;
  };
  mcp: { available: boolean; path: string };
  mcp_connections: MCPConnection[];
  chart_palette: string;
  jev: {
    model: string;
    api_key_set: boolean;
    api_key_source: string | null;
    secure_key_store_available?: boolean;
  };
  literature?: {
    ncbi_api_key_set: boolean;
    ncbi_api_key_source: string | null;
    secure_key_store_available?: boolean;
  };
}

export interface ChatHistory {
  session_id: string | null;
  messages: { role: "user" | "assistant"; content: string; message_id: number }[];
  has_more: boolean;
  next_before_message_id: number | null;
}

export interface AgentDashboardAction {
  dataset: OpenResult;
  title: string;
  charts: ChartSpec[];
  filters: Filter[];
}

export interface AgentWorkflowPlan {
  id: string;
  session_id?: string;
  workflow: string;
  dataset_id: string;
  rows: number;
  required_columns: string[];
  column_mapping?: Record<string, string>;
  input_resource_id: string;
  output_resource_id: string;
  output_path?: string;
  status: "ready" | "blocked" | "submitting" | "submission_unknown" | "submitted" | "running" | "completed" | "failed";
  errors: string[];
  run?: AgentWorkflowRun | null;
  results_location?: AgentWorkflowResultsLocation | null;
}

export interface AgentWorkflowRun {
  run_id?: string;
  status?: string;
  name?: string;
  [key: string]: unknown;
}

export interface AgentWorkflowResultsLocation {
  output_bucket_uuid?: string;
  output_bucket_resource?: string;
  output_bucket_path?: string;
}

export interface AgentWorkflowVerification {
  verified: true;
  run_id: string;
  rows?: number;
  integrity?: string;
  summary_sha256?: string;
  source_ref?: SourceRef;
  [key: string]: unknown;
}

export interface StudioAgentResponse {
  reply: string;
  session_id: string;
  trace_id: string;
  tool_calls: string[];
  tool_results?: { name: string; status: "completed" | "failed" }[];
  limit_reached?: boolean;
  actions: AgentDashboardAction[];
  workflow_plans: AgentWorkflowPlan[];
}

export interface AgentWorkflowApproval {
  status: string;
  run?: AgentWorkflowRun | null;
  results_location?: AgentWorkflowResultsLocation | null;
  error?: string | null;
}

export type AgentWorkflowStatus = AgentWorkflowPlan;

export type CreateSourceRequest =
  | { kind: "postgres"; id: string; label: string;
      secret_id: string; region: string }
  | { kind: "s3"; id: string; label: string; bucket: string;
      prefix: string; region: string }
  | { kind: "athena"; id: string; label: string; region: string;
      workgroup: string; output_location: string; databases: string[];
      catalog: "AwsDataCatalog" };

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
  source_ref?: SourceRef;
  query_scope?: "database" | "loaded";
}

export interface CohortAgentResult {
  session_id?: string;
  reply: string;
  concept_names?: Record<string, string>;
  spec: OmopSpec | null;
  count: OmopCount | null;
  reason: string | null;
  trace_id: string;
}

export interface ExportJob {
  id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | string;
  rows?: number;
  bytes?: number;
  error?: string | null;
}

let pendingWorkflows: Promise<WorkflowList> | undefined;
function workflows(refresh = false): Promise<WorkflowList> {
  if (!refresh && pendingWorkflows) return pendingWorkflows;
  const task = request<WorkflowList>(`/api/workflows${refresh ? "?refresh=true" : ""}`);
  if (!refresh) {
    pendingWorkflows = task;
    void task.then(() => { if (pendingWorkflows === task) pendingWorkflows = undefined; },
      () => { if (pendingWorkflows === task) pendingWorkflows = undefined; });
  }
  return task;
}

export const api = {
  groupSummary: (datasetId: string, body: { group_by: string[]; measure: string | null; filters: Filter[]; page: number; page_size: number }) =>
    request<{ columns: string[]; rows: unknown[][]; total_groups: number; input_rows: number; page: number; page_size: number; scope: "database" | "loaded"; sampled: boolean }>(`/api/datasets/${encodeURIComponent(datasetId)}/summary`, post(body)),

  grain: (id: string) => request<GrainInfo>(`/api/datasets/${id}/grain`),
  saveGrain: (id: string, definition: GrainDefinition) => request<GrainInfo>(`/api/datasets/${id}/grain`, {...post(definition), method: "PUT"}),
  checkGrain: (id: string) => request<GrainCheck>(`/api/datasets/${id}/grain/check`, post({})),
  performance: () => request<PerformanceSummary>("/api/performance"),
  createSource: (body: CreateSourceRequest) =>
    request<{ kind: string; id: string; label: string }>("/api/sources", post(body)),

  chatHistory: (kind: "dataset" | "omop", id: string, sessionId?: string, before?: number) => {
    const path = kind === "dataset" ? `/api/datasets/${encodeURIComponent(id)}/chat/history`
      : `/api/omop/${encodeURIComponent(id)}/cohort/agent/history`;
    const query = new URLSearchParams();
    if (sessionId) query.set("session_id", sessionId);
    if (before !== undefined) query.set("before", String(before));
    return request<ChatHistory>(`${path}?${query}`);
  },
  agentChatSessions: () => request<{ sessions: { session_id: string; title: string; updated_at: string }[] }>("/api/agent/chat/sessions"),
  agentChatHistory: (sessionId?: string, before?: number) => {
    const query = new URLSearchParams();
    if (sessionId) query.set("session_id", sessionId);
    if (before !== undefined) query.set("before", String(before));
    return request<ChatHistory>(`/api/agent/chat/history?${query}`);
  },
  agentChat: (message: string, sessionId?: string, newSession = false) =>
    request<StudioAgentResponse>("/api/agent/chat",
      post({ message, session_id: sessionId, new_session: newSession })),
  approveAgentWorkflow: (planId: string) =>
    request<AgentWorkflowPlan>(
      `/api/agent/workflows/${encodeURIComponent(planId)}/approve`, post({})),
  agentWorkflowStatus: (planId: string) =>
    request<AgentWorkflowPlan>(
      `/api/agent/workflows/${encodeURIComponent(planId)}/status`),
  agentWorkflowPlans: (sessionId?: string) =>
    request<{ plans: AgentWorkflowPlan[] }>(`/api/agent/workflows${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""}`),
  openAgentWorkflowResults: (planId: string) =>
    request<{ action: AgentDashboardAction; verification: AgentWorkflowVerification }>(
      `/api/agent/workflows/${encodeURIComponent(planId)}/results/open`, post({})),
  omopAgent: (id: string, message: string,
              _history: { role: string; content: string }[], spec: OmopSpec, sessionId?: string) =>
    request<CohortAgentResult>(`/api/omop/${encodeURIComponent(id)}/cohort/agent`,
      post({ message, spec, session_id: sessionId })),

  omopInfo: (id: string, refresh = false) => request<OmopInfo>(
    `/api/omop/${encodeURIComponent(id)}?refresh=${refresh}`),
  omopConcepts: (id: string, q: string, domain: string, standard: boolean) =>
    request<{ concepts: OmopConcept[] }>(`/api/omop/${encodeURIComponent(id)}/concepts?`
      + new URLSearchParams({ q, domain, standard_only: String(standard) })),
  omopCount: (id: string, spec: OmopSpec) => request<OmopCount>(
    `/api/omop/${encodeURIComponent(id)}/cohort/count`, post(spec)),
  omopSummary: (id: string, spec: OmopSpec, signal?: AbortSignal) =>
    request<OmopSummary>(`/api/omop/${encodeURIComponent(id)}/cohort/summary`,
      { ...post({ spec }), signal }),
  omopOpen: (id: string, spec: OmopSpec, name: string) => request<OpenResult>(
    `/api/omop/${encodeURIComponent(id)}/cohort/open`, post({ spec, name })),
  omopDomain: (id: string, table: string, spec: OmopSpec | null, names: boolean) =>
    request<OpenResult>(`/api/omop/${encodeURIComponent(id)}/domain/open`,
      post({ table, spec, concept_names: names })),

  datasources: () =>
    request<{ ready: boolean; sources: Source[];
              catalogs_pending?: boolean }>("/api/datasources"),

  publishCatalog: (resourceId: string, name: string) =>
    request<{ catalog_id: string; uri: string; views: string[];
              skipped: { name: string; error: string }[]; bytes: number }>(
      "/api/catalogs/build", post({ resource_id: resourceId, name })),

  tables: (kind: string, resourceId: string) =>
    request<TableInfo[]>(
      `/api/tables?kind=${kind}&resource_id=${encodeURIComponent(resourceId)}`),

  openDataset: (kind: string, resourceId: string, table: string) =>
    dataJob<OpenResult>("open", { kind, resource_id: resourceId, table }),

  openSourceRef: (source: SourceRef) =>
    dataJob<OpenResult>("open", { source_ref: source }),

  uploadDataset: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<OpenResult>("/api/datasets/upload",
      { method: "POST", body: form });
  },

  query: (datasetId: string, filters: Filter[], charts: ChartSpec[],
          page: number, entityColumn?: string, refresh = false) =>
    request<QueryResult>(`/api/datasets/${datasetId}/query`,
      post({ filters, charts: charts.map(({ kind, x, y }) => ({ kind, x, y })),
             page, page_size: 50, entity_column: entityColumn ?? null,
             refresh })),

  updateColumns: (datasetId: string, columns: ColumnSetting[]) =>
    request<OpenResult>(`/api/datasets/${datasetId}/columns`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ columns }),
    }),

  join: (baseId: string, steps: JoinStep[], allowLoaded = false) =>
    dataJob<OpenResult & { join: JoinStats }>("join",
      { base_id: baseId, steps, allow_loaded: allowLoaded }),

  previewJoin: (baseId: string, steps: JoinStep[], allowLoaded = false) =>
    request<JoinPreview>("/api/datasets/join/preview",
      post({ base_id: baseId, steps, allow_loaded: allowLoaded })),

  validateJoin: (baseId: string, steps: JoinStep[], signal?: AbortSignal,
                 allowLoaded = false) =>
    request<JoinValidation>("/api/datasets/join/validate",
      { ...post({ base_id: baseId, steps, allow_loaded: allowLoaded }), signal }),

  suggestJoin: (leftId: string, rightId: string) =>
    request<JoinSuggestion[]>(
      `/api/datasets/join/suggest?left_id=${encodeURIComponent(leftId)}`
      + `&right_id=${encodeURIComponent(rightId)}`),

  recommendJoin: (left: SourceRef, right: SourceRef) =>
    request<{ candidates: JoinRecommendation[]; warnings: string[] }>(
      "/api/joins/recommend", post({ left, right })),

  previewSql: (resourceId: string, sql: string) =>
    request<SqlPreview>("/api/sql/preview", post({ resource_id: resourceId, sql })),

  compare: (datasetId: string, filtersA: Filter[], filtersB: Filter[],
            bIsRest: boolean) =>
    request<CompareResult>(`/api/datasets/${datasetId}/compare`, post({
      filters_a: filtersA, filters_b: filtersB, b_is_rest: bIsRest })),

  derive: (datasetId: string, spec: Record<string, unknown>) =>
    request<{ name: string; rows: number; columns: ColumnProfile[];
              source_ref?: SourceRef | null;
              query_scope?: "database" | "loaded"; sampled?: boolean }>(
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
    jev_api_key?: string; jev_model?: string;
    ncbi_api_key?: string;
    mcp_connections?: Omit<MCPConnection, "token_set">[]; chart_palette?: string;
  }) => request<AppConfig>("/api/config",
    { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) }),

  testLlm: (timeoutMs = 30000) => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    return request<{ ok: boolean; provider: string; model: string;
                     display_name: string }>(
      "/api/config/llm/test", { method: "POST", signal: controller.signal })
      .finally(() => window.clearTimeout(timer));
  },

  agentTurns: () =>
    request<{ turns: AgentTurn[] }>("/api/agent/turns"),

  workflows,

  workflowRegistry: () =>
    request<{ available: boolean;
              workflows: { id: string; name: string; type: string | null;
                           description: string | null }[] }>(
      "/api/workflows/registry"),

  exportCohort: (datasetId: string, resourceId: string, path: string,
                 filters: Filter[], workflow?: string) =>
    request<{ s3_uri: string; resource_id: string; path: string;
              rows: number }>(
      `/api/datasets/${datasetId}/export-cohort`,
      post({ resource_id: resourceId, path, filters, workflow })),

  submitWorkflow: (spec: Record<string, unknown>) =>
    request<WorkflowJob>("/api/workflows/submit", post(spec)),

  chat: (datasetId: string, message: string, _history: ChatMsg[],
         filters: Filter[], charts: ChartSpec[], sessionId?: string) =>
    request<{ session_id?: string; reply: string; filters: Filter[]; charts: ChartSpec[];
              actions: string[] }>(
      `/api/datasets/${datasetId}/chat`,
      post({ message, session_id: sessionId,
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

  listAllViews: () => request<SavedViewList>("/api/views/all"),

  savedViewJob: (jobId: string) =>
    request<SavedViewJob>(`/api/views/jobs/${encodeURIComponent(jobId)}`),

  refreshView: (kind: string, resourceId: string, name: string) =>
    request<SavedViewJob>("/api/views/refresh", post({
      kind, resource_id: resourceId, name,
    })),

  getView: (kind: string, resourceId: string, name: string) =>
    request<{
      version?: number; active?: number;
      datasets: Array<{
        source: SourceRef;
        title?: string; filters: Filter[]; charts: ChartSpec[];
        cohorts?: Cohort[];
        entity_column?: string | null;
        filter_ask_history?: Dataset["filterAskHistory"];
      }>;
    }>(`/api/views/one?kind=${kind}&resource_id=${encodeURIComponent(resourceId)}`
       + `&name=${encodeURIComponent(name)}`),

  saveView: (kind: string, resourceId: string, name: string,
             datasets: Dataset[], active: number) =>
    request<{ name: string; job_id?: string; status?: SavedViewJob["status"]; completed_sources?: number; total_sources?: number; error?: string | null }>("/api/views", post({
      kind, resource_id: resourceId, name, active,
      datasets: datasets.map((d) => ({
        source: d.sourceRef,
        title: d.title,
        filters: d.filters,
        charts: d.charts,
        cohorts: d.cohorts ?? [],
        entity_column: d.entityColumn ?? null,
        filter_ask_history: d.filterAskHistory ?? [],
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
  createExport: (datasetId: string, filters: Filter[]) =>
    request<ExportJob>(`/api/datasets/${encodeURIComponent(datasetId)}/exports`,
      post({ filters })),
  exportStatus: (jobId: string) =>
    request<ExportJob>(`/api/exports/${encodeURIComponent(jobId)}`),
  cancelExport: (jobId: string) =>
    request<{ ok?: boolean }>(`/api/exports/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
    }),
  exportDownloadUrl: (jobId: string) =>
    `/api/exports/${encodeURIComponent(jobId)}/download`,
};
