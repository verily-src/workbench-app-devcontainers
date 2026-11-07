import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type {
  Dataset, Filter, SavedViewEntry, SavedViewJob, SavedViewStoreError, Source, ViewRevision,
} from "../types";

type Store = { kind: string; id: string };

type TaskTarget = { kind: string; id: string; action: "save" | "refresh" };
/** Save/refresh snapshot job as seen by this browser. */
type SnapshotTask =
  | { state: "idle" }
  | (TaskTarget & { state: "polling"; job: SavedViewJob; attempt: number })
  | (TaskTarget & { state: "done"; job: SavedViewJob })
  | (TaskTarget & { state: "failed"; error: string });

const POLL_MS = 1200;
const MAX_POLL_BACKOFF_MS = 10_000;
const MAX_POLL_RETRIES = 8;
export const EXPIRED_SAVE_JOB = "This save job expired (the app restarted). Reload the view.";

function taskFor(job: SavedViewJob, target: TaskTarget): SnapshotTask {
  if (job.status === "complete") return { ...target, state: "done", job };
  if (job.status === "failed")
    return { ...target, state: "failed", error: job.error || "Unknown error" };
  return { ...target, state: "polling", job, attempt: 0 };
}

interface Props {
  sources: Source[];
  datasets: Dataset[];
  active: number;
  onLoadView: (store: Store, name: string) => void;
  /** Opens a published revision read-only; without `revision`, the latest. */
  onOpenRevision: (store: Store, name: string, revision?: number) => void;
  /** Viewer mode: no saving, publishing, rollback or delete. */
  readOnly?: boolean;
  /** Dashboard filters, saved with the view. */
  dashboardFilters?: Filter[];
}

/** Share link for a saved view; `published` links always open the latest revision. */
export function viewLink(view: { kind: string; resource_id: string; name: string },
                         target: "draft" | "published" | number = "draft") {
  return `${window.location.origin}${window.location.pathname}`
    + `#view=${view.kind}:${encodeURIComponent(view.resource_id)}:${encodeURIComponent(view.name)}`
    + (target === "published" ? "&published" : typeof target === "number" ? `&rev=${target}` : "");
}

/** Parses `#view=kind:resource:name` with optional `&published` or `&rev=N`. */
export function parseViewHash(hash: string): {
  store: Store; name: string; published: boolean; revision?: number;
} | null {
  const [head, ...flags] = hash.replace(/^#/, "").split("&");
  const m = head.match(/^view=([^:]+):([^:]+):(.+)$/);
  if (!m) return null;
  const rev = flags.find((flag) => /^rev=\d{1,6}$/.test(flag));
  const revision = rev ? Number(rev.slice(4)) : undefined;
  return {
    store: { kind: m[1], id: decodeURIComponent(m[2]) }, name: decodeURIComponent(m[3]),
    published: flags.includes("published") || Boolean(revision && revision > 0),
    revision: revision && revision > 0 ? revision : undefined,
  };
}

export function publicationLabel(view: SavedViewEntry) {
  if (view.publication_unknown) return "Publish status unavailable";
  if (!view.published_revision) return "Draft · not published";
  return `Published rev ${view.published_revision}`
    + (view.draft_changed ? " · draft has changes" : "");
}

function ViewVersions({ view, readOnly, draftPending, onOpenRevision, onLoadView, onChanged, onStatus }: {
  view: SavedViewEntry; readOnly?: boolean;
  /** A save or snapshot job is still writing a draft. */
  draftPending?: boolean;
  onOpenRevision: Props["onOpenRevision"]; onLoadView: Props["onLoadView"];
  onChanged: () => void; onStatus: (text: string) => void;
}) {
  const [revisions, setRevisions] = useState<ViewRevision[] | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const store = { kind: view.kind, id: view.resource_id };
  const load = () => api.listViewRevisions(view.kind, view.resource_id, view.name)
    .then((out) => { setRevisions(out.revisions); setError(""); })
    .catch((e) => setError(`Revisions could not be loaded: ${(e as Error).message}`));
  useEffect(() => { void load(); }, [view.kind, view.resource_id, view.name, view.published_revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const publish = async () => {
    setBusy(true);
    try {
      const out = await api.publishView(view.kind, view.resource_id, view.name, note);
      setNote("");
      onStatus(`Published ${view.name} rev ${out.revision}.`);
      await load();
      onChanged();
    } catch (e) {
      onStatus(`Publish failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };
  const rollback = async (revision: number) => {
    if (!window.confirm(`Replace the draft of ${view.name} with rev ${revision}? `
        + "Unpublished draft changes are lost.")) return;
    setBusy(true);
    try {
      await api.rollbackView(view.kind, view.resource_id, view.name, revision);
      onStatus(`Draft of ${view.name} rolled back to rev ${revision}.`);
      onChanged();
      onLoadView(store, view.name);
    } catch (e) {
      onStatus(`Roll back failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };
  const copy = (target: "published" | number) => {
    const url = viewLink(view, target);
    navigator.clipboard?.writeText(url).then(
      () => onStatus("Published link copied."), () => onStatus(url));
  };
  const latest = revisions?.[0]?.revision;
  return (
    <div className="view-versions" role="group" aria-label={`Versions of ${view.name}`}>
      {!readOnly && <div className="view-publish">
        <input type="text" maxLength={500} value={note}
               aria-label={`Publish note for ${view.name}`}
               placeholder="note (optional)"
               onChange={(event) => setNote(event.target.value)}
               onKeyDown={(event) => { if (event.key === "Enter" && !busy && !draftPending) void publish(); }} />
        <button className="primary" disabled={busy || draftPending} onClick={() => void publish()}>
          {latest ? `Publish rev ${latest + 1}` : "Publish"}
        </button>
      </div>}
      {error && <div className="settings-hint" role="alert">{error}</div>}
      {revisions?.length === 0 && <div className="settings-hint">No published revisions.</div>}
      {revisions && revisions.length > 0 && <>
        <button className="quiet" onClick={() => copy("published")}
                aria-label={`Copy published link for ${view.name}`}>Copy published link</button>
        <ol className="view-revisions">
          {revisions.map((rev) => (
            <li key={rev.revision}>
              <div>
                <strong>Rev {rev.revision}</strong>
                {rev.published_at && <> · {new Date(rev.published_at).toLocaleString()}</>}
                {rev.published_by && <> · {rev.published_by}</>}
              </div>
              {rev.note && <div className="settings-hint">{rev.note}</div>}
              <div className="view-revision-actions">
                <button className="quiet" aria-label={`Open rev ${rev.revision} of ${view.name}`}
                        onClick={() => onOpenRevision(store, view.name, rev.revision)}>Open</button>
                <button className="quiet" aria-label={`Copy link to rev ${rev.revision} of ${view.name}`}
                        onClick={() => copy(rev.revision)}>Link</button>
                {!readOnly && <button className="quiet" disabled={busy || draftPending}
                        aria-label={`Roll back draft of ${view.name} to rev ${rev.revision}`}
                        onClick={() => void rollback(rev.revision)}>Roll back</button>}
              </div>
            </li>
          ))}
        </ol>
      </>}
    </div>
  );
}

export function SavedViews({ sources, datasets, active, onLoadView, onOpenRevision, readOnly, dashboardFilters = [] }: Props) {
  const saveable = datasets.filter((dataset) => dataset.sourceRef);
  const stores = sources.filter((source) => source.kind === "aurora" || source.kind === "s3");
  const defaultStore = stores.find((source) => source.kind === "aurora")
    ?? stores.find((source) => source.kind === "s3");
  const [views, setViews] = useState<SavedViewEntry[]>([]);
  const [pending, setPending] = useState(0);
  const [unavailable, setUnavailable] = useState<SavedViewStoreError[]>([]);
  const [name, setName] = useState("");
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const [listError, setListError] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [task, setTask] = useState<SnapshotTask>({ state: "idle" });
  const taskRunning = task.state === "polling";
  const storeKey = useMemo(() => stores.map((source) =>
    `${source.kind}:${source.id}`).sort().join("|"), [sources]);
  const storeKeyRef = useRef(storeKey);
  storeKeyRef.current = storeKey;

  const refresh = async () => {
    const requested = storeKeyRef.current;
    try {
      const result = await api.listAllViews();
      if (storeKeyRef.current !== requested) return;
      setPending(result.pending?.length ?? 0);
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
    if (!pending && !unavailable.length && !listError) return;
    const timer = setTimeout(() => void refresh(), pending ? 2000 : 20000);
    return () => clearTimeout(timer);
  }, [pending, views, unavailable, listError]);

  useEffect(() => {
    if (task.state !== "polling") return;
    const { kind, id, action, attempt } = task;
    let cancelled = false;
    const delay = attempt === 0 ? POLL_MS : Math.min(POLL_MS * 2 ** attempt, MAX_POLL_BACKOFF_MS);
    const timer = setTimeout(() => {
      api.savedViewJob(task.job.job_id).then((job) => {
        if (cancelled) return;
        const next = taskFor(job, { kind, id, action });
        setTask(next);
        if (next.state === "done") {
          setStatus(job.materialized_sources === 0
            ? `Saved ${job.name} without a snapshot.`
            : `Snapshot ready for ${job.name}.`);
          void refresh();
          onLoadView({ kind, id }, job.name);
        } else if (next.state === "failed") {
          setStatus(`Snapshot failed: ${next.error}`);
        } else if (attempt > 0) {
          setStatus(`Building snapshot for ${job.name}…`);
        }
      }).catch((error) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 404) {
          setTask({ kind, id, action, state: "failed", error: EXPIRED_SAVE_JOB });
          setStatus(EXPIRED_SAVE_JOB);
        } else if (attempt >= MAX_POLL_RETRIES) {
          const message = `Could not check snapshot status: ${(error as Error).message}`;
          setTask({ kind, id, action, state: "failed", error: message });
          setStatus(message);
        } else {
          setStatus(`Could not check snapshot status: ${(error as Error).message}. Retrying…`);
          setTask({ ...task, attempt: attempt + 1 });
        }
      });
    }, delay);
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
        name.trim(), saveable, activeSaveIdx, dashboardFilters);
      setName("");
      if (result.job_id) {
        const job = { ...result, status: result.status ?? "queued",
          completed_sources: result.completed_sources ?? 0, total_sources: result.total_sources ?? 0 } as SavedViewJob;
        setTask(taskFor(job, { kind: defaultStore.kind, id: defaultStore.id, action: "save" }));
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
      setTask(taskFor(job, { kind: view.kind, id: view.resource_id, action: "refresh" }));
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
    if (view.publication_unknown && !window.confirm(
      `Delete ${view.name}? Its published revisions, if any, are deleted too.`)) return;
    if (!view.publication_unknown && view.published_revision && !window.confirm(
      `Delete ${view.name} and its ${view.published_revision} published revision(s)?`)) return;
    try {
      await api.deleteView(view.kind, view.resource_id, view.name);
      setStatus(`Deleted ${view.name} from ${view.store_label}.`);
      void refresh();
    } catch (error) {
      setStatus(`Delete failed: ${(error as Error).message}`);
    }
  };

  const copyLink = (view: SavedViewEntry) => {
    const url = viewLink(view);
    navigator.clipboard?.writeText(url).then(
      () => setStatus("Link copied."),
      () => setStatus(url));
  };

  const counts = new Map<string, number>();
  for (const view of views) counts.set(view.name, (counts.get(view.name) ?? 0) + 1);

  return (
    <div>
      {!readOnly && defaultStore && saveable.length > 0 && (
        <div className="view-save">
          <input type="text"
                 aria-label="Saved view name"
                 placeholder={`Name dashboard (${saveable.length} tab${saveable.length > 1 ? "s" : ""})`}
                 value={name}
                 onChange={(event) => setName(event.target.value)}
                 onKeyDown={(event) => { if (event.key === "Enter") void save(); }} />
          <button className="primary" onClick={() => void save()}
                  disabled={!name.trim() || saving || !!taskRunning}>
            Save dashboard
          </button>
          <span className="settings-hint" title="New views use this default store.">
            {defaultStore.label}
          </span>
        </div>
      )}
      {!readOnly && !defaultStore && saveable.length > 0 && (
        <div className="settings-hint" style={{ margin: "6px 0" }}>
          No Aurora or S3 resource is available to store these views.
        </div>
      )}
      {!readOnly && datasets.length > 0 && saveable.length === 0 && (
        <div className="settings-hint" style={{ margin: "6px 0" }}>
          Uploaded files can't be saved — load from a datasource to save a view.
        </div>
      )}

      <div className="view-list">
        {!listError && views.length === 0 && unavailable.length === 0 && pending === 0 && (
          <div className="settings-hint">No saved views.</div>
        )}
        {views.map((view) => {
          const viewTask = task.state === "polling" && task.job.name === view.name
            && task.kind === view.kind && task.id === view.resource_id ? task : null;
          const taskForView = viewTask !== null;
          const updated = view.refreshed_at
            ? new Date(view.refreshed_at).toLocaleString() : "";
          const duplicate = (counts.get(view.name) ?? 0) > 1;
          const rowKey = `${view.kind}:${view.resource_id}:${view.name}`;
          const sourceLabelId = `saved-view-source-${encodeURIComponent(rowKey)}`;
          return (
            <div key={rowKey}
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
                {!readOnly && view.materialized_sources > 0 && <button className="quiet"
                        title={`Refresh saved data for ${view.name}`}
                        aria-label={`Refresh saved data for ${view.name} from ${view.store_label}`}
                        disabled={!!taskRunning || saving}
                        onClick={() => void refreshSnapshot(view)}>
                  {viewTask?.action === "refresh" ? "Refreshing…" : "Refresh"}
                </button>}
                <button className="quiet" title="Copy share link"
                        aria-label={`Copy link for ${view.name} from ${view.store_label}`}
                        onClick={() => copyLink(view)}>🔗</button>
                <button className="quiet" title="Publish and revisions"
                        aria-label={`Versions of ${view.name} from ${view.store_label}`}
                        aria-expanded={expanded === rowKey}
                        onClick={() => setExpanded(expanded === rowKey ? null : rowKey)}>
                  Versions
                </button>
                {!readOnly && <button className="quiet" title="Delete"
                        aria-label={`Delete ${view.name} from ${view.store_label}`}
                        disabled={!!taskForView}
                        onClick={() => void remove(view)}>✕</button>}
              </div>
              <div className={`settings-hint view-status${view.published_revision ? " published" : ""}`}
                   title={view.published_at
                     ? `Rev ${view.published_revision} published ${new Date(view.published_at).toLocaleString()}`
                     : undefined}>
                {publicationLabel(view)}
              </div>
              {expanded === rowKey && <ViewVersions view={view} readOnly={readOnly}
                draftPending={saving || !!taskRunning}
                onOpenRevision={onOpenRevision} onLoadView={onLoadView}
                onChanged={() => void refresh()} onStatus={setStatus} />}
              <div className="settings-hint"
                   title={updated ? `Snapshot created ${updated}; source freshness is unknown.` : "This saved view has no materialized snapshot."}>
                {view.materialized_sources > 0
                  ? `Snapshot · ${view.materialized_sources} source${view.materialized_sources === 1 ? "" : "s"}${updated ? ` · ${updated}` : ""}`
                  : "No snapshot"}
              </div>
              {view.materialized_sources > 0 && view.refresh_mode === "blocking" && (
                <div className="settings-hint" title="Refreshing this snapshot can pause queries that use it.">
                  {viewTask?.action === "refresh"
                    ? "Refreshing — queries may wait"
                    : "Refresh can pause queries"}
                </div>
              )}
              {viewTask && <div className="settings-hint" role="status">
                {viewTask.action === "refresh" ? "Refreshing snapshot" : "Building snapshot"} · {viewTask.job.completed_sources}/{viewTask.job.total_sources} sources
              </div>}
            </div>
          );
        })}
      </div>
      {listError && <div className="settings-hint" role="alert">{listError}</div>}
      {pending > 0 && <div role="status">Finding saved views… {pending} stores remaining</div>}
      {unavailable.length > 0 && <details><summary>{unavailable.length} saved-view stores unavailable</summary>
      {unavailable.map((item) => <div key={`${item.kind}:${item.resource_id}:${item.label}`}
        className="settings-hint" role="alert">
        Could not load saved views from {item.label}: {item.error}
      </div>)}
      </details>}
      {status && <div className="settings-hint" role={taskRunning || saving ? "status" : undefined}>{status}</div>}
    </div>
  );
}
