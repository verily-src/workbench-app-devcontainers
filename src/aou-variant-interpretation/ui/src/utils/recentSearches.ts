import type { HpoTerm } from "../api/conditions";

// The entry page's "Recent searches" menu, and the drawer's: the criteria of the last few searches
// that loaded, kept in this browser's localStorage. Only what was searched for (variant IDs and
// condition concepts, with what their chips show) is stored -- never results or participant
// counts. A per-browser convenience: storage can be empty, full, blocked or cleared, and every
// read and write here tolerates that by treating it as "no history" rather than failing.

// Bumped when the shape changes: entries in an older shape fail validation and are dropped, which
// is simpler than migrating a convenience. v1 held one `condition` where v2 holds `conditions`.
// A condition's estimate and HPO term were added within v2: both optional, so earlier entries
// still load, their chips just without them.
const STORAGE_KEY = "via.recentSearches.v2";
const MAX_SEARCHES = 20;

/** A picked condition as the form needs it back: ConditionConcept, with the extras optional. */
export interface RecentSearchCondition {
  conceptId: number;
  name: string;
  estimatedParticipantCount?: number | null;
  hpo?: HpoTerm | null;
}

export interface RecentSearch {
  variants: string[];
  /** The picked conditions, in the order they were picked; empty when the search had none. */
  conditions: RecentSearchCondition[];
  /** When it was last run, as epoch milliseconds. */
  searchedAt: number;
}

function isHpoTerm(value: unknown): value is HpoTerm {
  if (typeof value !== "object" || value === null) return false;
  const term = value as Record<string, unknown>;
  return typeof term.id === "string" && typeof term.name === "string" && (term.match === "exact" || term.match === "approximate");
}

function isCondition(value: unknown): value is RecentSearchCondition {
  if (typeof value !== "object" || value === null) return false;
  const condition = value as Record<string, unknown>;
  return (
    typeof condition.conceptId === "number" &&
    typeof condition.name === "string" &&
    (condition.estimatedParticipantCount === undefined ||
      condition.estimatedParticipantCount === null ||
      typeof condition.estimatedParticipantCount === "number") &&
    (condition.hpo === undefined || condition.hpo === null || isHpoTerm(condition.hpo))
  );
}

function isRecentSearch(value: unknown): value is RecentSearch {
  if (typeof value !== "object" || value === null) return false;
  const search = value as Record<string, unknown>;
  return (
    Array.isArray(search.variants) &&
    search.variants.every((variant) => typeof variant === "string") &&
    typeof search.searchedAt === "number" &&
    Array.isArray(search.conditions) &&
    search.conditions.every(isCondition)
  );
}

/** Newest first. Anything unreadable -- storage blocked, or data from an older format -- is dropped. */
export function loadRecentSearches(): RecentSearch[] {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter(isRecentSearch).slice(0, MAX_SEARCHES) : [];
  } catch {
    return [];
  }
}

function save(searches: RecentSearch[]) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(searches));
  } catch {
    // Storage full or blocked: history just isn't kept.
  }
}

/**
 * Same variants and same conditions, each in any order: re-running a search moves it to the top.
 * Conditions are OR'd, so their order doesn't change the search.
 */
function sameCriteria(a: Omit<RecentSearch, "searchedAt">, b: Omit<RecentSearch, "searchedAt">) {
  const variants = (search: typeof a) => [...search.variants].sort().join("\n");
  const conditions = (search: typeof a) =>
    search.conditions
      .map((condition) => condition.conceptId)
      .sort((x, y) => x - y)
      .join(",");
  return variants(a) === variants(b) && conditions(a) === conditions(b);
}

/** Adds a search that just loaded, at the top, replacing an earlier run of the same criteria. */
export function recordRecentSearch(search: Omit<RecentSearch, "searchedAt">, now = Date.now()) {
  if (search.variants.length === 0) return;
  const others = loadRecentSearches().filter((existing) => !sameCriteria(existing, search));
  save([{ ...search, searchedAt: now }, ...others].slice(0, MAX_SEARCHES));
}

export function clearRecentSearches() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to clear if storage is unavailable.
  }
}

const RELATIVE_TIME = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** "just now", "5 minutes ago", "yesterday", "3 weeks ago". */
export function describeSearchedAt(searchedAt: number, now = Date.now()): string {
  const seconds = Math.round((searchedAt - now) / 1000);
  if (Math.abs(seconds) < 60) return "just now";
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["minute", 60],
    ["hour", 60 * 60],
    ["day", 60 * 60 * 24],
    ["week", 60 * 60 * 24 * 7],
    ["month", 60 * 60 * 24 * 30],
    ["year", 60 * 60 * 24 * 365],
  ];
  // The largest unit that fits at least once.
  let [unit, size] = units[0];
  for (const candidate of units) {
    if (Math.abs(seconds) >= candidate[1]) [unit, size] = candidate;
  }
  return RELATIVE_TIME.format(Math.round(seconds / size), unit);
}
