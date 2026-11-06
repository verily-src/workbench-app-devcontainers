import type { Filter } from "./types";

const UNIT_LABEL = { day: "day", week: "week", month: "month", year: "year" } as const;

/** Short text for a filter chip, the PDF and saved-view summaries. */
export function describeFilter(f: Filter, words = false): string {
  if (f.kind === "any") {
    return (f.groups ?? []).map((g) => `(${g.map((x) => describeFilter(x, words)).join(" and ")})`).join(" or ");
  }
  if (f.kind === "categorical") return `${f.column}: ${(f.values ?? []).join(", ")}`;
  if (f.kind === "date") {
    if (f.last) return `${f.column}: last ${f.last} ${UNIT_LABEL[f.unit ?? "day"]}${f.last === 1 ? "" : "s"}`;
    if (f.start && f.end) return `${f.column}: ${f.start} ${words ? "to" : "–"} ${f.end}`;
    if (f.start) return `${f.column}: ${words ? "from" : "≥"} ${f.start}`;
    return `${f.column}: ${words ? "until" : "≤"} ${f.end ?? ""}`;
  }
  return f.max === Number.MAX_VALUE ? `${f.column}: ${words ? "at least" : "≥"} ${f.min}`
    : f.min === -Number.MAX_VALUE ? `${f.column}: ${words ? "at most" : "≤"} ${f.max}`
      : `${f.column}: ${f.min}${words ? " to " : "–"}${f.max}`;
}
