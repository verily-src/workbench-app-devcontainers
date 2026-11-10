// The one place the UI talks to the backend. Every module in api/ builds its request with
// apiFetch, so URL assembly, the ok-check and the shape of a failure are decided once.
// Nothing else here: no retries, no interceptors. If a request needs more, it composes this.

/**
 * A response the backend answered with an error status. Carries what the response said, so an
 * error page can show the status (and the body, when the backend sends one) instead of parsing a
 * message. The message stays "Request failed with status N", which is what callers display and
 * tests look for.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly statusText: string,
    /** The response body, parsed as JSON when it was JSON, otherwise as text; null when empty. */
    readonly body: unknown,
  ) {
    super(`Request failed with status ${status}`);
    this.name = "ApiError";
  }
}

/**
 * Fetches `/api{path}` and returns its JSON body. Throws ApiError for an error status; a network
 * failure (or an aborted request) rejects with the browser's own error, untouched, since it isn't
 * a response.
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  // Called exactly as the modules used to call it, so a test that asserts the fetch arguments
  // sees the same call with or without options.
  const response = init === undefined ? await fetch(`/api${path}`) : await fetch(`/api${path}`, init);
  if (!response.ok) {
    throw new ApiError(response.status, response.statusText ?? "", await bodyOf(response));
  }
  return response.json() as Promise<T>;
}

/** The body of an error response, without letting a malformed or missing one mask the status. */
async function bodyOf(response: Response): Promise<unknown> {
  try {
    const text = await response.text?.();
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  } catch {
    return null;
  }
}

/**
 * One sentence for a failed request, for the places that show it: the status for an ApiError,
 * otherwise whatever the browser said (typically a network failure).
 */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.statusText ? `${error.message} (${error.statusText})` : error.message;
  }
  return error instanceof Error ? error.message : String(error);
}
