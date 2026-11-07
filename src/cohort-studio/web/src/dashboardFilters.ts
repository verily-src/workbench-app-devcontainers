import type { ColumnProfile, Filter } from "./types";

/** Why a dashboard filter doesn't apply to a tab with these columns, or null when it does.
 *  It applies when the tab has a column of the same name and the same filter kind. */
export function notApplicable(columns: ColumnProfile[], f: Filter): string | null {
  const col = columns.find((c) => c.name === f.column);
  if (!col) return `This tab has no ${f.column} column.`;
  if (col.filter_kind !== f.kind) return `${f.column} isn't a ${f.kind === "range" ? "number" : f.kind} field in this tab.`;
  return null;
}

/** The dashboard filters a tab adds to its own filters (both are ANDed). */
export function applicableFilters(columns: ColumnProfile[], dashboard: Filter[]): Filter[] {
  return dashboard.filter((f) => notApplicable(columns, f) === null);
}

/** A tab filter as a dashboard filter: parameters are per tab, so keep only the resolved values. */
export function asDashboardFilter(f: Filter): Filter {
  const { param: _param, ...rest } = f;
  return rest;
}

/** Add or replace the dashboard filter on this filter's column. */
export function withDashboardFilter(dashboard: Filter[], f: Filter): Filter[] {
  return [...dashboard.filter((d) => d.column !== f.column), asDashboardFilter(f)];
}
