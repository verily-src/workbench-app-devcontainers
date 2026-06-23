import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { FilterState } from "./types";

// Mock import.meta.env.BASE_URL before importing api module
vi.stubEnv("BASE_URL", "/proxy/8080/");

// Dynamic import so the env stub is in place
const api = await import("./api");

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

function mockFetch(response: Partial<Response>) {
  const fn = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => Promise.resolve({}),
    ...response,
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("fetchWithTimeout behavior", () => {
  it("rejects with timeout message when fetch hangs", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        (_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => {
              reject(new DOMException("The operation was aborted.", "AbortError"));
            });
          }),
      ),
    );

    // connectResource has 15s timeout — we fake timers to trigger it instantly
    vi.useFakeTimers();
    const promise = api.connectResource("test-resource");
    vi.advanceTimersByTime(15_000);
    await expect(promise).rejects.toThrow("Request timed out after 15 seconds");
    vi.useRealTimers();
  });

  it("passes AbortSignal to fetch", async () => {
    const fetchSpy = mockFetch({ json: () => Promise.resolve({ connected: "ok" }) });
    await api.connectResource("test-id");

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const init = fetchSpy.mock.calls[0][1];
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });
});

describe("error message extraction", () => {
  it("extracts detail field from error response body", async () => {
    mockFetch({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ detail: "Connection refused by database" }),
    });

    await expect(api.fetchSamples({} as FilterState)).rejects.toThrow(
      "Connection refused by database",
    );
  });

  it("falls back to HTTP status when body has no detail", async () => {
    mockFetch({
      ok: false,
      status: 502,
      json: () => Promise.resolve({}),
    });

    await expect(api.fetchFilters({} as FilterState)).rejects.toThrow(
      "Failed to fetch filters (HTTP 502)",
    );
  });

  it("falls back to HTTP status when body is not JSON", async () => {
    mockFetch({
      ok: false,
      status: 503,
      json: () => Promise.reject(new Error("not json")),
    });

    await expect(api.fetchCounts({} as FilterState)).rejects.toThrow(
      "Failed to fetch counts (HTTP 503)",
    );
  });
});

describe("query parameter serialization", () => {
  it("serializes categorical filters as repeated params", async () => {
    const fetchSpy = mockFetch({ json: () => Promise.resolve([]) });

    const filters: FilterState = {
      ...{} as FilterState,
      tissue_type: ["Brain", "Heart"],
      autolysis_score: ["Mild"],
    };

    await api.fetchSamples(filters);

    const url = fetchSpy.mock.calls[0][0] as string;
    expect(url).toContain("tissue_type=Brain");
    expect(url).toContain("tissue_type=Heart");
    expect(url).toContain("autolysis_score=Mild");
  });

  it("serializes range filters when non-null", async () => {
    const fetchSpy = mockFetch({ json: () => Promise.resolve([]) });

    const filters: FilterState = {
      ...{} as FilterState,
      rin_number_min: 5.0,
      rin_number_max: 9.5,
    };

    await api.fetchSamples(filters);

    const url = fetchSpy.mock.calls[0][0] as string;
    expect(url).toContain("rin_number_min=5");
    expect(url).toContain("rin_number_max=9.5");
  });

  it("omits null range filters", async () => {
    const fetchSpy = mockFetch({ json: () => Promise.resolve([]) });

    await api.fetchSamples({} as FilterState);

    const url = fetchSpy.mock.calls[0][0] as string;
    expect(url).not.toContain("rin_number_min");
    expect(url).not.toContain("rin_number_max");
  });
});

describe("exportUrl", () => {
  it("returns a URL string with the base path", () => {
    const url = api.exportUrl({} as FilterState);
    expect(url).toMatch(/^\/proxy\/8080\/api\/export/);
  });
});
