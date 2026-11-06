import { useEffect, useState } from "react";
import type { ColumnProfile, DateUnit, Filter, ParamBinding, Parameter } from "../types";

interface Props {
  columns: ColumnProfile[];
  filters: Filter[];
  onChange: (filters: Filter[]) => void;
  /** Tab parameters a bound can follow. */
  parameters?: Parameter[];
}

/** A binding with one bound changed (name "" removes it); undefined when empty. */
function rebind(param: ParamBinding | undefined, bound: keyof ParamBinding, name: string): ParamBinding | undefined {
  const next: ParamBinding = { ...(param ?? {}) };
  if (name) next[bound] = name; else delete next[bound];
  return Object.keys(next).length ? next : undefined;
}

/** "Follows: <parameter>" for one filter bound. */
function Follows({ label, value, options, onChange }: {
  label: string; value?: string; options: Parameter[]; onChange: (name: string) => void;
}) {
  if (!options.length && !value) return null;
  return (
    <label className="filter-follows">Follows
      <select aria-label={label} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">—</option>
        {options.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
      </select>
    </label>
  );
}

function upsert(filters: Filter[], next: Filter | null, column: string):
    Filter[] {
  const rest = filters.filter((f) => f.column !== column);
  return next ? [...rest, next] : rest;
}

function CustomValue({ onAdd }: { onAdd: (value: string) => void }) {
  const [value, setValue] = useState("");
  return <form className="filter-custom-value" onSubmit={(event) => {
    event.preventDefault();
    if (value.trim()) { onAdd(value); setValue(""); }
  }}>
    <input aria-label="Custom filter value" value={value} placeholder="Add a value"
      onChange={(event) => setValue(event.target.value)} />
    <button type="submit" disabled={!value.trim()}>Add</button>
  </form>;
}

/** Values of one categorical column, with a search box once the list is long.
 *  Selected values always stay listed. */
function ValueList({ name, values, selected, onToggle }: {
  name: string; values: string[]; selected: string[]; onToggle: (value: string) => void;
}) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const shown = q ? values.filter((v) => selected.includes(v) || v.toLowerCase().includes(q)) : values;
  return <>
    {values.length > 8 && (
      <input type="search" className="filter-search" aria-label={`Search ${name} values`}
             placeholder="Search values" value={query} onChange={(e) => setQuery(e.target.value)} />
    )}
    {shown.map((v) => (
      <label key={v}>
        <input type="checkbox" checked={selected.includes(v)} onChange={() => onToggle(v)} />
        {v}
      </label>
    ))}
    {q && !shown.some((v) => !selected.includes(v)) && (
      <div className="settings-hint">No {selected.length ? "other " : ""}values match "{query.trim()}".</div>
    )}
  </>;
}

/** A date column: Between two dates (end inclusive), or the last N days/weeks/months/years. */
function DateFilter({ col, active, onChange, parameters = [] }: {
  col: ColumnProfile; active?: Filter; onChange: (next: Filter | null) => void; parameters?: Parameter[];
}) {
  const dateParams = parameters.filter((p) => p.kind === "date");
  const name = col.label || col.name;
  // The mode is the user's choice, not derived from the applied filter, so clearing
  // the count while typing doesn't flip back to Between.
  const [mode, setMode] = useState<"between" | "last">(active?.last ? "last" : "between");
  const [lastDraft, setLastDraft] = useState(String(active?.last ?? 30));
  const [unit, setUnit] = useState<DateUnit>(active?.unit ?? "day");
  // Follow filters applied from elsewhere (a saved cohort, another tab).
  useEffect(() => {
    if (active?.last) {
      setMode("last"); setLastDraft(String(active.last)); setUnit(active.unit ?? "day");
    } else if (active) {
      setMode("between");
    }
  }, [active?.last, active?.unit, active?.start, active?.end]); // eslint-disable-line react-hooks/exhaustive-deps
  // param: undefined keeps the current binding, null removes it.
  const between = (start?: string, end?: string, param?: ParamBinding | null) => {
    const binding = param === undefined ? active?.param : param ?? undefined;
    onChange(start || end ? { column: col.name, kind: "date", ...(start ? { start } : {}), ...(end ? { end } : {}),
                              ...(binding ? { param: binding } : {}) } : null);
  };
  const follow = (bound: "start" | "end", name: string) => {
    const p = dateParams.find((x) => x.name === name);
    const start = bound === "start" && p ? String(p.value) : active?.start;
    const end = bound === "end" && p ? String(p.value) : active?.end;
    between(start, end, rebind(active?.param, bound, name) ?? null);
  };
  const last = (n: string, u: DateUnit) => {
    const value = Number(n);
    onChange(Number.isInteger(value) && value > 0 ? { column: col.name, kind: "date", last: value, unit: u } : null);
  };
  return (
    <div className="date-filter">
      <div className="date-filter-modes" role="radiogroup" aria-label={`${name} date filter`}>
        {(["between", "last"] as const).map((m) => (
          <button key={m} type="button" role="radio" aria-checked={mode === m}
                  onClick={() => {
                    if (m === mode) return;
                    setMode(m);
                    if (m === "last") last(lastDraft, unit);
                    else if (active?.last) onChange(null);
                  }}>
            {m === "between" ? "Between" : "Last"}
          </button>
        ))}
      </div>
      {mode === "between" ? (
        <div className="date-filter-range">
          <input type="date" aria-label={`From ${name}`} min={col.min_date} max={col.max_date}
                 disabled={Boolean(active?.param?.start)} value={active?.start ?? ""}
                 onChange={(e) => between(e.target.value || undefined, active?.end)} />
          <span aria-hidden>–</span>
          <input type="date" aria-label={`To ${name}`} min={col.min_date} max={col.max_date}
                 disabled={Boolean(active?.param?.end)} value={active?.end ?? ""}
                 onChange={(e) => between(active?.start, e.target.value || undefined)} />
        </div>
      ) : null}
      {mode === "between" && dateParams.length > 0 ? (
        <div className="filter-follows-row">
          <Follows label={`From ${name} follows`} value={active?.param?.start} options={dateParams}
                   onChange={(n) => follow("start", n)} />
          <Follows label={`To ${name} follows`} value={active?.param?.end} options={dateParams}
                   onChange={(n) => follow("end", n)} />
        </div>
      ) : null}
      {mode === "between" ? null : (
        <div className="date-filter-range">
          <input type="number" min={1} max={10000} step={1} aria-label={`Last ${name} count`} value={lastDraft}
                 onChange={(e) => { setLastDraft(e.target.value); last(e.target.value, unit); }} />
          <select aria-label={`Last ${name} unit`} value={unit}
                  onChange={(e) => { const u = e.target.value as DateUnit; setUnit(u); last(lastDraft, u); }}>
            {(["day", "week", "month", "year"] as const).map((u) => <option key={u} value={u}>{u}s</option>)}
          </select>
        </div>
      )}
      {(col.min_date || col.max_date) && (
        <div className="settings-hint">Data from {col.min_date ?? "?"} to {col.max_date ?? "?"}</div>
      )}
      {active && <button type="button" className="link" onClick={() => onChange(null)}>Clear</button>}
    </div>
  );
}

export function FilterPanel({ columns, filters, onChange, parameters = [] }: Props) {
  const numberParams = parameters.filter((p) => p.kind === "number");
  const byColumn = new Map(filters.map((f) => [f.column, f]));
  // Groups the user opened stay open while their filter is edited or cleared.
  const [opened, setOpened] = useState<Set<string>>(() => new Set());

  const toggleValue = (col: ColumnProfile, value: string) => {
    const current = byColumn.get(col.name)?.values ?? [];
    const values = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    onChange(upsert(filters, values.length
      ? { column: col.name, kind: "categorical", values } : null, col.name));
  };

  // param: undefined keeps the current binding (minus an edited bound), null removes it.
  const setRange = (col: ColumnProfile, lo: number, hi: number, edited?: "min" | "max",
                    explicit?: ParamBinding | null) => {
    const current = byColumn.get(col.name)?.param;
    const param = explicit === undefined ? (edited ? rebind(current, edited, "") : current) : explicit ?? undefined;
    const active = Boolean(param) || lo > (col.min ?? -Infinity) || hi < (col.max ?? Infinity);
    onChange(upsert(filters, active
      ? { column: col.name, kind: "range", min: lo, max: hi, ...(param ? { param } : {}) } : null,
      col.name));
  };
  const followRange = (col: ColumnProfile, bound: "min" | "max", name: string) => {
    const current = byColumn.get(col.name);
    const p = numberParams.find((x) => x.name === name);
    const lo = bound === "min" && p ? Number(p.value) : current?.min ?? col.min ?? 0;
    const hi = bound === "max" && p ? Number(p.value) : current?.max ?? col.max ?? 0;
    setRange(col, lo, hi, undefined, rebind(current?.param, bound, name) ?? null);
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
                   open={opened.has(col.name) || Boolean(active)}
                   onToggle={(e) => {
                     const isOpen = (e.currentTarget as HTMLDetailsElement).open;
                     setOpened((prev) => {
                       if (isOpen === prev.has(col.name)) return prev;
                       const next = new Set(prev);
                       if (isOpen) next.add(col.name); else next.delete(col.name);
                       return next;
                     });
                   }}>
            <summary>
              {col.label || col.name}
              {active && <span className="badge">
                {col.filter_kind === "categorical"
                  ? active.values?.length : col.filter_kind === "date" ? "date" : "range"}</span>}
            </summary>
            {col.filter_kind === "date" ? (
              <DateFilter col={col} active={active} parameters={parameters}
                          onChange={(next) => onChange(upsert(filters, next, col.name))} />
            ) : col.filter_kind === "categorical" ? (
              <div className="filter-values">
                <ValueList name={col.label || col.name}
                           values={[...new Set([...(col.values ?? []), ...(active?.values ?? [])])]}
                           selected={active?.values ?? []} onToggle={(v) => toggleValue(col, v)} />
                <CustomValue onAdd={(value) => {
                  const values = byColumn.get(col.name)?.values ?? [];
                  if (!values.includes(value)) onChange(upsert(filters,
                    { column: col.name, kind: "categorical", values: [...values, value] }, col.name));
                }} />
              </div>
            ) : (
              <div className="range-inputs">
                <input
                  type="number" step="any"
                  aria-label={`Minimum ${col.label || col.name}`}
                  placeholder="No minimum"
                  value={active?.min === -Number.MAX_VALUE ? "" : active?.min ?? col.min ?? 0}
                  disabled={Boolean(active?.param?.min)}
                  onChange={(e) => setRange(col, e.target.value === "" ? -Number.MAX_VALUE : Number(e.target.value),
                    active?.max ?? col.max ?? 0, "min")}
                />
                <input
                  type="number" step="any"
                  aria-label={`Maximum ${col.label || col.name}`}
                  placeholder="No maximum"
                  value={active?.max === Number.MAX_VALUE ? "" : active?.max ?? col.max ?? 0}
                  disabled={Boolean(active?.param?.max)}
                  onChange={(e) => setRange(col,
                    active?.min ?? col.min ?? 0, e.target.value === "" ? Number.MAX_VALUE : Number(e.target.value), "max")}
                />
                {numberParams.length > 0 && <div className="filter-follows-row">
                  <Follows label={`Minimum ${col.label || col.name} follows`} value={active?.param?.min}
                           options={numberParams} onChange={(n) => followRange(col, "min", n)} />
                  <Follows label={`Maximum ${col.label || col.name} follows`} value={active?.param?.max}
                           options={numberParams} onChange={(n) => followRange(col, "max", n)} />
                </div>}
              </div>
            )}
          </details>
        );
      })}
    </>
  );
}
