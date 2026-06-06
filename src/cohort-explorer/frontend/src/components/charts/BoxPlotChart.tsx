import { useMemo } from "react";
import { Box, Tooltip, Typography } from "@mui/material";
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

  const ticks = [stats.min, stats.q1, stats.median, stats.q3, stats.max];
  const uniqueTicks = [...new Set(ticks.map((t) => t.toFixed(1)))];

  return (
    <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", justifyContent: "center", px: 3, py: 2 }}>
      <svg width="100%" height="80" viewBox="0 0 100 40" preserveAspectRatio="none" style={{ overflow: "visible" }}>
        {/* Whisker line */}
        <line x1={toPercent(stats.min)} y1={20} x2={toPercent(stats.max)} y2={20} stroke={WHISKER_COLOR} strokeWidth={0.5}>
          <title>Range: {stats.min.toFixed(2)} – {stats.max.toFixed(2)}</title>
        </line>

        {/* Min cap */}
        <Tooltip title={`Min: ${stats.min.toFixed(2)}`} arrow>
          <line x1={toPercent(stats.min)} y1={12} x2={toPercent(stats.min)} y2={28} stroke={WHISKER_COLOR} strokeWidth={0.5} style={{ cursor: "default" }} />
        </Tooltip>

        {/* Max cap */}
        <Tooltip title={`Max: ${stats.max.toFixed(2)}`} arrow>
          <line x1={toPercent(stats.max)} y1={12} x2={toPercent(stats.max)} y2={28} stroke={WHISKER_COLOR} strokeWidth={0.5} style={{ cursor: "default" }} />
        </Tooltip>

        {/* IQR box */}
        <Tooltip title={`Q1: ${stats.q1.toFixed(2)}, Q3: ${stats.q3.toFixed(2)}, IQR: ${(stats.q3 - stats.q1).toFixed(2)}`} arrow>
          <rect
            x={toPercent(stats.q1)}
            y={8}
            width={toPercent(stats.q3) - toPercent(stats.q1)}
            height={24}
            fill={BOX_COLOR}
            fillOpacity={0.25}
            stroke={WHISKER_COLOR}
            strokeWidth={0.5}
            style={{ cursor: "default" }}
          />
        </Tooltip>

        {/* Median */}
        <Tooltip title={`Median: ${stats.median.toFixed(2)}`} arrow>
          <line x1={toPercent(stats.median)} y1={8} x2={toPercent(stats.median)} y2={32} stroke={WHISKER_COLOR} strokeWidth={1} style={{ cursor: "default" }} />
        </Tooltip>

        {/* Outliers */}
        {stats.outliers.map((o, i) => (
          <Tooltip key={i} title={`Outlier: ${o.toFixed(2)}`} arrow>
            <circle cx={toPercent(o)} cy={20} r={1.5} fill={OUTLIER_COLOR} stroke={WHISKER_COLOR} strokeWidth={0.3} style={{ cursor: "default" }} />
          </Tooltip>
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
