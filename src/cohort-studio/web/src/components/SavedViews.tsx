import { useEffect, useState } from "react";
import { api } from "../api";
import type { Dataset, Source } from "../types";

interface Props {
  sources: Source[];
  datasets: Dataset[];
  active: number;
  onLoadView: (store: { kind: string; id: string }, name: string) => void;
}

// Views persist to Aurora (a _studio_views row) or S3 (a JSON object),
// so filters + charts survive the app closing. Browser state does not.
export function SavedViews({ sources, datasets, active, onLoadView }: Props) {
  // Only datasource-backed tabs can be reloaded (uploads have no source).
  const saveable = datasets.filter((d) => d.sourceRef);
  const stores = sources.filter((s) => s.kind === "aurora" || s.kind === "s3");
  const [store, setStore] = useState("");
  const [views, setViews] = useState<{ name: string }[]>([]);
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");

  const current = stores.find((s) => `${s.kind}:${s.id}` === store);

  useEffect(() => {
    if (!store && stores[0]) setStore(`${stores[0].kind}:${stores[0].id}`);
  }, [stores.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => {
    if (!current) return;
    api.listViews(current.kind, current.id)
      .then(setViews).catch(() => setViews([]));
  };
  useEffect(refresh, [store]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!current || saveable.length === 0 || !name.trim()) return;
    setStatus("Saving…");
    try {
      const activeSaveIdx = Math.max(0, saveable.findIndex(
        (d) => d === datasets[active]));
      await api.saveView(current.kind, current.id, name.trim(),
                         saveable, activeSaveIdx);
      setName("");
      const skipped = datasets.length - saveable.length;
      setStatus(`Saved ${saveable.length} tab(s).`
        + (skipped ? ` ${skipped} upload(s) skipped.` : ""));
      refresh();
    } catch (e) {
      setStatus(`Failed: ${(e as Error).message}`);
    }
  };

  const remove = async (viewName: string) => {
    if (!current) return;
    await api.deleteView(current.kind, current.id, viewName).catch(() => undefined);
    refresh();
  };

  if (stores.length === 0) {
    return <div className="settings-hint" style={{ padding: "4px 0" }}>
      No Aurora or S3 resource to store views in.</div>;
  }

  return (
    <div>
      <select value={store} onChange={(e) => setStore(e.target.value)}>
        {stores.map((s) => (
          <option key={`${s.kind}:${s.id}`} value={`${s.kind}:${s.id}`}>
            {s.id} · {s.kind.toUpperCase()}
          </option>
        ))}
      </select>

      {saveable.length > 0 ? (
        <div className="view-save">
          <input type="text"
                 placeholder={`name this view (${saveable.length} tab${saveable.length > 1 ? "s" : ""})`}
                 value={name}
                 onChange={(e) => setName(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") save(); }} />
          <button className="primary" onClick={save} disabled={!name.trim()}>
            Save
          </button>
        </div>
      ) : datasets.length > 0 ? (
        <div className="settings-hint" style={{ margin: "6px 0" }}>
          Uploaded files can't be saved — load from a datasource to save a view.
        </div>
      ) : null}

      <div className="view-list">
        {views.length === 0 && (
          <div className="settings-hint">No saved views here yet.</div>
        )}
        {views.map((v) => (
          <div key={v.name} className="view-row">
            <button className="view-load"
                    onClick={() => current && onLoadView(
                      { kind: current.kind, id: current.id }, v.name)}>
              {v.name}
            </button>
            <button className="quiet" title="Delete"
                    onClick={() => remove(v.name)}>✕</button>
          </div>
        ))}
      </div>
      {status && <div className="settings-hint">{status}</div>}
    </div>
  );
}
