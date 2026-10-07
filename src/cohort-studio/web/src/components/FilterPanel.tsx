import type { ColumnProfile, Filter } from "../types";

interface Props {
  columns: ColumnProfile[];
  filters: Filter[];
  onChange: (filters: Filter[]) => void;
}

function upsert(filters: Filter[], next: Filter | null, column: string):
    Filter[] {
  const rest = filters.filter((f) => f.column !== column);
  return next ? [...rest, next] : rest;
}

export function FilterPanel({ columns, filters, onChange }: Props) {
  const byColumn = new Map(filters.map((f) => [f.column, f]));

  const toggleValue = (col: ColumnProfile, value: string) => {
    const current = byColumn.get(col.name)?.values ?? [];
    const values = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    onChange(upsert(filters, values.length
      ? { column: col.name, kind: "categorical", values } : null, col.name));
  };

  const setRange = (col: ColumnProfile, lo: number, hi: number) => {
    const active = lo > (col.min ?? -Infinity) || hi < (col.max ?? Infinity);
    onChange(upsert(filters, active
      ? { column: col.name, kind: "range", min: lo, max: hi } : null,
      col.name));
  };

  const filterable = columns.filter((c) => c.filter_kind !== "none");
  if (!filterable.length) {
    return <div style={{ color: "var(--ink-muted)" }}>
      No filterable columns.</div>;
  }

  return (
    <>
      {filterable.map((col) => {
        const active = byColumn.get(col.name);
        return (
          <details key={col.name} className="filter-group"
                   open={Boolean(active)}>
            <summary>
              {col.name}
              {active && <span className="badge">
                {col.filter_kind === "categorical"
                  ? active.values?.length : "range"}</span>}
            </summary>
            {col.filter_kind === "categorical" ? (
              <div className="filter-values">
                {col.values?.map((v) => (
                  <label key={v}>
                    <input
                      type="checkbox"
                      checked={active?.values?.includes(v) ?? false}
                      onChange={() => toggleValue(col, v)}
                    />
                    {v}
                  </label>
                ))}
              </div>
            ) : (
              <div className="range-inputs">
                <input
                  type="number" step="any"
                  value={active?.min ?? col.min ?? 0}
                  onChange={(e) => setRange(col, Number(e.target.value),
                    active?.max ?? col.max ?? 0)}
                />
                <input
                  type="number" step="any"
                  value={active?.max ?? col.max ?? 0}
                  onChange={(e) => setRange(col,
                    active?.min ?? col.min ?? 0, Number(e.target.value))}
                />
              </div>
            )}
          </details>
        );
      })}
    </>
  );
}
