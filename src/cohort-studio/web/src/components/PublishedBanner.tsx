import type { ViewRevision } from "../types";

/** Viewer mode: which published revision is open read-only. */
export interface PublishedViewer {
  store: { kind: string; id: string };
  name: string;
  revision: ViewRevision;
}

export function PublishedBanner({ viewer, onOpenDraft }: {
  viewer: PublishedViewer; onOpenDraft: () => void;
}) {
  const { revision } = viewer;
  const date = revision.published_at ? new Date(revision.published_at).toLocaleDateString() : "";
  return (
    <div className="published-banner" role="status" aria-label="Published view">
      <strong>Published · rev {revision.revision}{date ? ` · ${date}` : ""}</strong>
      <span>{viewer.name}{revision.published_by ? ` · ${revision.published_by}` : ""}</span>
      {revision.note && <span className="published-note">{revision.note}</span>}
      <span className="published-readonly">Read-only</span>
      <button type="button" className="quiet" onClick={onOpenDraft}>Open draft</button>
    </div>
  );
}
