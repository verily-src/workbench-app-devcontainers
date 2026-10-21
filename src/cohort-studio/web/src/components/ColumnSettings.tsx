import { useEffect, useState } from "react";
import { api } from "../api";
import type { ColumnProfile, ColumnSetting, Dataset } from "../types";

interface Props {
  dataset: Dataset;
  onUpdate: (changes: Partial<Dataset>) => void;
}

function settingOf(column: ColumnProfile): ColumnSetting {
  return {
    name: column.name,
    logical_type: column.logical_type ?? null,
    label: column.label ?? "",
    filter_kind: column.filter_kind,
  };
}

export function ColumnSettings({ dataset, onUpdate }: Props) {
  const [open, setOpen] = useState(false);
  const [columns, setColumns] = useState<ColumnSetting[]>([]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) setColumns(dataset.columns.map(settingOf));
  }, [open, dataset.columns]);

  const change = (index: number, patch: Partial<ColumnSetting>) =>
    setColumns((prev) => prev.map((column, i) =>
      i === index ? { ...column, ...patch } : column));

  const save = async () => {
    setBusy(true);
    setStatus("Saving…");
    try {
      const out = await api.updateColumns(dataset.id, columns.map((column) => ({
        ...column, label: column.label?.trim() ?? "",
      })));
      onUpdate({ columns: out.columns,
        sourceRef: out.source_ref ?? dataset.sourceRef,
        queryScope: out.query_scope ?? dataset.queryScope });
      setStatus("Column settings saved.");
    } catch (e) {
      setStatus(`Could not save: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="column-settings">
      <button className="quiet" onClick={() => setOpen((value) => !value)}>
        {open ? "Hide columns" : "Column settings"}
      </button>
      {open && <div className="column-settings-panel">
        <div className="section-label">Column settings</div>
        {columns.map((column, i) => (
          <div className="column-setting-row" key={column.name}>
            <strong>{column.name}</strong>
            <label>Type
              <select value={column.logical_type ?? ""}
                      onChange={(e) => {
                        const logicalType = e.target.value || null;
                        change(i, {
                          logical_type: logicalType as ColumnSetting["logical_type"],
                          ...(logicalType === "text" && column.filter_kind === "range"
                            ? { filter_kind: "none" as const } : {}),
                        });
                      }}>
                <option value="">Keep current</option>
                <option value="number">Number</option>
                <option value="text">Text</option>
              </select>
            </label>
            <label>Filter
              <select value={column.filter_kind ?? ""}
                      onChange={(e) => change(i, {
                        filter_kind: (e.target.value || null) as ColumnSetting["filter_kind"],
                      })}>
                <option value="">Keep current</option>
                <option value="categorical">Categories</option>
                <option value="range">Range</option>
                <option value="none">No filter</option>
              </select>
            </label>
            <label>Label
              <input value={column.label ?? ""}
                     onChange={(e) => change(i, { label: e.target.value })} />
            </label>
          </div>
        ))}
        <div className="join-row">
          <button className="primary" disabled={busy} onClick={save}>
            {busy ? "Saving…" : "Save column settings"}
          </button>
          {status && <span className="settings-hint">{status}</span>}
        </div>
      </div>}
    </div>
  );
}
