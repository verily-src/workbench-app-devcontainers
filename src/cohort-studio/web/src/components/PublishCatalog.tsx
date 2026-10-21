import { useState } from "react";
import { api } from "../api";
import type { Source } from "../types";
import type { Toast } from "../workflowAlerts";

interface Props {
  source: Source;
  onToast: (t: Omit<Toast, "id">) => void;
  onPublished: () => void;
}

export function PublishCatalog({ source, onToast, onPublished }: Props) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const publish = async () => {
    const n = name.trim();
    if (!n) return;
    setBusy(true);
    try {
      const out = await api.publishCatalog(source.id, n);
      onToast({ title: "Catalog published", tone: "ok",
        body: `${out.views.length} view(s) → ${out.catalog_id}`
          + (out.skipped.length ? ` · ${out.skipped.length} skipped` : "") });
      setName("");
      onPublished();
    } catch (e) {
      onToast({ title: "Publish failed", tone: "fail",
                body: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="view-save" title="Views-only DuckDB catalog over this folder's data files">
      <input type="text" placeholder="catalog name" value={name}
             disabled={busy}
             onChange={(e) => setName(e.target.value)}
             onKeyDown={(e) => { if (e.key === "Enter") publish(); }} />
      <button onClick={publish} disabled={busy || !name.trim()}>
        {busy ? "Publishing…" : "Publish catalog"}
      </button>
    </div>
  );
}
