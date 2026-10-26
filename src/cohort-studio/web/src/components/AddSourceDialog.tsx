import { useState } from "react";
import { api, CreateSourceRequest } from "../api";

type Kind = CreateSourceRequest["kind"];

interface Props {
  onClose: () => void;
  onAdded: (source: { kind: string; id: string }) => void;
}

export function AddSourceDialog({ onClose, onAdded }: Props) {
  const [kind, setKind] = useState<Kind>("postgres");
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key: string, value: string) =>
    setValues((previous) => ({ ...previous, [key]: value }));
  const value = (key: string) => values[key] ?? "";

  const submit = async () => {
    setBusy(true);
    setError("");
    const common = { kind, id: value("id").trim(), label: value("label").trim() };
    let body: CreateSourceRequest;
    if (kind === "postgres") {
      body = { ...common, kind, secret_id: value("secret_id").trim(),
        region: value("region").trim() };
    } else if (kind === "s3") {
      body = { ...common, kind, bucket: value("bucket").trim(),
        prefix: value("prefix").trim(), region: value("region").trim() };
    } else {
      body = { ...common, kind, region: value("region").trim(),
        workgroup: value("workgroup").trim(),
        output_location: value("output_location").trim(),
        databases: value("databases").split(",").map((part) => part.trim()).filter(Boolean),
        catalog: "AwsDataCatalog" };
    }
    try {
      const created = await api.createSource(body);
      onAdded({ kind: created.kind, id: created.id });
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const input = (key: string, label: string, placeholder = "", required = true) => (
    <label className="field-label" key={key} style={{ display: "grid", gap: 4, flex: 1, minWidth: 0 }}>{label}
      <input type="text" aria-label={label} value={value(key)} placeholder={placeholder}
             required={required} onChange={(event) => set(key, event.target.value)} />
    </label>
  );
  const required = kind === "postgres"
    ? ["id", "label", "secret_id", "region"]
    : kind === "s3" ? ["id", "label", "bucket", "region"]
      : ["id", "label", "region", "workgroup", "output_location", "databases"];
  const ready = !busy && required.every((key) => value(key).trim());

  return (
    <div className="modal-backdrop" role="presentation" style={{
      position: "fixed", inset: 0, zIndex: 1000, display: "grid",
      placeItems: "center", padding: 20, background: "rgba(10, 20, 30, .5)",
    }} onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="settings-card" role="dialog" aria-modal="true"
               aria-labelledby="add-source-title" style={{ width: "min(560px, 92vw)",
                 maxHeight: "90vh", overflowY: "auto" }}>
        <h2 id="add-source-title">Add data source</h2>
        <label className="field-label" style={{ display: "grid", gap: 4 }}>Source type
          <select aria-label="Source type" value={kind}
                  onChange={(event) => { setKind(event.target.value as Kind); setError(""); }}>
            <option value="postgres">PostgreSQL / RDS</option>
            <option value="s3">S3 / Parquet</option>
            <option value="athena">Athena / Iceberg</option>
          </select>
        </label>
        <div className="join-row">
          {input("id", "Source ID", "clinical-rds")}
          {input("label", "Display name", "Clinical RDS")}
        </div>
        {kind === "postgres" && <>
          {input("secret_id", "AWS Secrets Manager connection secret ID", "research/postgres")}
          {input("region", "AWS region", "us-east-1")}
          <p className="settings-caption">The secret must contain the PostgreSQL connection details. Credentials stay in Secrets Manager.</p>
        </>}
        {kind === "s3" && <>
          <div className="join-row">
            {input("bucket", "S3 bucket", "research-data")}
            {input("prefix", "Prefix (optional)", "exports/", false)}
          </div>
          {input("region", "AWS region", "us-east-1")}
          <p className="settings-caption">Uses the app's AWS identity. No access keys are entered here.</p>
        </>}
        {kind === "athena" && <>
          <div className="join-row">
            {input("region", "AWS region", "us-east-1")}
            {input("workgroup", "Workgroup", "primary")}
          </div>
          {input("output_location", "Query output S3 URI", "s3://query-results-bucket/path/")}
          {input("databases", "Databases (comma separated)", "clinical,genetics")}
          <p className="settings-caption">Uses the app's AWS identity and AWS Glue Data Catalog.</p>
        </>}
        {error && <div className="join-error" role="alert">Could not add source: {error}</div>}
        <div className="join-row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
          <button className="quiet" disabled={busy} onClick={onClose}>Cancel</button>
          <button className="primary" disabled={!ready} onClick={submit}>
            {busy ? "Testing connection…" : "Test and add source"}
          </button>
        </div>
      </section>
    </div>
  );
}
