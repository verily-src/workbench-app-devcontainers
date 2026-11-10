import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { readPreferences, updatePreferences, usePreference } from "./preferences";

describe("preferences", () => {
  afterEach(() => {
    window.localStorage.clear();
  });

  it("falls back to the defaults when nothing is stored, or what is stored is unreadable", () => {
    expect(readPreferences()).toEqual({ showUsageMeter: false, demoMode: false });

    window.localStorage.setItem("via.preferences.v1", "not json");
    expect(readPreferences()).toEqual({ showUsageMeter: false, demoMode: false });

    window.localStorage.setItem("via.preferences.v1", JSON.stringify({ showUsageMeter: "yes" }));
    expect(readPreferences().showUsageMeter).toBe(false);
  });

  it("stores an update over the current preferences", () => {
    updatePreferences({ showUsageMeter: true });
    expect(readPreferences().showUsageMeter).toBe(true);
    updatePreferences({});
    expect(readPreferences().showUsageMeter).toBe(true);
    updatePreferences({ demoMode: true });
    expect(readPreferences()).toEqual({ showUsageMeter: true, demoMode: true });
  });

  it("re-renders every reader when one of them sets a preference", () => {
    const first = renderHook(() => usePreference("showUsageMeter"));
    const second = renderHook(() => usePreference("showUsageMeter"));
    expect(first.result.current[0]).toBe(false);

    act(() => second.result.current[1](true));

    expect(first.result.current[0]).toBe(true);
    expect(second.result.current[0]).toBe(true);
    expect(readPreferences().showUsageMeter).toBe(true);
  });
});
