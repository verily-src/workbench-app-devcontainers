import { useEffect, useState } from "react";
import { api } from "../api";
import type { Dataset, Source } from "../types";

interface Props {
  dataset: Dataset;
  onClose: () => void;
  onSubmitted: (name: string) => void;
}

const GENETICS_WORKFLOW_ID = "cohort-genetics-demo";

interface ExportedCohort {
  s3_uri: string;
  rows: number;
  fingerprint: string;
}

export function LaunchWorkflow({ dataset, onClose, onSubmitted }: Props) {
  const [s3, setS3] = useState<Source[]>([]);
  const [registry, setRegistry] = useState<
    { id: string; name: string }[]>([]);
  const [registryLoading, setRegistryLoading] = useState(true);
  const [registryError, setRegistryError] = useState("");
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
  const [exported, setExported] = useState<ExportedCohort | null>(null);
  const [busy, setBusy] = useState("");
  const [status, setStatus] = useState("");
  const filterKey = JSON.stringify(dataset.filters ?? []);
  const isGeneticsDemo = workflow === GENETICS_WORKFLOW_ID;
  const safeDemoJobId = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(jobName);
  const exportFingerprint = JSON.stringify([
    dataset.id, filterKey, workflow, inputBucket, csvPath,
  ]);
  const exportIsCurrent = exported?.fingerprint === exportFingerprint;

  useEffect(() => {
    api.datasources().then((out) => {
      const buckets = out.sources.filter((s) => s.kind === "s3");
      setS3(buckets);
      if (buckets[0]) { setOutputBucket(buckets[0].id); setInputBucket(buckets[0].id); }
    }).catch(() => undefined);
    api.workflowRegistry().then((r) => {
      setRegistry(r.workflows);
      if (!r.available) setRegistryError("Workflow registry is unavailable.");
      if (r.workflows[0]) setWorkflow(r.workflows[0].id);
    }).catch(() => setRegistryError("Could not load workflows."))
      .finally(() => setRegistryLoading(false));
  }, []);

  useEffect(() => {
    setExported(null);
    setStatus("");
  }, [dataset.id, filterKey]);

  const writeCsv = async () => {
    setBusy("export"); setStatus("");
    try {
      const out = await api.exportCohort(
        dataset.id, inputBucket, csvPath, dataset.filters,
        isGeneticsDemo ? GENETICS_WORKFLOW_ID : undefined);
      setExported({ s3_uri: out.s3_uri, rows: out.rows,
                    fingerprint: exportFingerprint });
      setStatus(`Wrote ${out.rows.toLocaleString()} rows → ${out.s3_uri}`);
    } catch (e) {
      setStatus(`Export failed: ${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  };

  const submit = async () => {
    if (isGeneticsDemo && !exportIsCurrent) {
      setStatus("Write a fresh cohort CSV before submitting this workflow.");
      return;
    }
    setBusy("submit"); setStatus("");
    try {
      const runToken = crypto.randomUUID();
      const job = await api.submitWorkflow({
        workflow, output_bucket_id: outputBucket, job_id: jobName,
        ...(isGeneticsDemo && exported ? {
          params_file_bucket_id: inputBucket,
          params_file_path: `cohort-studio/params/${runToken}.json`,
          demo_input_resource_id: inputBucket,
          demo_input_csv_path: csvPath,
          demo_output_path: `cohort-studio/genetics-demo/${runToken}`,
        } : exportIsCurrent ? {
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

      <div className="launch-step launch-workflow-picker">
          <label>Workflow
            <select aria-label="Workflow" value={workflow} disabled={registryLoading || !!registryError}
                    onChange={(e) => { setWorkflow(e.target.value); setExported(null); setStatus(""); }}>
              {registry.length === 0 && <option value="">{registryLoading ? "Loading workflows…" : "No registered workflows"}</option>}
              {registry.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>))}
            </select>
          </label>
        {registryError && <p role="alert">{registryError}</p>}
      </div>

      <div className="launch-step">
        <div className="field-label">Input CSV (S3)</div>
        <div className="launch-row">
          <select aria-label="Input S3 folder" value={inputBucket}
                  onChange={(e) => { setInputBucket(e.target.value); setExported(null); setStatus(""); }}>
            {s3.map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
          </select>
          <input aria-label="Input CSV path" type="text" value={csvPath}
                 onChange={(e) => { setCsvPath(e.target.value); setExported(null); setStatus(""); }} />
          <button onClick={writeCsv} disabled={!inputBucket || busy !== ""}>
            {busy === "export" ? "Writing…" : "Write CSV"}
          </button>
        </div>
        {isGeneticsDemo && <p className="settings-hint">
          Exports the current cohort as person_id, sample_id, variant_id, dosage,
          gender_concept_id, and year_of_birth for SYN_VAR_0021.
        </p>}
      </div>

      <div className="launch-step">
        <div className="field-label">Run settings</div>
        <div className="launch-row">
          <label>Output S3 folder
            <select aria-label="Output S3 folder" value={outputBucket}
                    onChange={(e) => { setOutputBucket(e.target.value); setExported(null); setStatus(""); }}>
              {s3.map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
            </select>
          </label>
          <label>Job name
            <input type="text" value={jobName} maxLength={128}
                   aria-invalid={isGeneticsDemo && !safeDemoJobId}
                   onChange={(e) => setJobName(e.target.value)} />
          </label>
        </div>
        {isGeneticsDemo && !safeDemoJobId && (
          <p className="settings-hint" role="alert">
            Use 1–128 letters, numbers, dots, underscores, or hyphens; start with a letter or number.
          </p>
        )}
        {exportIsCurrent && !isGeneticsDemo && (
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
                disabled={!workflow || !outputBucket || busy !== ""
                  || (isGeneticsDemo && (!exportIsCurrent || !safeDemoJobId))}>
          {busy === "submit" ? "Submitting…" : "Submit job"}
        </button>
      </div>

      {status && <div className="settings-hint launch-status">{status}</div>}
    </div>
  );
}
