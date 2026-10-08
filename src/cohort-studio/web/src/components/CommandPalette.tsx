import { useEffect, useMemo, useRef, useState } from "react";

export interface Command {
  id: string;
  label: string;
  hint?: string;
  group: string;
  run: () => void;
}

interface Props {
  open: boolean;
  commands: Command[];
  onClose: () => void;
}

// Linear-style ⌘K palette: fuzzy-filter every navigable thing (views, open
// tabs, datasources, tables, actions) and run it. All client-side — the
// command list is built by App from state it already holds.
export function CommandPalette({ open, commands, onClose }: Props) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) { setQ(""); setActive(0); setTimeout(() => inputRef.current?.focus(), 0); }
  }, [open]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return commands;
    // Subsequence match so "wfhello" finds "Workflows: hello".
    const matches = (s: string) => {
      let i = 0;
      for (const ch of s.toLowerCase()) if (ch === needle[i]) i++;
      return i === needle.length;
    };
    return commands.filter((c) =>
      c.label.toLowerCase().includes(needle)
      || `${c.group} ${c.label}`.toLowerCase().includes(needle)
      || matches(`${c.group} ${c.label}`));
  }, [q, commands]);

  useEffect(() => { setActive(0); }, [q]);
  if (!open) return null;

  const pick = (i: number) => {
    const cmd = filtered[i];
    if (cmd) { cmd.run(); onClose(); }
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, filtered.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); pick(active); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  };

  return (
    <div className="palette-overlay" onMouseDown={onClose}>
      <div className="palette" onMouseDown={(e) => e.stopPropagation()}>
        <input ref={inputRef} className="palette-input" value={q}
               placeholder="Jump to a view, table, tab, or action…"
               onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} />
        <div className="palette-list">
          {filtered.length === 0 && (
            <div className="palette-empty">No matches</div>
          )}
          {filtered.map((c, i) => (
            <div key={c.id}
                 className={`palette-item${i === active ? " active" : ""}`}
                 onMouseEnter={() => setActive(i)}
                 onClick={() => pick(i)}>
              <span className="palette-group">{c.group}</span>
              <span className="palette-label">{c.label}</span>
              {c.hint && <span className="palette-hint">{c.hint}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
