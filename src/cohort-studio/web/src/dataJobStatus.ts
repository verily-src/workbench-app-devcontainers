/** Server states of a browser data job (`/api/data-jobs/{id}`). */
export type DataJobStatus =
  | "queued" | "running" | "cancelling"
  | "complete" | "failed" | "cancelled" | "interrupted";

export const ACTIVE_DATA_JOB_STATUSES: ReadonlySet<string> =
  new Set<DataJobStatus>(["queued", "running", "cancelling"]);

export const TERMINAL_DATA_JOB_STATUSES: ReadonlySet<string> =
  new Set<DataJobStatus>(["complete", "failed", "cancelled", "interrupted"]);

export function isActiveDataJob(status: string): boolean {
  return ACTIVE_DATA_JOB_STATUSES.has(status);
}

export function isTerminalDataJob(status: string): boolean {
  return TERMINAL_DATA_JOB_STATUSES.has(status);
}

const TRANSIENT_HTTP = new Set([502, 503, 504]);

/** Network failures and gateway errors are worth retrying; other errors are not. */
export function isTransientPollError(error: unknown): boolean {
  if (error instanceof TypeError) return true;
  const status = (error as { status?: unknown } | null)?.status;
  return typeof status === "number" && TRANSIENT_HTTP.has(status);
}

export const POLL_RETRY_BUDGET_MS = 60_000;
export const POLL_RETRY_MAX_DELAY_MS = 10_000;
