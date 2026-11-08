/** Explore left pane: what the active tab reads from, and how to change it. */
import type { Dataset } from "../types";
import { formatTimestamp } from "../format";

const KIND_LABEL: Record<string, string> = {
  aurora: "Aurora", postgres: "PostgreSQL", athena: "Athena", s3: "S3", bq: "BigQuery",
  catalog: "Catalog", sql: "SQL", join: "Join", derived: "Calculated", materialized: "Snapshot",
  group_summary: "Summary", omop_cohort: "OMOP cohort",
};

/** "Extract", "Upload", "Live" (queries the source) or "In memory" (a loaded copy). */
export function sourceMode(dataset: Dataset): string {
  if (dataset.extract) return "Extract";
  if (!dataset.sourceRef) return "Upload";
  return dataset.queryScope === "database" ? "Live" : "In memory";
}

interface Props {
  dataset: Dataset;
  /** Data Builder, with Connections showing this tab's datasource. */
  onChange?: () => void;
  /** Reopens a join, SQL or extract recipe in Data Builder. */
  onEdit?: () => void;
  /** Starts a Data Builder join from this tab. */
  onJoin?: () => void;
  /** Reruns an extract, or queries a live source again. */
  onRefresh?: () => void;
}

export function SourceCard({ dataset, onChange, onEdit, onJoin, onRefresh }: Props) {
  const kind = dataset.sourceRef?.kind;
  const mode = sourceMode(dataset);
  const rows = dataset.result?.total;
  const status = dataset.extractRefreshing ? "Refreshing extract…"
    : dataset.queryError ? "Query failed"
    : dataset.queryLoading || dataset.refreshing ? "Loading…"
    : dataset.extract?.refreshed_at ? `Refreshed ${formatTimestamp(dataset.extract.refreshed_at)}` : "";
  const refreshing = Boolean(dataset.extractRefreshing || dataset.refreshing);
  return (
    <div className="source-card" aria-label="Data source of this tab" role="group">
      <div className="source-card-path" title={dataset.source}>{dataset.source}</div>
      <div className="source-card-chips">
        {kind && <span className="source-chip">{KIND_LABEL[kind] ?? kind}</span>}
        <span className={`source-chip mode${mode === "Extract" ? " extract" : ""}`}>{mode}</span>
      </div>
      <dl className="source-card-facts">
        <div><dt>Rows</dt><dd>{rows != null ? rows.toLocaleString() : "…"}</dd></div>
        {status && <div className="wide"><dt>Status</dt>
          <dd className={dataset.queryError ? "error" : undefined} title={dataset.queryError}>{status}</dd></div>}
      </dl>
      <div className="source-card-actions">
        {onChange && <button type="button" className="link" aria-label="Change data source"
                             title="Open Data Builder to choose another table" onClick={onChange}>Change…</button>}
        {onEdit && <button type="button" className="link" onClick={onEdit} disabled={dataset.extractRefreshing}
                           title="Reopen this recipe in Data Builder">Edit in Data Builder</button>}
        {onJoin && <button type="button" className="link" onClick={onJoin}
                           title="Start a Data Builder join from this tab">⋈ Join…</button>}
        {onRefresh && <button type="button" className="icon-button" aria-label="Refresh source"
                              title={dataset.extract ? "Rerun the extract and replace its rows" : "Query the source again"}
                              disabled={refreshing} onClick={onRefresh}>
          <span aria-hidden className={refreshing ? "spin" : undefined}>↻</span>
        </button>}
      </div>
    </div>
  );
}
