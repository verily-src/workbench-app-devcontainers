import "./SourcePicker.css";
import { useEffect, useMemo, useState } from "react";
import { Source, TableInfo } from "../types";
import { formatBytes, formatTimestamp, rowsLabel, tableStats } from "../format";

type SourceKind = Source["kind"] | "postgres" | "athena";

interface Props {
  sources: Source[];
  tables: TableInfo[];
  sourceKey: string;
  table: string;
  loading?: boolean;
  busy?: boolean;
  /** Label of the datasource whose tables are being listed. */
  listing?: string;
  onSourceKeyChange: (value: string) => void;
  onTableChange: (value: string) => void;
  onLoadTable: () => void;
}

const SOURCE_TYPES: { kind: SourceKind; label: string }[] = [
  { kind: "aurora", label: "▤ Aurora" },
  { kind: "postgres", label: "▤ PostgreSQL" },
  { kind: "s3", label: "🪣 S3" },
  { kind: "bq", label: "☁ Google BigQuery" },
  { kind: "athena", label: "▤ Athena" },
  { kind: "catalog", label: "▦ Catalog" },
];

const SCHEMA_KINDS = new Set<string>(["aurora", "postgres", "athena"]);

function TableDetails({ info }: { info: TableInfo }) {
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

export function SourcePicker({ sources, tables, sourceKey, table, loading = false,
  busy = false, listing = "", onSourceKeyChange, onTableChange, onLoadTable }: Props) {
  const selectedSource = sources.find((source) =>
    `${source.kind}:${source.id}` === sourceKey);
  const [sourceKind, setSourceKind] = useState<SourceKind | "">(
    selectedSource?.kind ?? "");
  const [schema, setSchema] = useState("");
  const [fileFolder, setFileFolder] = useState("");

  useEffect(() => {
    if (selectedSource) setSourceKind(selectedSource.kind);
  }, [selectedSource?.kind, sourceKey]);

  useEffect(() => {
    setSchema("");
    setFileFolder("");
  }, [sourceKind, sourceKey]);

  const availableTypes = useMemo(() => {
    const kinds = new Set<SourceKind>(sources.map((source) => source.kind));
    return SOURCE_TYPES.filter((item) => kinds.has(item.kind));
  }, [sources]);

  const typeSources = sources.filter((source) => source.kind === sourceKind);
  const showSchema = Boolean(selectedSource && SCHEMA_KINDS.has(selectedSource.kind));
  const schemas = [...new Set(tables.flatMap((item) =>
    item.schema ? [item.schema] : []))].sort((a, b) => a.localeCompare(b));
  useEffect(() => {
    if (showSchema && schemas.length === 1 && schema !== schemas[0]) {
      setSchema(schemas[0]);
    }
  }, [schema, schemas, showSchema]);

  const fileFolders = selectedSource?.kind === "s3"
    ? [...new Set(tables.flatMap((item) => {
        const parts = item.name.split("/").slice(0, -1);
        return parts.map((_, index) => parts.slice(0, index + 1).join("/"));
      }))].sort((a, b) => a.localeCompare(b))
    : [];
  const visibleTables = showSchema && schema
    ? tables.filter((item) => item.schema === schema)
    : selectedSource?.kind === "s3" && fileFolder
      ? tables.filter((item) => item.name.startsWith(`${fileFolder}/`))
      : tables;
  const needsSchema = showSchema && schemas.length > 1 && !schema;
  const selectedTable = table ? tables.find((item) => item.name === table) : undefined;

  const changeType = (kind: SourceKind | "") => {
    setSourceKind(kind);
    setSchema("");
    onSourceKeyChange("");
    onTableChange("");
  };

  const changeSource = (key: string) => {
    setSchema("");
    onSourceKeyChange(key);
    onTableChange("");
  };

  return (
    <div className="source-picker">
      <div className="field-label">Source type</div>
      <select aria-label="Source type" value={sourceKind}
              onChange={(event) => changeType(event.target.value as SourceKind | "")}>
        <option value="">Choose a type…</option>
        {availableTypes.map((item) => (
          <option key={item.kind} value={item.kind}>{item.label}</option>
        ))}
      </select>

      <div className="field-label">Datasource</div>
      <select aria-label="Datasource" value={selectedSource ? sourceKey : ""}
              disabled={!sourceKind || typeSources.length === 0}
              onChange={(event) => changeSource(event.target.value)}>
        <option value="">Choose a datasource…</option>
        {typeSources.map((source) => (
          <option key={`${source.kind}:${source.id}`}
                  value={`${source.kind}:${source.id}`}>{source.label || source.id}</option>
        ))}
      </select>
      {listing && <div className="picker-status" role="status">
        <span className="spinner small" aria-hidden="true" />Listing tables in {listing}…
      </div>}

      {showSchema && schemas.length > 0 && !loading && (
        <>
          <div className="field-label">Schema</div>
          <select aria-label="Schema" value={schema}
                  onChange={(event) => {
                    setSchema(event.target.value);
                    onTableChange("");
                  }}>
            <option value="">Choose schema…</option>
            {schemas.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </>
      )}

      {selectedSource && (
        <>
          {selectedSource.kind === "s3" && fileFolders.length > 0 && (
            <>
              <div className="field-label">File folder</div>
              <select aria-label="File folder" value={fileFolder}
                      onChange={(event) => {
                        setFileFolder(event.target.value);
                        onTableChange("");
                      }}>
                <option value="">All folders</option>
                {fileFolders.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </>
          )}
          <div className="field-label">{selectedSource.kind === "s3" ? "File" : "Table"}</div>
          <select aria-label="Table" value={table}
                  disabled={loading || needsSchema}
                  onChange={(event) => onTableChange(event.target.value)}>
            <option value="">{listing ? "Listing tables…" : "Choose…"}</option>
            {visibleTables.map((item) => (
              <option key={item.name} value={item.name} title={item.sql ?? undefined}>
                {selectedSource.kind === "s3" && fileFolder
                  ? item.name.slice(fileFolder.length + 1) || `All parts in ${item.name}`
                  : showSchema && !schema && schemas.length > 1
                    ? item.name : item.table ?? item.name} ({[item.detail, tableStats(item)].filter(Boolean).join(" · ")})
              </option>
            ))}
          </select>
          {selectedTable && <TableDetails info={selectedTable} />}
          <div style={{ marginTop: 10 }}>
            <button className="primary" onClick={onLoadTable}
                    disabled={!table || loading || busy || needsSchema}>
              {selectedSource.kind === "s3" ? "Load file" : "Load table"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
