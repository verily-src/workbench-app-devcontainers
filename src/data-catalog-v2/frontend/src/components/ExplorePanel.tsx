import { useMemo, useState, useEffect, useCallback, lazy, Suspense } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { IMutField, IRow } from "@kanaries/graphic-walker";
import "@kanaries/graphic-walker/dist/style.css";
import type { ChartSuggestion } from "../types/charts";
import type { TechColumn, TechProfile } from "../types/profile";
import { Badge, Card } from "./rds";

const GraphicWalkerLazy = lazy(() =>
  import("@kanaries/graphic-walker").then((m) => ({ default: m.GraphicWalker as React.ComponentType<any> }))
);

// ── Field mapping ────────────────────────────────────────────────────────────

const BQ_TO_GW: Record<string, IMutField["semanticType"]> = {
  INTEGER: "quantitative", INT64: "quantitative",
  FLOAT: "quantitative", FLOAT64: "quantitative",
  NUMERIC: "quantitative", BIGNUMERIC: "quantitative",
  BOOLEAN: "nominal", BOOL: "nominal",
  STRING: "nominal", BYTES: "nominal",
  DATE: "nominal", DATETIME: "nominal",
  TIMESTAMP: "nominal", TIME: "nominal",
  GEOGRAPHY: "nominal", JSON: "nominal",
  RECORD: "nominal", STRUCT: "nominal",
};

function bqColToField(col: TechColumn): IMutField {
  const upper = (col.data_type || "STRING").toUpperCase();
  const semanticType = BQ_TO_GW[upper] || "nominal";
  return {
    fid: col.name,
    name: col.name,
    semanticType,
    analyticType: semanticType === "quantitative" ? "measure" : "dimension",
  };
}

function buildFields(tech: TechProfile): IMutField[] {
  return tech.columns.map(bqColToField);
}

// ── AI insight charts (Recharts) ─────────────────────────────────────────────

const CHART_COLORS = ["#0f7b6c", "#278bac", "#1a7f37", "#9a6700", "#8250df", "#cf222e"];

function buildChartRows(tech: TechProfile, sug: ChartSuggestion) {
  const names = sug.columns.filter(Boolean);
  if (!names.length) return [];

  if (names.length > 1 || sug.title.toLowerCase().includes("null")) {
    return names.map((n) => {
      const c = tech.columns.find((x) => x.name === n);
      return { name: n, value: c?.null_percent ?? 0 };
    });
  }

  const col = tech.columns.find((c) => c.name === names[0]);
  if (!col) return [];
  if (col.value_counts && Object.keys(col.value_counts).length) {
    return Object.entries(col.value_counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 12)
      .map(([name, value]) => ({ name: String(name).slice(0, 30), value }));
  }
  if ((col.top_values || []).length) {
    return (col.top_values || []).slice(0, 12).map((name) => ({ name: String(name).slice(0, 30), value: 1 }));
  }
  return [{ name: col.name, value: col.distinct_count ?? 0 }];
}

function deriveAxisLabels(tech: TechProfile, sug: ChartSuggestion): { xLabel: string; yLabel: string } {
  const names = sug.columns.filter(Boolean);
  const titleLower = sug.title.toLowerCase();

  if (titleLower.includes("null")) {
    return { xLabel: "Column", yLabel: "Null %" };
  }

  if (names.length === 1) {
    const col = tech.columns.find((c) => c.name === names[0]);
    const colName = names[0].replace(/_/g, " ");

    if (col?.value_counts && Object.keys(col.value_counts).length) {
      return { xLabel: colName, yLabel: "Count (rows)" };
    }
    if (col?.numeric_stats?.min != null) {
      return { xLabel: colName, yLabel: "Value" };
    }
    return { xLabel: colName, yLabel: "Count" };
  }

  if (names.length > 1) {
    if (titleLower.includes("distinct")) return { xLabel: "Column", yLabel: "Distinct values" };
    if (titleLower.includes("null")) return { xLabel: "Column", yLabel: "Null %" };
    return { xLabel: "Column", yLabel: "Value" };
  }

  return { xLabel: "", yLabel: "" };
}

function InsightCharts(props: {
  tech: TechProfile;
  suggestions: ChartSuggestion[];
  loading: boolean;
  err: string | null;
}) {
  if (props.loading) {
    return <div style={{ padding: "16px 0", color: "var(--wb-muted)", fontSize: 13 }}>Generating AI insights…</div>;
  }
  if (props.err) {
    return <div style={{ padding: "16px 0", color: "var(--wb-danger)", fontSize: 13 }}>{props.err}</div>;
  }
  if (!props.suggestions.length) return null;

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--wb-muted)", marginBottom: 10 }}>
        AI-suggested insights
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", gap: 16 }}>
        {props.suggestions.map((sug, idx) => {
          const rows = buildChartRows(props.tech, sug);
          if (!rows.length) return null;
          const isPie = sug.chart_type === "pie" && rows.length <= 8;
          const { xLabel, yLabel } = deriveAxisLabels(props.tech, sug);
          return (
            <Card key={`${sug.title}-${idx}`}>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 2 }}>{sug.title}</div>
              <div style={{ fontSize: 12, color: "var(--wb-muted)", marginBottom: 8, lineHeight: 1.4 }}>{sug.rationale}</div>
              <div style={{ display: "flex", gap: 4, marginBottom: 10 }}>
                <Badge tone="neutral">{sug.chart_type}</Badge>
                {sug.columns.slice(0, 3).map((c) => <Badge key={c} tone="info">{c}</Badge>)}
              </div>
              <div style={{ width: "100%", height: 240 }}>
                <ResponsiveContainer>
                  {isPie ? (
                    <PieChart>
                      <Pie data={rows} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={70} label>
                        {rows.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  ) : (
                    <BarChart data={rows} margin={{ top: 4, right: 12, left: 8, bottom: 65 }}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis
                        dataKey="name"
                        angle={-30}
                        textAnchor="end"
                        interval={0}
                        height={80}
                        tick={{ fontSize: 10 }}
                        label={{ value: xLabel, position: "insideBottom", offset: 0, fontSize: 11, fill: "#555", fontWeight: 600 }}
                      />
                      <YAxis
                        tick={{ fontSize: 10 }}
                        label={{ value: yLabel, angle: -90, position: "insideLeft", fontSize: 11, fill: "#555", fontWeight: 600, dx: -4 }}
                      />
                      <Tooltip />
                      <Bar dataKey="value" fill="#0f7b6c" name={sug.columns.join(", ") || "value"} radius={[3, 3, 0, 0]} />
                    </BarChart>
                  )}
                </ResponsiveContainer>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

// ── Graphic Walker wrapper ───────────────────────────────────────────────────

function GWExplorer(props: {
  fields: IMutField[];
  data: IRow[];
  mode: "local" | "server";
  project: string;
  dataset: string;
  table: string;
}) {
  const computation = useCallback(
    async (payload: any): Promise<IRow[]> => {
      const resp = await fetch(
        `/api/gw/compute/${encodeURIComponent(props.project)}/${encodeURIComponent(props.dataset)}/${encodeURIComponent(props.table)}`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
      );
      if (!resp.ok) throw new Error(await resp.text());
      return resp.json();
    },
    [props.project, props.dataset, props.table],
  );

  if (props.mode === "server") {
    return (
      <GraphicWalkerLazy
        fields={props.fields}
        computation={computation}
        appearance="light"
        vizThemeConfig="vega"
      />
    );
  }

  return (
    <GraphicWalkerLazy
      fields={props.fields}
      dataSource={props.data}
      appearance="light"
      vizThemeConfig="vega"
    />
  );
}

// ── Key Insights panel (AI-suggested charts) ────────────────────────────────

export function KeyInsightsPanel(props: {
  technical: TechProfile | null;
  suggestions: ChartSuggestion[];
  sugLoading: boolean;
  sugErr: string | null;
}) {
  if (!props.technical) {
    return (
      <Card>
        <p style={{ color: "var(--wb-muted)" }}>Key Insights unlock after technical profiling. Run it from the Technical tab.</p>
      </Card>
    );
  }

  return (
    <div style={{ marginTop: 8 }}>
      <InsightCharts
        tech={props.technical}
        suggestions={props.suggestions}
        loading={props.sugLoading}
        err={props.sugErr}
      />
    </div>
  );
}

// ── Interactive Explorer panel (Graphic Walker) ─────────────────────────────

export function InteractiveExplorerPanel(props: {
  project: string;
  dataset: string;
  table: string;
  technical: TechProfile | null;
}) {
  const [mode, setMode] = useState<"local" | "server">("local");
  const [previewRows, setPreviewRows] = useState<IRow[] | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);

  const fields = useMemo(
    () => (props.technical ? buildFields(props.technical) : []),
    [props.technical],
  );

  useEffect(() => {
    if (!props.technical) return;
    setLoadingPreview(true);
    fetch(
      `/api/projects/${encodeURIComponent(props.project)}/datasets/${encodeURIComponent(props.dataset)}/tables/${encodeURIComponent(props.table)}/preview?limit=2000`,
    )
      .then(async (r) => {
        if (!r.ok) throw new Error(await r.text());
        return r.json();
      })
      .then((j: { rows?: IRow[] }) => setPreviewRows(j.rows || []))
      .catch(() => setPreviewRows([]))
      .finally(() => setLoadingPreview(false));
  }, [props.project, props.dataset, props.table, props.technical]);

  if (!props.technical) {
    return (
      <Card>
        <p style={{ color: "var(--wb-muted)" }}>Interactive Explorer unlocks after technical profiling. Run it from the Technical tab.</p>
      </Card>
    );
  }

  const isLocal = mode === "local";
  const ready = isLocal ? previewRows !== null && !loadingPreview : true;

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12, fontSize: 13 }}>
        <span style={{ color: "var(--wb-muted)" }}>Data source:</span>
        {(["local", "server"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            style={{
              padding: "4px 12px",
              borderRadius: "var(--wb-radius)",
              border: `1px solid ${mode === m ? "var(--wb-primary)" : "var(--wb-border)"}`,
              background: mode === m ? "var(--wb-primary)" : "var(--wb-surface)",
              color: mode === m ? "#fff" : "var(--wb-text)",
              cursor: "pointer", fontSize: 13, fontWeight: 500,
            }}
          >
            {m === "local" ? "Preview (fast)" : "Full dataset (BigQuery)"}
          </button>
        ))}
        <span style={{ color: "var(--wb-muted)", fontSize: 12 }}>
          {isLocal ? `${previewRows?.length ?? "…"} sample rows` : "Queries full table via BigQuery"}
        </span>
      </div>

      {loadingPreview && isLocal ? (
        <Card><p style={{ color: "var(--wb-muted)" }}>Loading preview data…</p></Card>
      ) : ready ? (
        <Card style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ minHeight: 520 }}>
            <Suspense fallback={<div style={{ padding: 24, color: "var(--wb-muted)" }}>Loading explorer…</div>}>
              <GWExplorer
                key={`${mode}-${props.table}`}
                fields={fields}
                data={previewRows || []}
                mode={mode}
                project={props.project}
                dataset={props.dataset}
                table={props.table}
              />
            </Suspense>
          </div>
        </Card>
      ) : null}
    </div>
  );
}
