import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Cell,
} from "recharts";
import type { ChartSuggestion } from "../types/charts";
import type { TechProfile } from "../types/profile";
import { Card } from "./rds";

const COLORS = ["#0969da", "#1a7f37", "#9a6700", "#8250df", "#cf222e", "#656d76"];

function buildRows(tech: TechProfile, sug: ChartSuggestion) {
  const names = sug.columns.filter(Boolean);
  if (names.length === 0) return [];

  // Null-rate style: multiple columns -> bar of null_percent
  if (names.length > 1 || sug.title.toLowerCase().includes("null")) {
    return names.map((n) => {
      const c = tech.columns.find((x) => x.name === n);
      return { name: n, value: c?.null_percent ?? 0 };
    });
  }

  const col = tech.columns.find((c) => c.name === names[0]);
  if (!col) return [];
  if (col.value_counts && Object.keys(col.value_counts).length) {
    return Object.entries(col.value_counts).map(([name, value]) => ({ name: String(name).slice(0, 40), value }));
  }
  if ((col.top_values || []).length) {
    return (col.top_values || []).map((name) => ({ name: String(name).slice(0, 40), value: 1 }));
  }
  return [{ name: col.name, value: col.distinct_count ?? 0 }];
}

export function ChartPanel(props: {
  technical: TechProfile | null;
  suggestions: ChartSuggestion[];
  loading: boolean;
  err: string | null;
}) {
  if (props.loading) return <p>Generating chart suggestions…</p>;
  if (props.err) return <p style={{ color: "var(--wb-danger)" }}>{props.err}</p>;
  if (!props.technical) return <p>Charts unlock after technical profiling.</p>;
  if (!props.suggestions.length) return <p>No chart suggestions returned.</p>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {props.suggestions.map((sug, idx) => {
        const rows = buildRows(props.technical!, sug);
        if (!rows.length) return null;
        const isPie = sug.chart_type === "pie" && rows.length <= 8;
        return (
          <Card key={`${sug.title}-${idx}`} title={sug.title}>
            <p style={{ color: "var(--wb-muted)", fontSize: 14 }}>{sug.rationale}</p>
            <div style={{ width: "100%", height: 320 }}>
              <ResponsiveContainer>
                {isPie ? (
                  <PieChart>
                    <Pie data={rows} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} label>
                      {rows.map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                    <Legend />
                  </PieChart>
                ) : (
                  <BarChart data={rows} margin={{ top: 8, right: 16, left: 0, bottom: 64 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" angle={-35} textAnchor="end" interval={0} height={80} tick={{ fontSize: 11 }} />
                    <YAxis />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="value" fill="#0969da" name={sug.columns.join(", ") || "value"} />
                  </BarChart>
                )}
              </ResponsiveContainer>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
