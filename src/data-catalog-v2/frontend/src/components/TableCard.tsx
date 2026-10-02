import { Link } from "react-router-dom";
import type { CatalogTable } from "../types/catalog";
import { Badge, Card } from "./rds";

function profilingBadge(t: CatalogTable) {
  const tech = t.profiling.technical;
  const sem = t.profiling.semantic;
  if (tech === "running" || sem === "running") {
    return <Badge tone="warn">Profiling…</Badge>;
  }
  if (tech === "available" && sem === "available") {
    return <Badge tone="success">Fully profiled</Badge>;
  }
  if (tech === "available") {
    return <Badge tone="info">Technical</Badge>;
  }
  return <Badge tone="neutral">Not profiled</Badge>;
}

export function TableCard(props: { table: CatalogTable }) {
  const t = props.table;
  const to = `/table/${encodeURIComponent(t.project_id)}/${encodeURIComponent(t.dataset_id)}/${encodeURIComponent(t.table_id)}`;
  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <Link to={to} style={{ fontWeight: 700, fontSize: 16 }}>
            {t.table_id}
          </Link>
          <div style={{ color: "var(--wb-muted)", fontSize: 13, marginTop: 4 }}>{t.fq_table}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          {profilingBadge(t)}
          <div style={{ fontSize: 13, marginTop: 8 }}>
            {t.row_count != null ? `${t.row_count.toLocaleString()} rows` : "rows ?"} · {t.column_count} cols
          </div>
        </div>
      </div>
    </Card>
  );
}
