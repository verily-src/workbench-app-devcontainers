import { useEffect, useState } from "react";
import { api } from "../api";
import type { Dataset } from "../types";

/** Saves the people matching the current filters into an existing OMOP cohort table (insert only). */
export function SaveCohort({ dataset }: { dataset: Dataset }) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [name, setName] = useState("");
  const [cohortId, setCohortId] = useState("1");
  const [targets, setTargets] = useState<{ schema: string; table: string; can_insert: boolean }[]>([]);
  const [targetKey, setTargetKey] = useState("");
  const [targetsError, setTargetsError] = useState("");
  const [needed, setNeeded] = useState<string[]>([]);
  const [dateColumn, setDateColumn] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  const entity = dataset.entityColumn;
  const people = dataset.result?.entity?.filtered;
  const dateColumns = dataset.columns.filter((c) => c.filter_kind === "date");
  const id = Number(cohortId);
  const target = targets.find((t) => `${t.schema}.${t.table}` === targetKey);
  const schema = target?.schema ?? "";
  const table = target?.table ?? "";
  const valid = Boolean(entity) && name.trim().length > 0 && Number.isInteger(id) && id >= 1
    && Boolean(target?.can_insert);

  useEffect(() => {
    if (!open) return;
    setTargetsError("");
    api.cohortTargets(dataset.id).then((out) => {
      setTargets(out.targets);
      setNeeded(out.columns);
      // Keep a choice that is still offered; otherwise pick the first writable table.
      setTargetKey((current) => out.targets.some((t) => `${t.schema}.${t.table}` === current) ? current
        : (out.targets.find((t) => t.can_insert) ? `${out.targets.find((t) => t.can_insert)!.schema}.${out.targets.find((t) => t.can_insert)!.table}` : ""));
    }).catch((e) => setTargetsError((e as Error).message));
  }, [open, dataset.id]);

  const save = async () => {
    if (!entity) return;
    setBusy(true);
    setStatus("");
    try {
      const out = await api.saveCohort(dataset.id, {
        filters: dataset.filters, entity_column: entity, target_schema: schema,
        target_table: table, cohort_definition_id: id, cohort_name: name.trim(),
        date_column: dateColumn || null,
      });
      setStatus(`Saved ${out.saved.toLocaleString()} people to ${out.schema}.${out.table} as cohort ${out.cohort_definition_id}.`);
      setConfirming(false);
    } catch (e) {
      setStatus(`Failed: ${(e as Error).message}`);
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  };

  if (!open) return <button onClick={() => setOpen(true)}>Save cohort…</button>;

  return (
    <div className="save-aurora" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {!entity && <span className="settings-hint">Set "Count unique" to the person column first.</span>}
      <input type="text" placeholder="Cohort name" value={name} maxLength={256}
             onChange={(e) => { setName(e.target.value); setConfirming(false); }} />
      <label className="settings-hint">Cohort id
        <input type="number" min={1} value={cohortId}
               onChange={(e) => { setCohortId(e.target.value); setConfirming(false); }} />
      </label>
      <label className="settings-hint">Save to table
        <select aria-label="Destination table" value={targetKey}
                onChange={(e) => { setTargetKey(e.target.value); setConfirming(false); }}>
          {targets.length === 0 && <option value="">No cohort table found</option>}
          {targets.map((t) => (
            <option key={`${t.schema}.${t.table}`} value={`${t.schema}.${t.table}`} disabled={!t.can_insert}>
              {t.schema}.{t.table}{t.can_insert ? "" : " (no write access)"}
            </option>
          ))}
        </select>
      </label>
      {targetsError && <span className="settings-hint">Could not list tables: {targetsError}</span>}
      {!targetsError && targets.length === 0 && (
        <span className="settings-hint">
          The database has no table with the columns {needed.join(", ") || "of a cohort table"}. The
          app doesn't create tables; ask the data owner to create one outside the OMOP schema.
        </span>
      )}
      <label className="settings-hint">Dates from
        <select value={dateColumn} onChange={(e) => setDateColumn(e.target.value)}>
          <option value="">None (leave dates empty)</option>
          {dateColumns.map((c) => <option key={c.name} value={c.name}>{c.label || c.name}</option>)}
        </select>
      </label>
      {!confirming ? (
        <button className="primary" disabled={!valid || busy} onClick={() => setConfirming(true)}>
          Save {people != null ? `${people.toLocaleString()} people` : "cohort"}
        </button>
      ) : (
        <div role="group" aria-label="Confirm save">
          <span className="settings-hint">
            Insert {people != null ? `${people.toLocaleString()} people` : "the matching people"} into{" "}
            {schema}.{table} as cohort {id}? This adds rows to the database.
          </span>
          <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
            <button className="primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Confirm"}</button>
            <button className="quiet" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
          </div>
        </div>
      )}
      <button className="quiet" onClick={() => setOpen(false)}>Close</button>
      {status && <span className="ask-note">{status}</span>}
    </div>
  );
}
