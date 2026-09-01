import { useState, type ReactNode } from "react";

export function DatasetAccordion(props: { title: string; defaultOpen?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(props.defaultOpen ?? true);
  return (
    <div style={{ border: "1px solid var(--wb-border)", borderRadius: "var(--wb-radius)", marginBottom: 12 }}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        style={{
          width: "100%",
          textAlign: "left",
          padding: "12px 14px",
          background: "var(--wb-surface)",
          border: "none",
          fontWeight: 700,
          cursor: "pointer",
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>{props.title}</span>
        <span>{open ? "▾" : "▸"}</span>
      </button>
      {open ? <div style={{ padding: "0 12px 12px" }}>{props.children}</div> : null}
    </div>
  );
}
