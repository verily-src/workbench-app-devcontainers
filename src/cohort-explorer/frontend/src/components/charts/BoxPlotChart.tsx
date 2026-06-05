import { useMemo } from "react";
import { Box, Typography } from "@mui/material";
import { computeBoxPlotStats } from "../../utils/chartData";

const BOX_COLOR = "#087a6a";
const WHISKER_COLOR = "#054f45";
const OUTLIER_COLOR = "#84bdb5";

interface Props {
  values: number[];
}

export default function BoxPlotChart({ values }: Props) {
  const stats = useMemo(() => computeBoxPlotStats(values), [values]);

  if (!stats) {
    return (
      <Box sx={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "text.secondary" }}>
        No data
      </Box>
    );
  }

  const padding = (stats.max - stats.min) * 0.15 || 1;
  const domainMin = Math.min(stats.min, ...stats.outliers) - padding;
  const domainMax = Math.max(stats.max, ...stats.outliers) + padding;
  const range = domainMax - domainMin;

  function toPercent(v: number) {
    return ((v - domainMin) / range) * 100;
  }

  const boxLeft = toPercent(stats.q1);
  const boxRight = toPercent(stats.q3);
  const boxWidth = boxRight - boxLeft;
  const medianPos = toPercent(stats.median);
  const minPos = toPercent(stats.min);
  const maxPos = toPercent(stats.max);

  const ticks = [stats.min, stats.q1, stats.median, stats.q3, stats.max];
  const uniqueTicks = [...new Set(ticks.map((t) => t.toFixed(1)))];

  return (
    <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", justifyContent: "center", px: 3, py: 2 }}>
      <svg width="100%" height="80" viewBox="0 0 100 40" preserveAspectRatio="none">
        {/* Whisker line: min to max */}
        <line x1={minPos} y1={20} x2={maxPos} y2={20} stroke={WHISKER_COLOR} strokeWidth={0.5} />

        {/* Min whisker cap */}
        <line x1={minPos} y1={12} x2={minPos} y2={28} stroke={WHISKER_COLOR} strokeWidth={0.5} />

        {/* Max whisker cap */}
        <line x1={maxPos} y1={12} x2={maxPos} y2={28} stroke={WHISKER_COLOR} strokeWidth={0.5} />

        {/* IQR box */}
        <rect
          x={boxLeft}
          y={8}
          width={boxWidth}
          height={24}
          fill={BOX_COLOR}
          fillOpacity={0.25}
          stroke={WHISKER_COLOR}
          strokeWidth={0.5}
        />

        {/* Median line */}
        <line x1={medianPos} y1={8} x2={medianPos} y2={32} stroke={WHISKER_COLOR} strokeWidth={1} />

        {/* Outliers */}
        {stats.outliers.map((o, i) => (
          <circle key={i} cx={toPercent(o)} cy={20} r={1.5} fill={OUTLIER_COLOR} stroke={WHISKER_COLOR} strokeWidth={0.3} />
        ))}
      </svg>

      <Box sx={{ display: "flex", justifyContent: "space-between", mt: 1 }}>
        {uniqueTicks.map((t) => (
          <Typography key={t} variant="caption" color="text.secondary">{t}</Typography>
        ))}
      </Box>

      <Box sx={{ display: "flex", justifyContent: "center", gap: 3, mt: 0.5 }}>
        <Typography variant="caption" color="text.secondary">n = {stats.count}</Typography>
        <Typography variant="caption" color="text.secondary">IQR: {(stats.q3 - stats.q1).toFixed(1)}</Typography>
        {stats.outliers.length > 0 && (
          <Typography variant="caption" color="text.secondary">{stats.outliers.length} outlier{stats.outliers.length > 1 ? "s" : ""}</Typography>
        )}
      </Box>
    </Box>
  );
}
