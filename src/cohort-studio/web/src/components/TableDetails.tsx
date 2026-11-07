import "./TableDetails.css";
import { TableInfo } from "../types";
import { formatBytes, formatTimestamp, rowsLabel } from "../format";

/** Rows, size, columns and statistics date of a listed table or file. */
export function TableDetails({ info }: { info: TableInfo }) {
  const rows = rowsLabel(info);
  const facts: [string, string, string?, boolean?][] = [];
  facts.push(["Type", info.detail]);
  if (rows) facts.push(["Rows", rows.replace(/ rows$/, ""),
    info.rows_estimated ? "Estimated from database statistics; the exact count is computed after loading." : undefined]);
  if (info.bytes != null) facts.push(["Size", formatBytes(info.bytes),
    info.detail === "file" ? "Object size in S3"
      : info.detail.startsWith("Parquet folder") ? "Total size of the Parquet parts in S3"
      : "On disk, including indexes"]);
  if (info.columns != null) facts.push(["Columns", String(info.columns)]);
  if (info.analyzed) facts.push(["Stats as of", formatTimestamp(info.analyzed), undefined, true]);
  if (info.modified) facts.push(["Modified", formatTimestamp(info.modified), undefined, true]);
  return (
    <dl className="table-details" aria-label="Table details">
      {facts.map(([label, value, title, wide]) => (
        <div key={label} title={title} className={wide ? "wide" : undefined}><dt>{label}</dt><dd>{value}</dd></div>
      ))}
    </dl>
  );
}
