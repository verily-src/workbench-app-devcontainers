import { useCallback, useEffect, useState } from "react";
import type { WorkspaceInfo, WorkspaceDataset } from "../types/catalog";

export function useWorkspaces() {
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch("/api/workspaces")
      .then(async (r) => {
        if (!r.ok) throw new Error(await r.text());
        return r.json();
      })
      .then((d) => { if (!cancelled) setWorkspaces(d.workspaces || []); })
      .catch((e) => { if (!cancelled) setErr(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return { workspaces, loading, err };
}

export function useWorkspaceDatasets(workspaceId: string) {
  const [datasets, setDatasets] = useState<WorkspaceDataset[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback((id: string) => {
    if (!id) { setDatasets([]); return; }
    setLoading(true);
    setErr(null);
    fetch(`/api/workspaces/${encodeURIComponent(id)}/datasets`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await r.text());
        return r.json();
      })
      .then((d) => setDatasets(d.datasets || []))
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(workspaceId); }, [workspaceId, load]);

  return { datasets, loading, err };
}
