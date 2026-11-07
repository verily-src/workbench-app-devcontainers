import "./DashboardFilters.css";
import type { ColumnProfile, Filter } from "../types";
import { describeFilter } from "../filterText";
import { notApplicable } from "../dashboardFilters";
import { Popover } from "./Popover";

/** Filters that apply to every tab with a matching column. Shown only when there are any. */
export function DashboardFilters({ filters, columns, onChange, onEditHere }: {
  filters: Filter[]; columns: ColumnProfile[] | undefined;
  onChange: (next: Filter[]) => void;
  /** Move one back into the active tab's own filters, to edit it there. */
  onEditHere: (f: Filter) => void;
}) {
  if (!filters.length) return null;
  return (
    <div className="dashboard-filters" role="region" aria-label="Dashboard filters">
      <span className="dashboard-filters-label">Dashboard filters</span>
      {filters.map((f) => {
        const reason = columns ? notApplicable(columns, f) : null;
        const text = describeFilter(f);
        return (
          <span key={f.column} className={`chip dashboard-chip${reason ? " off" : ""}`} title={reason ?? undefined}>
            <Popover align="left" ariaLabel={`Dashboard filter ${text}`}
                     label={<>{text}{reason && <span className="dashboard-off"> · not in this tab</span>}</>}>
              {(close) => <div className="popover-menu">
                <button type="button" disabled={Boolean(reason)} title={reason ?? undefined}
                        onClick={() => { onEditHere(f); close(); }}>Edit on this tab</button>
                <button type="button" onClick={() => { onChange(filters.filter((o) => o !== f)); close(); }}>
                  Remove from all tabs</button>
              </div>}
            </Popover>
            <button type="button" className="quiet" aria-label={`Remove dashboard filter ${text}`}
                    onClick={() => onChange(filters.filter((o) => o !== f))}>✕</button>
          </span>
        );
      })}
      {filters.length > 1 && <button type="button" className="quiet chip clear" onClick={() => onChange([])}>
        Clear all</button>}
    </div>
  );
}
