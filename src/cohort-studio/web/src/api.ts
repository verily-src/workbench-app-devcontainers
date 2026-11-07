import type { ExtractInfo, JoinOutput, Parameter,
  ChartSpec, ChatMsg, Cohort, ColumnProfile, Dataset, Filter, JoinPreview,
  ColumnSetting, JoinFilter, JoinStats, JoinStep, JoinSuggestion, JoinRecommendation, JoinValidation, QueryResult, Source,
  SourceRef, GrainDefinition, GrainInfo, GrainCheck, PerformanceSummary,
  TableInfo, OmopSpec, OmopCount, SqlPreview,
  SavedViewJob, SavedViewList, SourceInfo, SqlCompletions, ViewRevision,
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

/** Freshness of the workspace resource list behind /api/datasources. */
export interface DiscoveryStatus {
  status: "fresh" | "refreshing" | "stale" | "failed" | "unavailable";
  updated_at: string | null;
  from_cache: boolean;
  error?: string;
  error_code?: string;
  failed_kinds?: string[];
  retry_at?: string;
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

import { notifyDataReady } from "./notifications";

/** Serializable recipe for each open tab (saved views and session restore). */
export function viewSpecs(datasets: Dataset[]) {
  return datasets.map((d) => ({
    source: d.sourceRef,
    title: d.title,
    filters: d.filters,
    charts: d.charts,
    cohorts: d.cohorts ?? [],
    entity_column: d.entityColumn ?? null,
    filter_ask_history: d.filterAskHistory ?? [],
    group_summary: d.groupSummary ?? null,
    sort: d.sort ?? null,
    parameters: d.parameters ?? [],
    chart_columns: d.chartColumns ?? 0,
  }));
}

/** A saved view's stored tab set (draft or published revision). */
export interface SavedViewState {
  version?: number; active?: number;
  datasets: Array<{
    source: SourceRef;
    title?: string; filters: Filter[]; charts: ChartSpec[];
    cohorts?: Cohort[];
    entity_column?: string | null;
    filter_ask_history?: Dataset["filterAskHistory"];
    group_summary?: Dataset["groupSummary"] | null;
    sort?: Dataset["sort"] | null;
    parameters?: Parameter[];
    chart_columns?: 0 | 1 | 2 | 3 | 4;
  }>;
}

export interface DataJob {
  job_id: string; kind: string; status: string; result?: OpenResult;
  error?: string | { code?: string; message?: string }; status_code?: number;
  /** What is being loaded or joined, e.g. "cdm.person from omop". */
  label?: string;
  /** Current step reported by the server, e.g. "Reading cdm.person from omop". */
  phase?: string;
  detail?: { rows?: number; columns?: number; cap?: number; engine?: string;
    resource?: string; table?: string; sources?: number };
  started?: number;
  /** Seconds since the job was queued (frozen once it finishes). */
  elapsed?: number;
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

async function dataJob<T>(kind: string, body: unknown, signal?: AbortSignal,
                          onProgress?: (job: DataJob) => void): Promise<T> {
  const started = dataSubmissions.then(() => request<DataJob>(`/api/data-jobs/${kind}`, post(body)));
  dataSubmissions = started.catch(() => undefined);
  let job = await started;
  const cancel = () => { void request(`/api/data-jobs/${job.job_id}/cancel`, post({})).catch(() => {}); };
  if (signal?.aborted) cancel(); else signal?.addEventListener("abort", cancel, { once: true });
  if (kind !== "join_preview") { try { sessionStorage.setItem("studio-data-jobs", JSON.stringify([...pendingDataJobs(), job.job_id])); } catch { } }
  const notify = (value: DataJob | null) => { if (kind !== "join_preview") window.dispatchEvent(
    new CustomEvent("studio-data-job", { detail: { id: job.job_id, job: value } })); };
  try {
    while (["queued", "running", "cancelling"].includes(job.status)) {
      notify(job);
      onProgress?.(job);
      await new Promise(resolve => setTimeout(resolve, 750));
      job = await request<DataJob>(`/api/data-jobs/${job.job_id}`);
    }
    forgetDataJob(job.job_id);
    notify(job);
    onProgress?.(job);
    if (job.status === "complete") { if (kind !== "join_preview") notifyDataReady(job.kind, job.job_id); return job.result as T; }
    if (job.status === "cancelled") throw new Error("Operation cancelled.");
    if (job.status === "interrupted") throw new Error("The app restarted. Retry the operation.");
    const detail = job.error;
    throw new ApiError(job.status_code ?? 500,
      typeof detail === "object" ? detail.code : undefined,
      typeof detail === "object" ? detail.message ?? "Data operation failed." : detail ?? "Data operation failed.");
  } finally { signal?.removeEventListener("abort", cancel); notify(null); }
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
  /** App brand theme: "verily" or co-branded "partner". */
  brand?: "verily" | "partner";
  /** Off hides Agent, chat, Ask AI and AI settings (STUDIO_AI_FEATURES). */
  features?: { ai?: boolean; lineage?: boolean; plink?: boolean };
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
      catalog: "AwsDataCatalog" }
  | { kind: "bq"; id: string; label: string; project: string; dataset: string;
      table: string; billing_project: string };

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
  monitor_base?: string | null;
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
  source_info?: SourceInfo | null;
  query_scope?: "database" | "loaded";
  /** Present on the results of extract and refresh_extract jobs. */
  extract?: ExtractInfo;
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

/** Join request body; filters are sent only when set, so older servers and
 * recorded requests see the same shape as before. */
const hasOutput = (o?: JoinOutput) => Boolean(o && (o.exclude?.length || Object.keys(o.rename ?? {}).length));

function joinBody(baseId: string, steps: JoinStep[], allowLoaded: boolean,
                  baseFilters?: JoinFilter[], output?: JoinOutput) {
  return {
    ...(hasOutput(output) ? { output } : {}),
    base_id: baseId,
    steps: steps.map(({ filters, ...step }) => filters?.length ? { ...step, filters } : step),
    allow_loaded: allowLoaded,
    ...(baseFilters?.length ? { base_filters: baseFilters } : {}),
  };
}

export const api = {
  groupSummary: (datasetId: string, body: { group_by: string[]; measure: string | null; filters: Filter[]; page: number; page_size: number }) =>
    request<{ columns: string[]; rows: unknown[][]; total_groups: number; input_rows: number; page: number; page_size: number; scope: "database" | "loaded"; sampled: boolean }>(`/api/datasets/${encodeURIComponent(datasetId)}/summary`, post(body)),
  /** Every group of a summary (after filters) opened as a new dataset tab. */
  openGroupSummary: (datasetId: string, body: { group_by: string[]; measure: string | null; filters: Filter[] }) =>
    request<OpenResult & { summary: { total_groups: number; input_rows: number; scope: "database" | "loaded"; sampled: boolean; staged: boolean } }>(
      `/api/datasets/${encodeURIComponent(datasetId)}/summary/materialize`, post(body)),

  grain: (id: string) => request<GrainInfo>(`/api/datasets/${id}/grain`),
  saveGrain: (id: string, definition: GrainDefinition) => request<GrainInfo>(`/api/datasets/${id}/grain`, {...post(definition), method: "PUT"}),
  checkGrain: (id: string) => request<GrainCheck>(`/api/datasets/${id}/grain/check`, post({})),
  performance: () => request<PerformanceSummary>("/api/performance"),
  lintSql: (sql: string) => request<{ ok: boolean; message: string; line?: number; col?: number;
    detail?: string; formatted?: string | null }>("/api/sql/lint", post({ sql })),
  sqlCompletions: (resourceId: string) => request<SqlCompletions>(
    `/api/sql/completions?resource_id=${encodeURIComponent(resourceId)}`),

  agentStoreStatus: () => request<{ resource_id: string | null; from_environment: boolean;
    ready: boolean; aurora: string[] }>("/api/admin/agent-store"),
  setupAgentStore: (resourceId: string) => request<{ resource_id: string; ready: boolean; mode: string }>(
    "/api/admin/agent-store", post({ resource_id: resourceId, managed_access: true })),

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
  datasources: () =>
    request<{ ready: boolean; sources: Source[];
              catalogs_pending?: boolean; discovery?: DiscoveryStatus }>("/api/datasources"),
  refreshDatasources: () =>
    request<{ started: boolean; discovery: DiscoveryStatus }>(
      "/api/datasources/refresh", { method: "POST" }),

  publishCatalog: (resourceId: string, name: string) =>
    request<{ catalog_id: string; uri: string; views: string[];
              skipped: { name: string; error: string }[]; bytes: number }>(
      "/api/catalogs/build", post({ resource_id: resourceId, name })),

  tables: (kind: string, resourceId: string, refresh = false) =>
    request<TableInfo[]>(
      `/api/tables?kind=${kind}&resource_id=${encodeURIComponent(resourceId)}`
      + (refresh ? "&refresh=true" : "")),

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

  query: async (datasetId: string, filters: Filter[], charts: ChartSpec[],
          page: number, entityColumn?: string, refresh = false, sort?: Dataset["sort"],
          signal?: AbortSignal) => {
    const init = {
      ...post({ filters, charts: charts.map(({ kind, x, y }) => ({ kind, x, y })),
               page, page_size: 50, entity_column: entityColumn ?? null,
               refresh, sort: sort ?? null }),
      signal,
    };
    try {
      return await request<QueryResult>(`/api/datasets/${datasetId}/query`, init);
    } catch (e) {
      // Dashboard queries are admission-limited; one short retry absorbs a
      // burst instead of surfacing "429" to the user.
      if (!(e instanceof ApiError) || e.status !== 429 || signal?.aborted) throw e;
      await new Promise((resolve) => setTimeout(resolve, 600));
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      return request<QueryResult>(`/api/datasets/${datasetId}/query`, init);
    }
  },

  updateColumns: (datasetId: string, columns: ColumnSetting[]) =>
    request<OpenResult>(`/api/datasets/${datasetId}/columns`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ columns }),
    }),

  join: (baseId: string, steps: JoinStep[], allowLoaded = false, baseFilters?: JoinFilter[],
         output?: JoinOutput) =>
    dataJob<OpenResult & { join: JoinStats }>("join",
      joinBody(baseId, steps, allowLoaded, baseFilters, output)),

  previewJoin: (baseId: string, steps: JoinStep[], allowLoaded = false, signal?: AbortSignal,
                onProgress?: (job: DataJob) => void, baseFilters?: JoinFilter[], output?: JoinOutput) =>
    dataJob<JoinPreview>("join_preview", joinBody(baseId, steps, allowLoaded, baseFilters, output),
      signal, onProgress),

  validateJoin: (baseId: string, steps: JoinStep[], signal?: AbortSignal,
                 allowLoaded = false, baseFilters?: JoinFilter[]) =>
    request<JoinValidation>("/api/datasets/join/validate",
      { ...post(joinBody(baseId, steps, allowLoaded, baseFilters)), signal }),

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

  version: () => request<{ sha: string }>("/api/version"),

  config: () => request<AppConfig>("/api/config"),

  updateConfig: (body: {
    provider?: Provider; model?: string; api_key?: string;
    jev_api_key?: string; jev_model?: string;
    ncbi_api_key?: string;
    mcp_connections?: Omit<MCPConnection, "token_set">[]; chart_palette?: string;
    brand?: "verily" | "partner";
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

  /** Save every row of a tab as a database table (no row cap), recording its
   *  recipe so it can be refreshed; resolves with the extract table opened. */
  extract: (datasetId: string, kind: string, resourceId: string, table: string, title: string,
            onProgress?: (job: DataJob) => void) =>
    dataJob<OpenResult>("extract", { dataset_id: datasetId, kind, resource_id: resourceId, table, title },
      undefined, onProgress),

  /** Rerun an extract's recipe, replace its rows, and reopen it. */
  refreshExtract: (kind: string, resourceId: string, table: string,
                   onProgress?: (job: DataJob) => void) =>
    dataJob<OpenResult>("refresh_extract", { kind, resource_id: resourceId, table },
      undefined, onProgress),

  extractInfo: (resourceId: string, table: string) =>
    request<{ extract: ExtractInfo | null }>(
      `/api/extracts/info?${new URLSearchParams({ resource_id: resourceId, table })}`),

  ask: (datasetId: string, question: string, filters: Filter[]) =>
    request<{ filters: Filter[]; explanation: string }>(
      `/api/datasets/${datasetId}/ask`, post({ question, filters })),

  adminUpdate: () =>
    request<{ started: boolean }>("/api/admin/update", { method: "POST" }),

  listAllViews: () => request<SavedViewList>("/api/views/all"),

  savedViewJob: (jobId: string) =>
    request<SavedViewJob>(`/api/views/jobs/${encodeURIComponent(jobId)}`),

  refreshView: (kind: string, resourceId: string, name: string) =>
    request<SavedViewJob>("/api/views/refresh", post({
      kind, resource_id: resourceId, name,
    })),

  getView: (kind: string, resourceId: string, name: string) =>
    request<SavedViewState>(`/api/views/one?kind=${kind}&resource_id=${encodeURIComponent(resourceId)}`
       + `&name=${encodeURIComponent(name)}`),

  saveView: (kind: string, resourceId: string, name: string,
             datasets: Dataset[], active: number) =>
    request<{ name: string; job_id?: string; status?: SavedViewJob["status"]; completed_sources?: number; total_sources?: number; error?: string | null }>("/api/views", post({
      kind, resource_id: resourceId, name, active,
      datasets: viewSpecs(datasets),
    })),

  publishView: (kind: string, resourceId: string, name: string, note: string) =>
    request<ViewRevision>("/api/views/publish", post({
      kind, resource_id: resourceId, name, note: note.trim() || null,
    })),

  listViewRevisions: (kind: string, resourceId: string, name: string) =>
    request<{ revisions: ViewRevision[] }>(`/api/views/revisions?${new URLSearchParams({
      kind, resource_id: resourceId, name })}`),

  /** A published revision; without `revision`, the latest one. */
  getViewRevision: (kind: string, resourceId: string, name: string, revision?: number) =>
    request<SavedViewState & { published: ViewRevision }>(
      `/api/views/revision?${new URLSearchParams({ kind, resource_id: resourceId, name,
        ...(revision ? { revision: String(revision) } : {}) })}`),

  rollbackView: (kind: string, resourceId: string, name: string, revision: number) =>
    request<{ name: string; revision: number }>("/api/views/rollback", post({
      kind, resource_id: resourceId, name, revision,
    })),

  deleteView: (kind: string, resourceId: string, name: string) =>
    request<{ ok: boolean }>(
      `/api/views?kind=${kind}&resource_id=${encodeURIComponent(resourceId)}`
      + `&name=${encodeURIComponent(name)}`, { method: "DELETE" }),

  lineage: () =>
    request<{ columns: string[]; data: unknown[][] }>("/api/lineage"),

  export: async (datasetId: string, filters: Filter[], format: "tsv" | "tsv.gz" | "parquet" | "json" | "duckdb" = "tsv") => {
    const resp = await fetch(`/api/datasets/${datasetId}/export`,
      post({ filters, format }));
    if (!resp.ok) {
      const payload = await resp.json().catch(() => null);
      throw new Error(typeof payload?.detail === "string" ? payload.detail : `Export failed (${resp.status})`);
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cohort.${format}`;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 60000);
  },
  createExport: (datasetId: string, filters: Filter[], format: "tsv" | "tsv.gz" | "json" | "parquet" = "tsv") =>
    request<ExportJob>(`/api/datasets/${encodeURIComponent(datasetId)}/exports`,
      post({ filters, format })),
  exportStatus: (jobId: string) =>
    request<ExportJob>(`/api/exports/${encodeURIComponent(jobId)}`),
  cancelExport: (jobId: string) =>
    request<{ ok?: boolean }>(`/api/exports/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
    }),
  exportDownloadUrl: (jobId: string) =>
    `/api/exports/${encodeURIComponent(jobId)}/download`,
};
