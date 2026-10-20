/**
 * Lightweight UI primitives styled to match the Verily Workbench design language.
 * Replace imports with @verily-src/react-design-system when your registry is wired.
 */
import type { CSSProperties, ReactNode } from "react";

const btnBase: CSSProperties = {
  borderRadius: "var(--wb-radius)",
  padding: "8px 16px",
  fontWeight: 600,
  fontSize: 14,
  cursor: "pointer",
  border: "none",
  fontFamily: "var(--wb-font)",
  transition: "background 0.15s, box-shadow 0.15s",
  lineHeight: "20px",
};

export function Button(props: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  disabled?: boolean;
  type?: "button" | "submit";
  size?: "sm" | "md";
}) {
  const { children, onClick, variant = "secondary", disabled, type = "button", size = "md" } = props;
  const style: CSSProperties = { ...btnBase };
  if (size === "sm") {
    style.padding = "4px 12px";
    style.fontSize = 13;
  }
  if (variant === "primary") {
    style.background = "var(--wb-primary)";
    style.color = "#fff";
  } else if (variant === "danger") {
    style.background = "var(--wb-danger)";
    style.color = "#fff";
  } else if (variant === "ghost") {
    style.background = "transparent";
    style.color = "var(--wb-primary)";
  } else {
    style.background = "var(--wb-surface)";
    style.color = "var(--wb-text)";
    style.border = "1px solid var(--wb-border)";
  }
  if (disabled) {
    style.opacity = 0.45;
    style.cursor = "not-allowed";
  }
  return (
    <button type={type} style={style} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}

export function Card(props: { title?: string; children: ReactNode; style?: CSSProperties; flat?: boolean }) {
  const card: CSSProperties = {
    background: "var(--wb-surface)",
    borderRadius: "var(--wb-radius)",
    padding: 20,
    marginBottom: 12,
    ...(props.flat ? {} : { boxShadow: "0 1px 3px rgba(0,0,0,0.06)" }),
    ...props.style,
  };
  return (
    <div style={card}>
      {props.title ? (
        <h3 style={{ margin: "0 0 14px", fontSize: 16, fontWeight: 600, color: "var(--wb-text)" }}>{props.title}</h3>
      ) : null}
      {props.children}
    </div>
  );
}

export type BadgeTone = "neutral" | "info" | "success" | "warn" | "danger" | "running";

const toneBg: Record<BadgeTone, string> = {
  success: "#dafbe1",
  info: "#ddf4ff",
  warn: "#fff8c5",
  danger: "#ffebe9",
  running: "#eef6fc",
  neutral: "#ebebeb",
};
const toneColor: Record<BadgeTone, string> = {
  success: "var(--wb-success)",
  info: "var(--wb-info)",
  warn: "var(--wb-warning)",
  danger: "var(--wb-danger)",
  running: "var(--wb-accent)",
  neutral: "#636363",
};

export function Badge(props: { children: ReactNode; tone?: BadgeTone }) {
  const tone = props.tone ?? "neutral";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 10px",
        borderRadius: 4,
        fontSize: 12,
        fontWeight: 600,
        background: toneBg[tone],
        color: toneColor[tone],
        lineHeight: "20px",
        whiteSpace: "nowrap",
      }}
    >
      {props.children}
    </span>
  );
}

export function Tabs(props: {
  labels: string[];
  active: number;
  onChange: (i: number) => void;
  disabled?: boolean[];
}) {
  return (
    <div style={{ display: "flex", gap: 0, borderBottom: "2px solid var(--wb-border)", marginBottom: 20 }}>
      {props.labels.map((l, i) => {
        const dis = props.disabled?.[i];
        const active = props.active === i;
        return (
          <button
            key={l}
            type="button"
            onClick={() => !dis && props.onChange(i)}
            style={{
              padding: "12px 18px",
              border: "none",
              background: "transparent",
              cursor: dis ? "not-allowed" : "pointer",
              opacity: dis ? 0.4 : 1,
              borderBottom: active ? "2px solid var(--wb-primary)" : "2px solid transparent",
              marginBottom: -2,
              fontWeight: active ? 600 : 400,
              fontSize: 14,
              color: active ? "var(--wb-primary)" : "var(--wb-muted)",
              fontFamily: "var(--wb-font)",
              transition: "color 0.15s",
            }}
          >
            {l}
          </button>
        );
      })}
    </div>
  );
}

export function Stack(props: { children: ReactNode; gap?: number; direction?: "row" | "column" }) {
  return (
    <div style={{ display: "flex", flexDirection: props.direction ?? "column", gap: props.gap ?? 12 }}>
      {props.children}
    </div>
  );
}

export function Input(props: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  style?: CSSProperties;
}) {
  return (
    <input
      value={props.value}
      placeholder={props.placeholder}
      onChange={(e) => props.onChange(e.target.value)}
      style={{
        padding: "8px 12px",
        borderRadius: "var(--wb-radius)",
        border: "1px solid var(--wb-border)",
        minWidth: 220,
        fontFamily: "var(--wb-font)",
        fontSize: 14,
        outline: "none",
        transition: "border-color 0.15s",
        ...props.style,
      }}
      onFocus={(e) => (e.target.style.borderColor = "var(--wb-primary)")}
      onBlur={(e) => (e.target.style.borderColor = "var(--wb-border)")}
    />
  );
}

export function Select(props: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
      style={{
        padding: "8px 12px",
        borderRadius: "var(--wb-radius)",
        border: "1px solid var(--wb-border)",
        fontFamily: "var(--wb-font)",
        fontSize: 14,
        background: "var(--wb-surface)",
        outline: "none",
      }}
    >
      {props.options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function SectionLabel(props: { children: ReactNode }) {
  return (
    <div
      style={{
        fontSize: 11,
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.06em",
        color: "var(--wb-sidebar-muted)",
        padding: "16px 20px 6px",
      }}
    >
      {props.children}
    </div>
  );
}
