import { useEffect, useId, useRef, useState, type ReactNode } from "react";

/** A button that opens a small panel below it. The panel stays open while you
 *  work inside it (forms, selects) and closes on Escape or a click outside. */
export function Popover({ label, ariaLabel, children, align = "right", className }: {
  label: ReactNode; ariaLabel: string; children: ReactNode | ((close: () => void) => ReactNode);
  align?: "left" | "right"; className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  useEffect(() => { if (open) setMounted(true); }, [open]);
  const root = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  const close = () => setOpen(false);
  // Open towards the side with room, so the panel never slides under the sidebar.
  const [side, setSide] = useState(align);
  const toggle = () => {
    const rect = root.current?.getBoundingClientRect();
    if (!open && rect) {
      const width = Math.min(420, window.innerWidth * 0.9);
      setSide(align === "right" ? (rect.right - width < 300 ? "left" : "right")
        : (rect.left + width > window.innerWidth ? "right" : "left"));
    }
    setOpen(!open);
  };
  return (
    <div className={`popover${className ? ` ${className}` : ""}`} ref={root}>
      <button type="button" aria-label={ariaLabel} aria-expanded={open} aria-controls={id}
              className={open ? "active" : undefined} onClick={toggle}>{label}</button>
      {/* Stays mounted once opened (hidden when closed) so forms and running
          operations inside keep their state. */}
      {(open || mounted) && <div id={id} className={`popover-panel popover-${side}`} role="group"
                       aria-label={ariaLabel} hidden={!open}>
        {typeof children === "function" ? children(close) : children}
      </div>}
    </div>
  );
}
