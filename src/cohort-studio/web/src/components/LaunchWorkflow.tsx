import { useEffect, useState } from "react";
import { api } from "../api";
import type { Dataset, Source } from "../types";

interface Props {
  dataset: Dataset;
  onClose: () => void;
  onSubmitted: (name: string) => void;
}

// Run a Nextflow/HealthOmics workflow on the current cohort: write the
// filtered rows as an input CSV to a bucket, then submit a job pointing at
// it. Column-mapping / row-selection are workflow-specific, so they're
// free-text passthrough rather than hard-wired.
export function LaunchWorkflow({ dataset, onClose, onSubmitted }: Props) {
  const [s3, setS3] = useState<Source[]>([]);
  const [registry, setRegistry] = useState<
    { id: string; name: string }[]>([]);
  const [workflow, setWorkflow] = useState("");
  const [outputBucket, setOutputBucket] = useState("");
  const [inputBucket, setInputBucket] = useState("");
  const defaultPath =
    `cohort-studio/${dataset.title.replace(/[^A-Za-z0-9_-]+/g, "_")}.csv`;
  const [csvPath, setCsvPath] = useState(defaultPath);
  const [jobName, setJobName] = useState(
    `cohort-studio-${dataset.title.replace(/[^A-Za-z0-9_-]+/g, "_")}`);
  const [columnMapping, setColumnMapping] = useState("");
  const [rowSelection, setRowSelection] = useState("");
  const [exported, setExported] = useState<string>("");
  const [busy, setBusy] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    api.datasources().then((out) => {
      const buckets = out.sources.filter((s) => s.kind === "s3");
      setS3(buckets);
      if (buckets[0]) { setOutputBucket(buckets[0].id); setInputBucket(buckets[0].id); }
    }).catch(() => undefined);
    api.workflowRegistry().then((r) => {
      setRegistry(r.workflows);
      if (r.workflows[0]) setWorkflow(r.workflows[0].id);
    }).catch(() => undefined);
  }, []);

  const writeCsv = async () => {
    setBusy("export"); setStatus("");
    try {
      const out = await api.exportCohort(
        dataset.id, inputBucket, csvPath, dataset.filters);
      setExported(out.s3_uri);
      setStatus(`Wrote ${out.rows.toLocaleString()} rows → ${out.s3_uri}`);
    } catch (e) {
      setStatus(`Export failed: ${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  };

  const submit = async () => {
    setBusy("submit"); setStatus("");
    try {
      const job = await api.submitWorkflow({
        workflow, output_bucket_id: outputBucket, job_id: jobName,
        ...(exported ? {
          batch_input_bucket_id: inputBucket,
          batch_input_csv_path: csvPath,
          column_mapping: columnMapping, row_selection: rowSelection,
        } : {}),
      });
      setStatus(`Submitted "${job.name}" — ${job.status}.`);
      onSubmitted(job.name);
    } catch (e) {
      setStatus(`Submit failed: ${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  };

  const filteredCount = dataset.result?.filtered;

  return (
    <div className="launch-panel">
      <div className="launch-head">
        <strong>Run workflow on cohort</strong>
        <span className="settings-hint">
          {filteredCount != null
            ? `${filteredCount.toLocaleString()} rows in the current cohort`
            : ""}
        </span>
        <div style={{ flex: 1 }} />
        <button className="quiet" onClick={onClose}>✕</button>
      </div>

      <div className="launch-step">
        <div className="field-label">1 · Write cohort as input CSV (optional)</div>
        <div className="launch-row">
          <select value={inputBucket}
                  onChange={(e) => setInputBucket(e.target.value)}>
            {s3.map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
          </select>
          <input type="text" value={csvPath}
                 onChange={(e) => setCsvPath(e.target.value)} />
          <button onClick={writeCsv} disabled={!inputBucket || busy !== ""}>
            {busy === "export" ? "Writing…" : "Write CSV"}
          </button>
        </div>
      </div>

      <div className="launch-step">
        <div className="field-label">2 · Submit the job</div>
        <div className="launch-row">
          <label>Workflow
            <select value={workflow}
                    onChange={(e) => setWorkflow(e.target.value)}>
              {registry.length === 0 && <option value="">(none found)</option>}
              {registry.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>))}
            </select>
          </label>
          <label>Output bucket
            <select value={outputBucket}
                    onChange={(e) => setOutputBucket(e.target.value)}>
              {s3.map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
            </select>
          </label>
          <label>Job name
            <input type="text" value={jobName}
                   onChange={(e) => setJobName(e.target.value)} />
          </label>
        </div>
        {exported && (
          <div className="launch-row">
            <label>Column mapping (key=col, comma-sep)
              <input type="text" value={columnMapping}
                     placeholder="input=sample_id"
                     onChange={(e) => setColumnMapping(e.target.value)} />
            </label>
            <label>Row selection (optional)
              <input type="text" value={rowSelection} placeholder="1:100"
                     onChange={(e) => setRowSelection(e.target.value)} />
            </label>
          </div>
        )}
        <button className="primary" onClick={submit}
                disabled={!workflow || !outputBucket || busy !== ""}>
          {busy === "submit" ? "Submitting…" : "Submit job"}
        </button>
      </div>

      {status && <div className="settings-hint launch-status">{status}</div>}
    </div>
  );
}
