import { useEffect, useMemo, useState } from "react";
import type { ChartSuggestion } from "../types/charts";
import type { SemProfile, TechProfile } from "../types/profile";

export function useChartSuggestions(technical: TechProfile | null, semantic: SemProfile | null, enabled: boolean) {
  const [charts, setCharts] = useState<ChartSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const techKey = useMemo(() => (technical ? JSON.stringify(technical) : ""), [technical]);
  const semKey = useMemo(() => (semantic ? JSON.stringify(semantic) : ""), [semantic]);

  useEffect(() => {
    if (!enabled || !technical) {
      setCharts([]);
      return;
    }
    setLoading(true);
    fetch("/api/charts/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ technical, semantic }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error(await r.text());
        return r.json();
      })
      .then((j: { charts: ChartSuggestion[] }) => setCharts(j.charts || []))
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [enabled, techKey, semKey]);

  return { charts, loading, err };
}
