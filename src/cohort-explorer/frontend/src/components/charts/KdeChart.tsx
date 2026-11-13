import { useMemo } from "react";
import { Box } from "@mui/material";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { computeKde } from "../../utils/chartData";

const FILL_COLOR = "#087a6a";
interface Props {
  values: number[];
}

export default function KdeChart({ values }: Props) {
  const { kde, bins } = useMemo(() => computeKde(values), [values]);

  const maxDensity = Math.max(...kde.map((p) => p.density), 0);
  const maxCount = Math.max(...bins.map((b) => b.count), 0);
  const scale = maxCount > 0 && maxDensity > 0 ? maxCount / maxDensity : 1;

  const chartData = useMemo(
    () => kde.map((p) => ({ x: +p.x.toFixed(3), density: p.density * scale })),
    [kde, scale],
  );

  if (kde.length === 0) {
    return (
      <Box sx={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "text.secondary" }}>
        No data
      </Box>
    );
  }

  return (
    <Box sx={{ flex: 1, minHeight: 0 }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ left: 10, right: 20, bottom: 5, top: 10 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="x" type="number" domain={["dataMin", "dataMax"]} fontSize={11} tickCount={8} />
          <YAxis fontSize={11} />
          <Tooltip
            formatter={(value) => [Number(value).toLocaleString(), "Density"]}
            labelFormatter={(label) => `Value: ${Number(label).toFixed(2)}`}
          />
          <Area
            dataKey="density"
            type="monotone"
            stroke={FILL_COLOR}
            fill={FILL_COLOR}
            fillOpacity={0.2}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </Box>
  );
}
