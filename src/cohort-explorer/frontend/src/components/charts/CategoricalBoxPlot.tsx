import { useMemo } from "react";
import { Box, Typography } from "@mui/material";
import type { SampleRow } from "../../types";
import { computeBoxPlotStats } from "../../utils/chartData";
import type { BoxPlotStats } from "../../types";

const BOX_COLOR = "#087a6a";
const WHISKER_COLOR = "#054f45";
const OUTLIER_COLOR = "#84bdb5";

interface Props {
  rows: SampleRow[];
  catField: string;
  numField: string;
  catLabel: string;
  numLabel: string;
}

interface CategoryStats {
  category: string;
  stats: BoxPlotStats;
}

export default function CategoricalBoxPlot({ rows, catField, numField, catLabel, numLabel }: Props) {
  const categories = useMemo(() => {
    const catKey = catField as keyof SampleRow;
    const numKey = numField as keyof SampleRow;

    const groups = new Map<string, number[]>();
    for (const r of rows) {
      const cat = r[catKey] as string | null;
      const num = r[numKey] as number | null;
      if (cat === null || num === null) continue;
      const arr = groups.get(cat);
      if (arr) arr.push(num);
      else groups.set(cat, [num]);
    }

    const result: CategoryStats[] = [];
    for (const [category, values] of groups) {
      const stats = computeBoxPlotStats(values);
      if (stats) result.push({ category, stats });
    }

    return result.sort((a, b) => b.stats.count - a.stats.count).slice(0, 25);
  }, [rows, catField, numField]);

  if (categories.length === 0) {
    return (
      <Box sx={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "text.secondary" }}>
        No data
      </Box>
    );
  }

  const globalMin = Math.min(...categories.flatMap((c) => [c.stats.min, ...c.stats.outliers]));
  const globalMax = Math.max(...categories.flatMap((c) => [c.stats.max, ...c.stats.outliers]));
  const padding = (globalMax - globalMin) * 0.05 || 1;
  const domainMin = globalMin - padding;
  const domainMax = globalMax + padding;
  const range = domainMax - domainMin;

  function toPercent(v: number) {
    return ((v - domainMin) / range) * 100;
  }

  const rowHeight = Math.max(20, Math.min(40, 300 / categories.length));

  return (
    <Box sx={{ flex: 1, minHeight: 0, overflow: "auto", px: 2, py: 1 }}>
      <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: "block" }}>
        {numLabel} by {catLabel}
      </Typography>
      <Box sx={{ display: "flex", flexDirection: "column", gap: 0.25 }}>
        {categories.map(({ category, stats }) => (
          <Box key={category} sx={{ display: "flex", alignItems: "center", height: rowHeight }}>
            <Typography
              variant="caption"
              sx={{ width: 120, flexShrink: 0, textAlign: "right", pr: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
              title={category}
            >
              {category}
            </Typography>
            <Box sx={{ flex: 1, position: "relative", height: "100%" }}>
              <svg width="100%" height="100%" preserveAspectRatio="none">
                <line
                  x1={`${toPercent(stats.min)}%`} y1="50%"
                  x2={`${toPercent(stats.max)}%`} y2="50%"
                  stroke={WHISKER_COLOR} strokeWidth={1}
                />
                <line
                  x1={`${toPercent(stats.min)}%`} y1="25%"
                  x2={`${toPercent(stats.min)}%`} y2="75%"
                  stroke={WHISKER_COLOR} strokeWidth={1}
                />
                <line
                  x1={`${toPercent(stats.max)}%`} y1="25%"
                  x2={`${toPercent(stats.max)}%`} y2="75%"
                  stroke={WHISKER_COLOR} strokeWidth={1}
                />
                <rect
                  x={`${toPercent(stats.q1)}%`}
                  y="15%"
                  width={`${toPercent(stats.q3) - toPercent(stats.q1)}%`}
                  height="70%"
                  fill={BOX_COLOR}
                  fillOpacity={0.25}
                  stroke={WHISKER_COLOR}
                  strokeWidth={1}
                />
                <line
                  x1={`${toPercent(stats.median)}%`} y1="15%"
                  x2={`${toPercent(stats.median)}%`} y2="85%"
                  stroke={WHISKER_COLOR} strokeWidth={2}
                />
                {stats.outliers.map((o, i) => (
                  <circle
                    key={i}
                    cx={`${toPercent(o)}%`}
                    cy="50%"
                    r={3}
                    fill={OUTLIER_COLOR}
                    stroke={WHISKER_COLOR}
                    strokeWidth={0.5}
                  />
                ))}
              </svg>
            </Box>
          </Box>
        ))}
      </Box>
    </Box>
  );
}
