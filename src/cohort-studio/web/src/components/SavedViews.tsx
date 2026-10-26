import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type {
  Dataset, SavedViewEntry, SavedViewJob, SavedViewStoreError, Source,
} from "../types";

interface Props {
  sources: Source[];
  datasets: Dataset[];
  active: number;
  onLoadView: (store: { kind: string; id: string }, name: string) => void;
}

export function SavedViews({ sources, datasets, active, onLoadView }: Props) {
  const saveable = datasets.filter((dataset) => dataset.sourceRef);
  const stores = sources.filter((source) => source.kind === "aurora" || source.kind === "s3");
  const defaultStore = stores.find((source) => source.kind === "aurora")
    ?? stores.find((source) => source.kind === "s3");
  const [views, setViews] = useState<SavedViewEntry[]>([]);
  const [unavailable, setUnavailable] = useState<SavedViewStoreError[]>([]);
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const [listError, setListError] = useState("");
  const [task, setTask] = useState<{
    job: SavedViewJob; kind: string; id: string; action: "save" | "refresh";
  } | null>(null);
  const taskRunning = task?.job.status === "queued" || task?.job.status === "running";
  const storeKey = useMemo(() => stores.map((source) =>
    `${source.kind}:${source.id}`).sort().join("|"), [sources]);
  const storeKeyRef = useRef(storeKey);
  storeKeyRef.current = storeKey;

  const refresh = async () => {
    const requested = storeKeyRef.current;
    try {
      const result = await api.listAllViews();
      if (storeKeyRef.current !== requested) return;
      setViews(result.views);
      setUnavailable(result.unavailable);
      setListError("");
    } catch (error) {
      if (storeKeyRef.current !== requested) return;
      setViews([]);
      setUnavailable([]);
      setListError(`Saved views could not be loaded: ${(error as Error).message}`);
    }
  };

  useEffect(() => { void refresh(); }, [storeKey]);

  useEffect(() => {
    if (!task || !taskRunning) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      api.savedViewJob(task.job.job_id).then((job) => {
        if (cancelled) return;
        setTask({ ...task, job });
        if (job.status === "complete") {
          setStatus(job.materialized_sources === 0
            ? `Saved ${job.name} without a snapshot.`
            : `Snapshot ready for ${job.name}.`);
          void refresh();
          onLoadView({ kind: task.kind, id: task.id }, job.name);
        } else if (job.status === "failed") {
          setStatus(`Snapshot failed: ${job.error || "Unknown error"}`);
        }
      }).catch((error) => {
        if (cancelled) return;
        setStatus(`Could not check snapshot status: ${(error as Error).message}`);
        setTask({ ...task });
      });
    }, 1200);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [task]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!defaultStore || saveable.length === 0 || !name.trim()
        || saving || taskRunning) return;
    setSaving(true);
    setStatus("Saving…");
    try {
      const activeSaveIdx = Math.max(0, saveable.findIndex(
        (dataset) => dataset === datasets[active]));
      const result = await api.saveView(defaultStore.kind, defaultStore.id,
        name.trim(), saveable, activeSaveIdx);
      setName("");
      if (result.job_id) {
        const job = { ...result, status: result.status ?? "queued",
          completed_sources: result.completed_sources ?? 0, total_sources: result.total_sources ?? 0 } as SavedViewJob;
        setTask({ job, kind: defaultStore.kind, id: defaultStore.id, action: "save" });
        setStatus(job.status === "complete"
          ? `Snapshot ready for ${result.name}.`
          : job.status === "failed"
            ? `Snapshot failed: ${job.error || "Unknown error"}`
            : `Building snapshot for ${result.name}…`);
        if (job.status === "complete")
          onLoadView({ kind: defaultStore.kind, id: defaultStore.id }, result.name);
      } else {
        const skipped = datasets.length - saveable.length;
        setStatus(`Saved ${saveable.length} tab(s) to ${defaultStore.label}.`
          + (skipped ? ` ${skipped} upload(s) skipped.` : ""));
      }
      void refresh();
    } catch (error) {
      setStatus(`Save failed: ${(error as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const refreshSnapshot = async (view: SavedViewEntry) => {
    if (taskRunning || saving) return;
    setStatus(`Refreshing snapshot for ${view.name}…`);
    try {
      const job = await api.refreshView(view.kind, view.resource_id, view.name);
      setTask({ job, kind: view.kind, id: view.resource_id, action: "refresh" });
      if (job.status === "complete") {
        setStatus(job.materialized_sources === 0
            ? `Saved ${job.name} without a snapshot.`
            : `Snapshot ready for ${job.name}.`);
        void refresh();
        onLoadView({ kind: view.kind, id: view.resource_id }, job.name);
      } else if (job.status === "failed") {
        setStatus(`Snapshot failed: ${job.error || "Unknown error"}`);
      }
    } catch (error) {
      setStatus(`Refresh failed: ${(error as Error).message}`);
    }
  };

  const remove = async (view: SavedViewEntry) => {
    try {
      await api.deleteView(view.kind, view.resource_id, view.name);
      setStatus(`Deleted ${view.name} from ${view.store_label}.`);
      void refresh();
    } catch (error) {
      setStatus(`Delete failed: ${(error as Error).message}`);
    }
  };

  const copyLink = (view: SavedViewEntry) => {
    const url = `${window.location.origin}${window.location.pathname}`
      + `#view=${view.kind}:${encodeURIComponent(view.resource_id)}:${encodeURIComponent(view.name)}`;
    navigator.clipboard?.writeText(url).then(
      () => setStatus("Link copied."),
      () => setStatus(url));
  };

  const counts = new Map<string, number>();
  for (const view of views) counts.set(view.name, (counts.get(view.name) ?? 0) + 1);

  return (
    <div>
      {defaultStore && saveable.length > 0 && (
        <div className="view-save">
          <input type="text"
                 aria-label="Saved view name"
                 placeholder={`name this view (${saveable.length} tab${saveable.length > 1 ? "s" : ""})`}
                 value={name}
                 onChange={(event) => setName(event.target.value)}
                 onKeyDown={(event) => { if (event.key === "Enter") void save(); }} />
          <button className="primary" onClick={() => void save()}
                  disabled={!name.trim() || saving || !!taskRunning}>
            Save
          </button>
          <span className="settings-hint" title="New views use this default store.">
            {defaultStore.label}
          </span>
        </div>
      )}
      {!defaultStore && saveable.length > 0 && (
        <div className="settings-hint" style={{ margin: "6px 0" }}>
          No Aurora or S3 resource is available to store these views.
        </div>
      )}
      {datasets.length > 0 && saveable.length === 0 && (
        <div className="settings-hint" style={{ margin: "6px 0" }}>
          Uploaded files can't be saved — load from a datasource to save a view.
        </div>
      )}

      <div className="view-list">
        {!listError && views.length === 0 && unavailable.length === 0 && (
          <div className="settings-hint">No saved views.</div>
        )}
        {views.map((view) => {
          const taskForView = taskRunning && task?.job.name === view.name
            && task.kind === view.kind && task.id === view.resource_id;
          const updated = view.refreshed_at
            ? new Date(view.refreshed_at).toLocaleString() : "";
          const duplicate = (counts.get(view.name) ?? 0) > 1;
          const sourceLabelId = `saved-view-source-${encodeURIComponent(
            `${view.kind}:${view.resource_id}:${view.name}`)}`;
          return (
            <div key={`${view.kind}:${view.resource_id}:${view.name}`}
                 className="view-row" style={{ display: "block" }}>
              {duplicate && <div id={sourceLabelId} className="settings-hint">
                {view.store_label}
              </div>}
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <button className="view-load"
                        aria-describedby={duplicate ? sourceLabelId : undefined}
                        onClick={() => onLoadView(
                          { kind: view.kind, id: view.resource_id }, view.name)}>
                  {view.name}
                </button>
                {view.materialized_sources > 0 && <button className="quiet"
                        title={`Refresh saved data for ${view.name}`}
                        aria-label={`Refresh saved data for ${view.name} from ${view.store_label}`}
                        disabled={!!taskRunning || saving}
                        onClick={() => void refreshSnapshot(view)}>
                  {taskForView && task?.action === "refresh" ? "Refreshing…" : "Refresh"}
                </button>}
                <button className="quiet" title="Copy share link"
                        aria-label={`Copy link for ${view.name} from ${view.store_label}`}
                        onClick={() => copyLink(view)}>🔗</button>
                <button className="quiet" title="Delete"
                        aria-label={`Delete ${view.name} from ${view.store_label}`}
                        disabled={!!taskForView}
                        onClick={() => void remove(view)}>✕</button>
              </div>
              <div className="settings-hint"
                   title={updated ? `Snapshot created ${updated}; source freshness is unknown.` : "This saved view has no materialized snapshot."}>
                {view.materialized_sources > 0
                  ? `Snapshot · ${view.materialized_sources} source${view.materialized_sources === 1 ? "" : "s"}${updated ? ` · ${updated}` : ""}`
                  : "No snapshot"}
              </div>
              {view.materialized_sources > 0 && view.refresh_mode === "blocking" && (
                <div className="settings-hint" title="Refreshing this snapshot can pause queries that use it.">
                  {taskForView && task?.action === "refresh"
                    ? "Refreshing — queries may wait"
                    : "Refresh can pause queries"}
                </div>
              )}
              {taskForView && <div className="settings-hint" role="status">
                {task!.action === "refresh" ? "Refreshing snapshot" : "Building snapshot"} · {task!.job.completed_sources}/{task!.job.total_sources} sources
              </div>}
            </div>
          );
        })}
      </div>
      {listError && <div className="settings-hint" role="alert">{listError}</div>}
      {unavailable.map((item) => <div key={`${item.kind}:${item.resource_id}:${item.label}`}
        className="settings-hint" role="alert">
        Could not load saved views from {item.label}: {item.error}
      </div>)}
      {status && <div className="settings-hint" role={taskRunning || saving ? "status" : undefined}>{status}</div>}
    </div>
  );
}
