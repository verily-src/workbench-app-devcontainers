import { useEffect, useState } from "react";
import { api } from "../api";
import type { Dataset, SavedViewEntry, SavedViewStoreError, Source } from "../types";

interface Props {
  sources: Source[];
  datasets: Dataset[];
  active: number;
  onLoadView: (store: { kind: string; id: string }, name: string) => void;
}

export function SavedViews({ sources, datasets, active, onLoadView }: Props) {
  const saveable = datasets.filter((dataset) => dataset.sourceRef);
  const stores = sources.filter((source) => source.kind === "aurora" || source.kind === "s3");
  const defaultStore = stores.find((source) => source.kind === "aurora") ?? stores[0];
  const [views, setViews] = useState<SavedViewEntry[]>([]);
  const [unavailable, setUnavailable] = useState<SavedViewStoreError[]>([]);
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");
  const [loadingError, setLoadingError] = useState("");
  const [saving, setSaving] = useState(false);

  const refresh = async () => {
    try {
      const result = await api.listAllViews();
      setViews(result.views);
      setUnavailable(result.unavailable);
      setLoadingError("");
    } catch (error) {
      setLoadingError(`Saved views could not be loaded: ${(error as Error).message}`);
      setViews([]);
      setUnavailable([]);
    }
  };
  useEffect(() => { void refresh(); }, [sources.map((source) => `${source.kind}:${source.id}`).sort().join("|")]);

  const save = async () => {
    if (!defaultStore || !saveable.length || !name.trim() || saving) return;
    setSaving(true);
    setStatus("Saving…");
    try {
      const index = Math.max(0, saveable.findIndex((dataset) => dataset === datasets[active]));
      await api.saveView(defaultStore.kind, defaultStore.id, name.trim(), saveable, index);
      setName("");
      setStatus(`Saved ${saveable.length} tab(s) to ${defaultStore.label}.`);
      await refresh();
    } catch (error) {
      setStatus(`Save failed: ${(error as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const remove = async (view: SavedViewEntry) => {
    try {
      await api.deleteView(view.kind, view.resource_id, view.name);
      setStatus(`Deleted ${view.name} from ${view.store_label}.`);
      await refresh();
    } catch (error) {
      setStatus(`Delete failed: ${(error as Error).message}`);
    }
  };

  const copyLink = (view: SavedViewEntry) => {
    const link = `${window.location.origin}${window.location.pathname}`
      + `#view=${view.kind}:${encodeURIComponent(view.resource_id)}:${encodeURIComponent(view.name)}`;
    navigator.clipboard?.writeText(link).then(
      () => setStatus("Link copied."), () => setStatus(link));
  };

  const counts = new Map<string, number>();
  for (const view of views) counts.set(view.name, (counts.get(view.name) ?? 0) + 1);
  return <div>
    {defaultStore && saveable.length > 0 && <div className="view-save">
      <input aria-label="Saved view name" type="text"
        placeholder={`name this view (${saveable.length} tab${saveable.length > 1 ? "s" : ""})`}
        value={name} onChange={(event) => setName(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") void save(); }} />
      <button className="primary" onClick={() => void save()}
        disabled={!name.trim() || saving}>{saving ? "Saving…" : "Save"}</button>
      <span className="settings-hint" title="New views use the default store.">{defaultStore.label}</span>
    </div>}
    {!defaultStore && saveable.length > 0 && <div className="settings-hint">
      No Aurora or S3 resource is available to store these views.
    </div>}
    {datasets.length > 0 && saveable.length === 0 && <div className="settings-hint">
      Uploaded files can't be saved — load from a datasource to save a view.
    </div>}
    <div className="view-list">
      {!loadingError && views.length === 0 && unavailable.length === 0
        && <div className="settings-hint">No saved views.</div>}
      {views.map((view) => {
        const sourceId = `view-source-${encodeURIComponent(`${view.kind}:${view.resource_id}:${view.name}`)}`;
        const duplicate = (counts.get(view.name) ?? 0) > 1;
        return <div className="view-row" key={`${view.kind}:${view.resource_id}:${view.name}`}>
          <div>{duplicate && <span id={sourceId} className="settings-hint">{view.store_label} · </span>}
            <button className="view-load" aria-describedby={duplicate ? sourceId : undefined}
              onClick={() => onLoadView({ kind: view.kind, id: view.resource_id }, view.name)}>
              {view.name}
            </button>
            <button className="quiet" title="Copy share link"
              aria-label={`Copy link for ${view.name} from ${view.store_label}`}
              onClick={() => copyLink(view)}>🔗</button>
            <button className="quiet" title="Delete"
              aria-label={`Delete ${view.name} from ${view.store_label}`}
              onClick={() => void remove(view)}>✕</button>
          </div>
        </div>;
      })}
    </div>
    {loadingError && <div className="settings-hint" role="alert">{loadingError}</div>}
    {unavailable.map((item) => <div key={`${item.kind}:${item.resource_id}`}
      className="settings-hint" role="alert">
      Could not load saved views from {item.label}: {item.error}
    </div>)}
    {status && <div className="settings-hint" role={saving ? "status" : undefined}>{status}</div>}
  </div>;
}
