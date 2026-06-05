import { useMemo } from "react";
import { Box, Typography } from "@mui/material";
import {
  ComposedChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import { computeBoxPlotStats } from "../../utils/chartData";

const BOX_COLOR = "#087a6a";
const LINE_COLOR = "#054f45";

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

  const padding = (stats.max - stats.min) * 0.1 || 1;
  const domainMin = Math.min(stats.min, ...stats.outliers) - padding;
  const domainMax = Math.max(stats.max, ...stats.outliers) + padding;

  return (
    <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <Box sx={{ flex: 1, minHeight: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={[{ name: "" }]}
            layout="vertical"
            margin={{ left: 20, right: 20, top: 30, bottom: 10 }}
          >
            <XAxis
              type="number"
              domain={[domainMin, domainMax]}
              fontSize={11}
              tickCount={8}
            />
            <YAxis type="category" dataKey="name" hide />

            {/* Whisker lines */}
            <ReferenceLine x={stats.min} stroke={LINE_COLOR} strokeWidth={1} />
            <ReferenceLine x={stats.max} stroke={LINE_COLOR} strokeWidth={1} />

            {/* IQR box */}
            <ReferenceArea
              x1={stats.q1}
              x2={stats.q3}
              fill={BOX_COLOR}
              fillOpacity={0.3}
              stroke={LINE_COLOR}
              strokeWidth={1}
            />

            {/* Median line */}
            <ReferenceLine
              x={stats.median}
              stroke={LINE_COLOR}
              strokeWidth={2}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </Box>
      <Box sx={{ display: "flex", justifyContent: "space-around", px: 2, pb: 1 }}>
        <Typography variant="caption" color="text.secondary">Min: {stats.min.toFixed(1)}</Typography>
        <Typography variant="caption" color="text.secondary">Q1: {stats.q1.toFixed(1)}</Typography>
        <Typography variant="caption" color="text.secondary">Median: {stats.median.toFixed(1)}</Typography>
        <Typography variant="caption" color="text.secondary">Q3: {stats.q3.toFixed(1)}</Typography>
        <Typography variant="caption" color="text.secondary">Max: {stats.max.toFixed(1)}</Typography>
        {stats.outliers.length > 0 && (
          <Typography variant="caption" color="text.secondary">Outliers: {stats.outliers.length}</Typography>
        )}
      </Box>
    </Box>
  );
}
