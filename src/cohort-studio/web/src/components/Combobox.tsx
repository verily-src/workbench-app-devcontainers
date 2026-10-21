import { useEffect, useId, useMemo, useRef, useState } from "react";

export interface ComboOption { id: string; label: string; hint?: string }

interface Props {
  value: string;
  options: ComboOption[];
  onChange: (id: string) => void;
  label: string;
  placeholder?: string;
}

export function Combobox({ value, options, onChange, label, placeholder }: Props) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  const listRef = useRef<HTMLUListElement>(null);
  const selected = options.find((o) => o.id === value);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return options;
    return options.filter((o) =>
      `${o.label} ${o.hint ?? ""}`.toLowerCase().includes(needle));
  }, [q, options]);

  useEffect(() => { setActive(0); }, [q]);
  useEffect(() => {
    listRef.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  const show = () => {
    setQ("");
    setActive(Math.max(0, options.findIndex((o) => o.id === value)));
    setOpen(true);
  };
  const pick = (o?: ComboOption) => {
    if (o) onChange(o.id);
    setOpen(false);
  };

  const onKey = (e: React.KeyboardEvent) => {
    const last = filtered.length - 1;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) show(); else setActive((a) => Math.min(a + 1, last));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Home" && open) {
      e.preventDefault(); setActive(0);
    } else if (e.key === "End" && open) {
      e.preventDefault(); setActive(last);
    } else if (e.key === "Enter" && open) {
      e.preventDefault(); pick(filtered[active]);
    } else if (e.key === "Escape" && open) {
      e.preventDefault(); setOpen(false);
    }
  };

  const optId = (i: number) => `${listId}-${i}`;
  return (
    <div className="combo">
      <input type="text" role="combobox" aria-label={label} aria-expanded={open}
             aria-controls={listId} aria-autocomplete="list"
             aria-activedescendant={open && filtered[active] ? optId(active) : undefined}
             className="combo-input"
             placeholder={(open && selected?.label) || placeholder || "Search…"}
             value={open ? q : selected?.label ?? ""}
             onFocus={show} onClick={() => !open && show()}
             onBlur={() => setOpen(false)}
             onChange={(e) => { setQ(e.target.value); setOpen(true); }}
             onKeyDown={onKey} />
      {open && (
        <ul className="combo-list" role="listbox" id={listId} ref={listRef}
            aria-label={label}>
          {filtered.length === 0 && <li className="combo-empty">No matches</li>}
          {filtered.map((o, i) => (
            <li key={o.id} id={optId(i)} role="option"
                aria-selected={i === active}
                className={`combo-option${i === active ? " active" : ""}${o.id === value ? " current" : ""}`}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => { e.preventDefault(); pick(o); }}>
              <span className="combo-label">{o.label}</span>
              {o.hint && <span className="combo-hint">{o.hint}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
