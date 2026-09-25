import { useState } from "react";
import type { TechColumn, TechProfile } from "../types/profile";
import { Badge, Card, Stack } from "./rds";

function formatBytes(b: number | null | undefined) {
  if (b == null) return "—";
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`;
  return `${(b / 1024 ** 3).toFixed(2)} GB`;
}

function formatNum(n: number | null | undefined) {
  if (n == null) return "—";
  return typeof n === "number" && !Number.isInteger(n) ? n.toFixed(3) : n.toLocaleString();
}

const th: React.CSSProperties = {
  textAlign: "left",
  padding: "8px 10px",
  borderBottom: "2px solid var(--wb-border)",
  fontSize: 12,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.03em",
  color: "var(--wb-muted)",
  whiteSpace: "nowrap",
};

const td: React.CSSProperties = {
  padding: "8px 10px",
  borderBottom: "1px solid var(--wb-border)",
  verticalAlign: "top",
  fontSize: 13,
};

function StatPair(props: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", gap: 8, fontSize: 14 }}>
      <span style={{ color: "var(--wb-muted)", minWidth: 100 }}>{props.label}</span>
      <span style={{ fontWeight: 500 }}>{props.value}</span>
    </div>
  );
}

function ColumnDetail(props: { col: TechColumn }) {
  const c = props.col;
  const [showVc, setShowVc] = useState(false);
  const hasStr = c.string_stats && (c.string_stats.min_length != null || c.string_stats.max_length != null);
  const hasNum = c.numeric_stats && (c.numeric_stats.min != null || c.numeric_stats.max != null);
  const hasVc = c.value_counts && Object.keys(c.value_counts).length > 0;

  if (!hasStr && !hasNum && !hasVc) return null;

  return (
    <div style={{ padding: "6px 0 2px 16px", fontSize: 12, color: "var(--wb-muted)" }}>
      {hasStr ? (
        <span>
          len: {formatNum(c.string_stats!.min_length)}–{formatNum(c.string_stats!.max_length)} (avg {formatNum(c.string_stats!.avg_length)})
        </span>
      ) : null}
      {hasNum ? (
        <span>
          range: {formatNum(c.numeric_stats!.min)} – {formatNum(c.numeric_stats!.max)}
          {c.numeric_stats!.median != null ? ` · median ${formatNum(c.numeric_stats!.median)}` : ""}
          {c.numeric_stats!.stddev != null ? ` · σ ${formatNum(c.numeric_stats!.stddev)}` : ""}
        </span>
      ) : null}
      {hasVc ? (
        <>
          <button
            type="button"
            onClick={() => setShowVc(!showVc)}
            style={{
              background: "none",
              border: "none",
              color: "var(--wb-primary)",
              cursor: "pointer",
              fontSize: 12,
              padding: 0,
              marginLeft: hasStr || hasNum ? 8 : 0,
            }}
          >
            {showVc ? "hide counts ▴" : "value counts ▾"}
          </button>
          {showVc ? (
            <div style={{ marginTop: 4, display: "flex", flexWrap: "wrap", gap: "2px 12px" }}>
              {Object.entries(c.value_counts!).map(([k, v]) => (
                <span key={k}>
                  <strong>{k}</strong>: {v.toLocaleString()}
                </span>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

export function TechProfileView(props: { data: TechProfile | null; loading?: boolean }) {
  if (props.loading) return <p>Loading technical profile…</p>;
  if (!props.data) return <p style={{ color: "var(--wb-muted)" }}>No technical profile yet.</p>;

  const d = props.data;
  const v = d.validation;

  return (
    <Stack gap={16}>
      {/* Table-level stats */}
      <Card title="Technical profile">
        <div style={{ display: "flex", flexWrap: "wrap", gap: "12px 40px", marginBottom: 16 }}>
          <StatPair label="Table" value={d.table} />
          <StatPair label="Rows" value={d.row_count != null ? d.row_count.toLocaleString() : "—"} />
          <StatPair label="Size" value={formatBytes(d.size_bytes)} />
          <StatPair label="Profiled at" value={d.profiled_at ? new Date(d.profiled_at).toLocaleString() : "—"} />
          <StatPair label="Columns" value={d.columns.length} />
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <Badge tone={v.status === "pass" ? "success" : "warn"}>Validation: {v.status}</Badge>
        </div>

        {(v.anomalies?.length ?? 0) > 0 ? (
          <div style={{ color: "var(--wb-danger)", fontSize: 14, marginTop: 10 }}>
            <strong>Anomalies:</strong> {v.anomalies?.join("; ")}
          </div>
        ) : null}
        {(v.warnings?.length ?? 0) > 0 ? (
          <div style={{ color: "var(--wb-warning)", fontSize: 14, marginTop: 6 }}>
            <strong>Warnings:</strong> {v.warnings?.join("; ")}
          </div>
        ) : null}
      </Card>

      {/* Column-level detail table */}
      <Card title="Column details">
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr>
                {["Column", "Type", "Nullable", "Null count", "Null %", "Distinct", "Top values", "Stats", "Pattern", "Anomalies"].map((h) => (
                  <th key={h} style={th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.columns.map((c) => (
                <tr key={c.name}>
                  <td style={{ ...td, fontWeight: 600 }}>{c.name}</td>
                  <td style={td}>
                    <Badge tone="neutral">{c.data_type}</Badge>
                  </td>
                  <td style={td}>{c.nullable == null ? "—" : c.nullable ? "yes" : "no"}</td>
                  <td style={td}>{c.null_count != null ? c.null_count.toLocaleString() : "—"}</td>
                  <td style={td}>{c.null_percent != null ? `${c.null_percent}%` : "—"}</td>
                  <td style={td}>{c.distinct_count != null ? c.distinct_count.toLocaleString() : "—"}</td>
                  <td style={{ ...td, maxWidth: 220, fontSize: 12 }}>
                    {(c.top_values || []).slice(0, 8).join(", ")}
                    <ColumnDetail col={c} />
                  </td>
                  <td style={{ ...td, fontSize: 12, whiteSpace: "nowrap" }}>
                    {c.string_stats
                      ? `len ${formatNum(c.string_stats.min_length)}–${formatNum(c.string_stats.max_length)}`
                      : c.numeric_stats
                        ? `${formatNum(c.numeric_stats.min)} – ${formatNum(c.numeric_stats.max)}`
                        : "—"}
                  </td>
                  <td style={td}>
                    {c.pattern ? <Badge tone="info">{c.pattern}</Badge> : "—"}
                  </td>
                  <td style={td}>
                    {(c.anomalies || []).length > 0
                      ? c.anomalies!.map((a) => (
                          <Badge key={a} tone="danger">{a}</Badge>
                        ))
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </Stack>
  );
}
