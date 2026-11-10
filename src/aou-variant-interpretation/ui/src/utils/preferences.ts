// Per-browser display preferences, kept in localStorage the way recent searches are: a
// convenience that may be empty, blocked or cleared, so every read falls back to the defaults and
// every write may silently do nothing. Components read a preference through usePreference, which
// re-renders them when it changes anywhere in the page (the settings page flips a switch, the
// top bar follows) or in another tab.

import { useCallback, useSyncExternalStore } from "react";

// Bumped when the shape changes; an older shape fails validation and falls back to the defaults.
const STORAGE_KEY = "via.preferences.v1";

export interface Preferences {
  /** Show the BigQuery usage meter in the top bar. Off by default: it's a developer's readout. */
  showUsageMeter: boolean;
  /** Offer the curated example searches under the variants box. Off by default: they're for demos. */
  demoMode: boolean;
}

const DEFAULTS: Preferences = {
  showUsageMeter: false,
  demoMode: false,
};

const bool = (value: unknown, fallback: boolean) => (typeof value === "boolean" ? value : fallback);

function isPreferences(value: unknown): value is Partial<Preferences> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The stored preferences over the defaults; the defaults alone when storage is unreadable. */
export function readPreferences(): Preferences {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}");
    if (!isPreferences(parsed)) return DEFAULTS;
    return {
      showUsageMeter: bool(parsed.showUsageMeter, DEFAULTS.showUsageMeter),
      demoMode: bool(parsed.demoMode, DEFAULTS.demoMode),
    };
  } catch {
    return DEFAULTS;
  }
}

const listeners = new Set<() => void>();

/** Stores the given preferences over the current ones and tells every usePreference about it. */
export function updatePreferences(patch: Partial<Preferences>) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...readPreferences(), ...patch }));
  } catch {
    // Storage full or blocked: the preference isn't kept.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  // Another tab changing the same key.
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === STORAGE_KEY) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** One preference as state: its current value, and a setter that stores it for every reader. */
export function usePreference<K extends keyof Preferences>(key: K): [Preferences[K], (value: Preferences[K]) => void] {
  const value = useSyncExternalStore(subscribe, () => readPreferences()[key]);
  const set = useCallback((next: Preferences[K]) => updatePreferences({ [key]: next } as Partial<Preferences>), [key]);
  return [value, set];
}
