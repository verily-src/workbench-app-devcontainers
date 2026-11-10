import { describe, expect, it } from "vitest";

// The guard rail the project has no linter for: every request goes through api/client.ts, so the
// ok-check and the error type can't quietly fork again in a sixth module. Vite hands the test
// every source file's text at build time; no filesystem access needed.
const sources = import.meta.glob<string>("../**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true });

describe("the API client", () => {
  it("is the only source file that calls fetch directly", () => {
    const offenders = Object.entries(sources)
      // Keys are relative to this file: the client is "./client.ts", everything else "../…".
      .filter(([path]) => !/\.test\.tsx?$/.test(path) && path !== "./client.ts")
      .filter(([, text]) => /\bfetch\(/.test(text))
      .map(([path]) => path.replace(/^\.\.\//, ""));

    expect(offenders).toEqual([]);
  });
});
