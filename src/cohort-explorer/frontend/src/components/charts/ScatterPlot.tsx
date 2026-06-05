import { useMemo } from "react";
import { Box } from "@mui/material";
import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { SampleRow } from "../../types";

const DOT_COLOR = "#087a6a";

interface Props {
  rows: SampleRow[];
  xField: string;
  yField: string;
  xLabel: string;
  yLabel: string;
}

export default function ScatterPlot({ rows, xField, yField, xLabel, yLabel }: Props) {
  const data = useMemo(() => {
    const xKey = xField as keyof SampleRow;
    const yKey = yField as keyof SampleRow;
    return rows
      .map((r) => ({ x: r[xKey] as number | null, y: r[yKey] as number | null }))
      .filter((d): d is { x: number; y: number } => d.x !== null && d.y !== null);
  }, [rows, xField, yField]);

  if (data.length === 0) {
    return (
      <Box sx={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "text.secondary" }}>
        No data
      </Box>
    );
  }

  return (
    <Box sx={{ flex: 1, minHeight: 0 }}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ left: 10, right: 20, bottom: 20, top: 10 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="x" type="number" name={xLabel} fontSize={11} label={{ value: xLabel, position: "bottom", offset: 0, fontSize: 11 }} />
          <YAxis dataKey="y" type="number" name={yLabel} fontSize={11} label={{ value: yLabel, angle: -90, position: "insideLeft", offset: 10, fontSize: 11 }} />
          <ZAxis range={[20, 20]} />
          <Tooltip
            formatter={(value, name) => [Number(value).toFixed(2), String(name)]}
            cursor={{ strokeDasharray: "3 3" }}
          />
          <Scatter data={data} fill={DOT_COLOR} fillOpacity={0.5} />
        </ScatterChart>
      </ResponsiveContainer>
    </Box>
  );
}
