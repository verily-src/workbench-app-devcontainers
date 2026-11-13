import { useEffect, useState } from "react";

export interface PreviewResult {
  fq_table: string;
  columns: { name: string; type: string; mode?: string; description?: string | null }[];
  rows: unknown[][];
  preview_row_count: number;
  total_rows: number | null;
  size_bytes: number | null;
}

export function usePreview(project: string, dataset: string, table: string) {
  const [data, setData] = useState<PreviewResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/projects/${encodeURIComponent(project)}/datasets/${encodeURIComponent(dataset)}/tables/${encodeURIComponent(table)}/preview`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await r.text());
        return r.json();
      })
      .then(setData)
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [project, dataset, table]);

  return { data, loading, err };
}
