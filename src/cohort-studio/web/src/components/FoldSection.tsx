import { useState } from "react";
import type { ReactNode } from "react";

const KEY = (id: string) => `cohort-studio.fold.${id}`;

/** A left-pane section with a header that folds it; the state is remembered per browser. */
export function FoldSection({ id, title, badge, children }: {
  id: string; title: string; badge?: ReactNode; children: ReactNode;
}) {
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem(KEY(id)) !== "0"; } catch { return true; }
  });
  const toggle = () => {
    setOpen(!open);
    try { localStorage.setItem(KEY(id), open ? "0" : "1"); } catch { /* private mode */ }
  };
  const body = `fold-${id}`;
  return (
    <section className={`fold-section${open ? "" : " folded"}`} data-section={id}>
      <h3 className="section-label fold-head">
        <button type="button" aria-expanded={open} aria-controls={body} onClick={toggle}>
          <svg className="fold-chevron" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
            <path d="M3 2l4 3-4 3" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>{title}</span>
          {badge != null && <span className="fold-badge">{badge}</span>}
        </button>
      </h3>
      <div id={body} className="fold-body" hidden={!open}>{children}</div>
    </section>
  );
}
