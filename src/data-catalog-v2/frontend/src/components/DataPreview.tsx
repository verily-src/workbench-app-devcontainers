import type { PreviewResult } from "../hooks/usePreview";
import { Card } from "./rds";

export function DataPreview(props: { data: PreviewResult | null; loading: boolean; err: string | null }) {
  if (props.loading) return <p>Loading preview…</p>;
  if (props.err) return <p style={{ color: "var(--wb-danger)" }}>{props.err}</p>;
  if (!props.data) return null;
  const d = props.data;
  return (
    <Card title="Data preview (capped)">
      <p style={{ color: "var(--wb-muted)", fontSize: 14 }}>
        Showing {d.preview_row_count} rows
        {d.total_rows != null ? ` of ${Number(d.total_rows).toLocaleString()} total` : ""}.
      </p>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
          <thead>
            <tr>
              {d.columns.map((c) => (
                <th
                  key={c.name}
                  style={{
                    textAlign: "left",
                    borderBottom: "1px solid var(--wb-border)",
                    padding: 8,
                    whiteSpace: "nowrap",
                  }}
                >
                  {c.name}
                  <div style={{ fontWeight: 400, color: "var(--wb-muted)" }}>{c.type}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {d.rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td key={ci} style={{ borderBottom: "1px solid #eee", padding: 8, maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {cell === null || cell === undefined ? <em>null</em> : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
