import { useEffect, useState } from "react";
import type { Dataset } from "../types";
import { ColumnSettings } from "./ColumnSettings";
import { GrainSettings } from "./GrainSettings";
import "./DatasetSettings.css";

type Tab = "columns" | "grain";

/** One toolbar entry for dataset administration: column labels/types/filters
 * and the row-grain (what one row represents) definition, in a side drawer. */
export function DatasetSettings({ dataset, onUpdate }: {
  dataset: Dataset; onUpdate: (changes: Partial<Dataset>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("columns");
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  return <>
    <button className="quiet dataset-settings-button" aria-expanded={open}
            onClick={() => setOpen(!open)}>⚙ Dataset settings</button>
    {open && <div className="dataset-settings-backdrop" onClick={() => setOpen(false)}>
      <aside className="dataset-settings-drawer" role="dialog" aria-label="Dataset settings"
             onClick={(event) => event.stopPropagation()}>
        <header>
          <div>
            <div className="dataset-settings-kicker">Dataset settings</div>
            <strong>{dataset.title}</strong>
          </div>
          <button className="quiet" aria-label="Close dataset settings" onClick={() => setOpen(false)}>✕</button>
        </header>
        <nav className="dataset-settings-tabs" role="tablist">
          {([["columns", "Columns"], ["grain", "Row grain"]] as const).map(([id, label]) => (
            <button key={id} role="tab" aria-selected={tab === id}
                    className={tab === id ? "on" : undefined} onClick={() => setTab(id)}>{label}</button>
          ))}
        </nav>
        <p className="dataset-settings-hint">{tab === "columns"
          ? "Labels, types and filter controls for this dataset's columns."
          : "Declare what one row represents and which columns form its key; Studio can check the key for duplicates and gaps."}</p>
        <div key={`${tab}:${dataset.id}`}>
          {tab === "columns"
            ? <ColumnSettings dataset={dataset} onUpdate={onUpdate} embedded />
            : <GrainSettings dataset={dataset} onUpdate={onUpdate} embedded />}
        </div>
      </aside>
    </div>}
  </>;
}
