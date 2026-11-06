/** "Match any group": alternative criteria, (A AND B) OR (C AND D).
 *  Edits the one {kind: "any"} filter of a tab; the sidebar filters still apply
 *  to every row. Each group uses the same filter controls as the sidebar. */
import { useState } from "react";
import type { ColumnProfile, Filter, Parameter } from "../types";
import { FilterPanel } from "./FilterPanel";
import { describeFilter } from "../filterText";

export const groupsFilter = (filters: Filter[]): Filter | undefined =>
  filters.find((f) => f.kind === "any");

/** Replace the tab's criteria groups; empty groups are dropped, none at all removes the filter. */
export function withGroups(filters: Filter[], groups: Filter[][]): Filter[] {
  const rest = filters.filter((f) => f.kind !== "any");
  const kept = groups.filter((g) => g.length > 0);
  return kept.length ? [...rest, { column: "", kind: "any", groups: kept }] : rest;
}

export function CriteriaGroups({ columns, filters, onChange, onClose, parameters = [] }: {
  columns: ColumnProfile[]; filters: Filter[]; parameters?: Parameter[];
  onChange: (filters: Filter[]) => void; onClose: () => void;
}) {
  const saved = groupsFilter(filters)?.groups ?? [];
  // One empty group may be open for editing before it has any filter.
  const [draftEmpty, setDraftEmpty] = useState(saved.length === 0);
  const groups = draftEmpty ? [...saved, []] : saved;
  const setGroup = (index: number, next: Filter[]) => {
    const all = groups.map((g, i) => (i === index ? next : g));
    if (draftEmpty && index === groups.length - 1 && next.length) setDraftEmpty(false);
    onChange(withGroups(filters, all));
  };
  return (
    <section className="derive-panel criteria-groups" aria-label="Match any group">
      <div className="criteria-head">
        <strong>Match any group</strong>
        <span className="settings-hint">
          Rows must match every filter in at least one group (and the sidebar filters, which apply to all).
        </span>
        <span className="jc-spacer" />
        <button type="button" className="quiet" aria-label="Close groups" onClick={onClose}>✕</button>
      </div>
      <div className="criteria-list">
        {groups.map((group, i) => (
          <div key={i} className="criteria-group" role="group" aria-label={`Group ${i + 1}`}>
            {i > 0 && <div className="criteria-or" aria-hidden>OR</div>}
            <div className="criteria-group-head">
              <strong>Group {i + 1}</strong>
              <span className="settings-hint">{group.length
                ? group.map((f) => describeFilter(f)).join(" and ") : "No filters yet — choose some below."}</span>
              <span className="jc-spacer" />
              <button type="button" className="link" aria-label={`Remove group ${i + 1}`}
                      onClick={() => {
                        if (draftEmpty && i === groups.length - 1) { setDraftEmpty(false); return; }
                        onChange(withGroups(filters, groups.filter((_, j) => j !== i)));
                      }}>Remove</button>
            </div>
            <div className="criteria-filters">
              <FilterPanel columns={columns} filters={group} parameters={parameters}
                           onChange={(next) => setGroup(i, next)} />
            </div>
          </div>
        ))}
      </div>
      <button type="button" className="link" disabled={draftEmpty}
              title={draftEmpty ? "Add a filter to the empty group first" : undefined}
              onClick={() => setDraftEmpty(true)}>+ Add OR group</button>
    </section>
  );
}
