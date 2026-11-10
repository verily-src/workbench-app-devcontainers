import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, describeError } from "./client";

const respond = (init: { ok: boolean; status?: number; statusText?: string; body?: string | null; json?: unknown }) =>
  ({
    ok: init.ok,
    status: init.status ?? (init.ok ? 200 : 500),
    statusText: init.statusText ?? "",
    json: () => Promise.resolve(init.json),
    text: () => Promise.resolve(init.body ?? ""),
  }) as unknown as Response;

describe("apiFetch", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("prefixes the API root, forwards the request options and returns the JSON body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond({ ok: true, json: { userEmail: "a@b.org" } }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    const result = await apiFetch<{ userEmail: string }>("/profile", { signal: controller.signal });

    expect(result).toEqual({ userEmail: "a@b.org" });
    expect(fetchMock).toHaveBeenCalledWith("/api/profile", { signal: controller.signal });
  });

  it("throws an ApiError carrying the status and the parsed body for an error response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        respond({ ok: false, status: 503, statusText: "Service Unavailable", body: '{"error":"Service Unavailable","path":"/api/search"}' }),
      ),
    );

    const error = await apiFetch("/search").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(503);
    expect(apiError.statusText).toBe("Service Unavailable");
    expect(apiError.body).toEqual({ error: "Service Unavailable", path: "/api/search" });
    // The message callers and older tests display is unchanged.
    expect(apiError.message).toBe("Request failed with status 503");
  });

  it("copes with an error response that has no body, or a body that isn't JSON", async () => {
    // A bare stub, as tests use: no text() at all.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    const bare = (await apiFetch("/status").catch((e: unknown) => e)) as ApiError;
    expect(bare.status).toBe(500);
    expect(bare.body).toBeNull();

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond({ ok: false, status: 502, body: "Bad Gateway" })));
    const text = (await apiFetch("/status").catch((e: unknown) => e)) as ApiError;
    expect(text.body).toBe("Bad Gateway");
  });

  it("lets a network failure through as the browser's own error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(apiFetch("/profile")).rejects.toThrow(TypeError);
  });
});

describe("describeError", () => {
  it("names the status for an API error and passes other errors' messages through", () => {
    expect(describeError(new ApiError(500, "Internal Server Error", null))).toBe(
      "Request failed with status 500 (Internal Server Error)",
    );
    expect(describeError(new ApiError(404, "", null))).toBe("Request failed with status 404");
    expect(describeError(new TypeError("Failed to fetch"))).toBe("Failed to fetch");
    expect(describeError("odd")).toBe("odd");
  });
});
