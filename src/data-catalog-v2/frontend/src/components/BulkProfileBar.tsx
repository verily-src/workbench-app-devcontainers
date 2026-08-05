import { useState, type CSSProperties } from "react";
import type { BulkMode, BulkStatusResponse } from "../types/bulk";

/* ── Floating action bar (when tables selected) ─────────────────────────── */

const barStyle: CSSProperties = {
  position: "fixed",
  bottom: 80,
  left: "50%",
  transform: "translateX(-50%)",
  zIndex: 800,
  background: "var(--wb-primary, #1a5c5e)",
  color: "#fff",
  borderRadius: 12,
  padding: "10px 20px",
  display: "flex",
  alignItems: "center",
  gap: 14,
  boxShadow: "0 4px 20px rgba(0,0,0,0.25)",
  fontSize: 13,
  fontWeight: 500,
};

const btnStyle: CSSProperties = {
  background: "rgba(255,255,255,0.2)",
  color: "#fff",
  border: "1px solid rgba(255,255,255,0.3)",
  borderRadius: 6,
  padding: "5px 14px",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
};

const toggleStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  fontSize: 11,
  opacity: 0.9,
  cursor: "pointer",
  userSelect: "none",
};

const checkboxStyle: CSSProperties = {
  width: 14,
  height: 14,
  accentColor: "#fff",
  cursor: "pointer",
};

export function BulkActionBar(props: {
  count: number;
  onProfile: (mode: BulkMode, force: boolean) => void;
  onClear: () => void;
  disabled?: boolean;
  hasExistingProfiles?: boolean;
}) {
  const [force, setForce] = useState(false);

  if (props.count === 0) return null;

  return (
    <div style={barStyle}>
      <span>{props.count} table{props.count > 1 ? "s" : ""} selected</span>

      {props.hasExistingProfiles && (
        <label style={toggleStyle}>
          <input
            type="checkbox"
            checked={force}
            onChange={(e) => setForce(e.target.checked)}
            style={checkboxStyle}
          />
          Force re-profile
        </label>
      )}

      <button style={btnStyle} onClick={() => props.onProfile("technical", force)} disabled={props.disabled}>Technical</button>
      <button style={btnStyle} onClick={() => props.onProfile("semantic", force)} disabled={props.disabled}>Semantic</button>
      <button style={{ ...btnStyle, background: "rgba(255,255,255,0.35)" }} onClick={() => props.onProfile("both", force)} disabled={props.disabled}>Both</button>
      <button style={{ ...btnStyle, background: "transparent", borderColor: "transparent", opacity: 0.7 }} onClick={props.onClear}>Clear</button>
    </div>
  );
}

/* ── Progress drawer ─────────────────────────────────────────────────────── */

const drawerStyle: CSSProperties = {
  position: "fixed",
  bottom: 0,
  left: 0,
  right: 0,
  zIndex: 850,
  background: "#fff",
  borderTop: "2px solid var(--wb-primary, #1a5c5e)",
  boxShadow: "0 -4px 20px rgba(0,0,0,0.1)",
  maxHeight: 340,
  overflow: "auto",
  padding: "16px 24px",
  fontSize: 13,
};

function ProgressBar(props: { done: number; total: number; color: string }) {
  const pct = props.total > 0 ? Math.round((props.done / props.total) * 100) : 0;
  return (
    <div style={{ height: 6, borderRadius: 3, background: "#e8ecef", flex: 1, overflow: "hidden" }}>
      <div style={{ height: "100%", width: `${pct}%`, background: props.color, borderRadius: 3, transition: "width 0.3s" }} />
    </div>
  );
}

function StatusDot(props: { status: string }) {
  const colors: Record<string, string> = {
    done: "#1a7f37",
    running: "#0969da",
    failed: "#cf222e",
    skipped: "#999",
    pending: "#ddd",
  };
  return (
    <span style={{
      display: "inline-block",
      width: 8,
      height: 8,
      borderRadius: "50%",
      background: colors[props.status] || "#ddd",
    }} />
  );
}

export function BulkProgressDrawer(props: {
  status: BulkStatusResponse | null;
  loading: boolean;
  error: string | null;
  onDismiss: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  if (!props.status && !props.loading && !props.error) return null;

  const s = props.status;
  const isRunning = props.loading || s?.status === "running";

  return (
    <div style={drawerStyle}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>
          {isRunning ? "Bulk Profiling in Progress..." : s?.status === "completed" ? "Bulk Profiling Complete" : "Bulk Profiling Complete (with errors)"}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={() => setExpanded(e => !e)} style={{ background: "none", border: "1px solid #dde", borderRadius: 4, padding: "2px 10px", fontSize: 11, cursor: "pointer" }}>
            {expanded ? "Collapse" : "Details"}
          </button>
          {!isRunning && (
            <button onClick={props.onDismiss} style={{ background: "none", border: "1px solid #dde", borderRadius: 4, padding: "2px 10px", fontSize: 11, cursor: "pointer" }}>
              Dismiss
            </button>
          )}
        </div>
      </div>

      {props.error && <div style={{ color: "#cf222e", marginBottom: 8 }}>{props.error}</div>}

      {s && (
        <>
          {/* Progress bars */}
          <div style={{ display: "flex", gap: 24, marginBottom: 12 }}>
            {(s.mode === "technical" || s.mode === "both") && (
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontSize: 11, color: "#666" }}>
                  <span>Technical</span>
                  <span>{s.technical.done} done / {s.technical.failed} failed / {s.technical.skipped} skipped</span>
                </div>
                <ProgressBar done={s.technical.done + s.technical.skipped} total={s.total} color="#0f7b6c" />
              </div>
            )}
            {(s.mode === "semantic" || s.mode === "both") && (
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontSize: 11, color: "#666" }}>
                  <span>Semantic</span>
                  <span>{s.semantic.done} done / {s.semantic.failed} failed / {s.semantic.skipped} skipped</span>
                </div>
                <ProgressBar done={s.semantic.done + s.semantic.skipped} total={s.total} color="#278bac" />
              </div>
            )}
          </div>

          {/* Errors */}
          {s.errors.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#cf222e", marginBottom: 4 }}>Errors ({s.errors.length})</div>
              {s.errors.slice(0, expanded ? undefined : 3).map((e, i) => (
                <div key={i} style={{ fontSize: 12, color: "#cf222e", padding: "2px 0" }}>
                  <strong>{e.table.split(".").pop()}</strong> ({e.phase}): {e.error}
                </div>
              ))}
              {!expanded && s.errors.length > 3 && (
                <div style={{ fontSize: 11, color: "#999" }}>+{s.errors.length - 3} more errors</div>
              )}
            </div>
          )}

          {/* Warnings */}
          {s.warnings.length > 0 && expanded && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#9a6700", marginBottom: 4 }}>Warnings ({s.warnings.length})</div>
              {s.warnings.slice(0, 10).map((w, i) => (
                <div key={i} style={{ fontSize: 12, color: "#9a6700", padding: "2px 0" }}>
                  <strong>{w.table.split(".").pop()}</strong>: {w.message}
                </div>
              ))}
            </div>
          )}

          {/* Per-table details */}
          {expanded && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#666", marginBottom: 6 }}>Per-table status</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr auto auto auto auto", gap: "4px 12px", fontSize: 12 }}>
                <div style={{ fontWeight: 600, color: "#999" }}>Table</div>
                <div style={{ fontWeight: 600, color: "#999" }}>Tech</div>
                <div style={{ fontWeight: 600, color: "#999" }}>Sem</div>
                <div style={{ fontWeight: 600, color: "#999" }}>Tech (s)</div>
                <div style={{ fontWeight: 600, color: "#999" }}>Sem (s)</div>
                {s.tables.map((t) => (
                  <div key={t.fq_table} style={{ display: "contents" }}>
                    <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={t.fq_table}>
                      {t.fq_table.split(".").pop()}
                    </div>
                    <div><StatusDot status={t.technical} /> {t.technical}</div>
                    <div><StatusDot status={t.semantic} /> {t.semantic}</div>
                    <div>{t.tech_duration_s > 0 ? t.tech_duration_s : "—"}</div>
                    <div>{t.sem_duration_s > 0 ? t.sem_duration_s : "—"}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
