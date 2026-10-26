import { useEffect, useState } from "react";
import { api } from "../api";
import type { Dataset, GrainDefinition, GrainCheck } from "../types";

export function GrainSettings({ dataset, onUpdate }: {dataset: Dataset; onUpdate: (changes: Partial<Dataset>) => void}) {
  const [open, setOpen] = useState(false);
  const [definition, setDefinition] = useState<GrainDefinition>({entity: "person", keys: []});
  const [check, setCheck] = useState<GrainCheck | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!open) return;
    let current = true;
    setBusy(true);
    api.grain(dataset.id).then(info => {
      if (current && info.definition) setDefinition(info.definition);
      if (current && info.missing_columns.length) setStatus("Some saved keys no longer exist. Select new key columns.");
    }).catch(e => { if (current) setStatus(e.message); }).finally(() => {if (current) setBusy(false);});
    return () => {current = false;};
  }, [open, dataset.id]);
  const update = (next: GrainDefinition) => {setDefinition(next); setCheck(null); setStatus("");};
  const save = async (validate: boolean) => {
    setBusy(true); setStatus(""); setCheck(null);
    try {
      const info = await api.saveGrain(dataset.id, definition);
      onUpdate({sourceRef: info.source_ref ?? dataset.sourceRef});
      setStatus(info.persistent ? "Definition saved." : "Definition saved for this open dataset.");
      if (validate) setCheck(await api.checkGrain(dataset.id));
    } catch (e) {setStatus((e as Error).message);}
    finally {setBusy(false);}
  };
  return <div className="column-settings">
    <button className="quiet" onClick={() => setOpen(!open)} aria-expanded={open}>Row grain</button>
    {open && <section className="column-settings-panel" aria-label="Row grain">
      <label>One row represents
        <select value={definition.entity} disabled={busy} onChange={e => update({...definition, entity: e.target.value as GrainDefinition["entity"]})}>
          {["person", "sample", "variant", "event", "summary", "other"].map(value => <option key={value}>{value}</option>)}
        </select>
      </label>
      <fieldset disabled={busy}><legend>Key columns</legend>
        <div style={{display: "flex", flexWrap: "wrap", gap: 12}}>
          {dataset.columns.map(column => <label key={column.name}>
            <input type="checkbox" checked={definition.keys.includes(column.name)} onChange={e => update({...definition,
              keys: e.target.checked ? [...definition.keys, column.name] : definition.keys.filter(k => k !== column.name)})} /> {column.label || column.name}
          </label>)}
        </div>
      </fieldset>
      <div className="join-row">
        <button disabled={busy || !definition.keys.length || definition.keys.length > 8} onClick={() => save(false)}>Save definition</button>
        <button className="primary" disabled={busy || !definition.keys.length || definition.keys.length > 8} onClick={() => save(true)}>Save and check key</button>
      </div>
      {status && <p role="status">{status}</p>}
      {check && <div role="status">
        <strong>{check.status === "unique_non_null" ? "Key is unique and complete" : check.status === "empty" ? "No rows to check" : "Key has duplicates or missing values"}</strong>
        <p>{check.rows.toLocaleString()} rows · {check.distinct_keys.toLocaleString()} distinct keys · {check.null_key_rows.toLocaleString()} missing · {check.duplicate_key_rows.toLocaleString()} duplicate rows</p>
        <p>{check.scope === "database" ? "Full database source" : check.scope === "sample" ? "Loaded sample only" : "Loaded data"} · {new Date(check.checked_at).toLocaleString()}</p>
      </div>}
    </section>}
  </div>;
}
