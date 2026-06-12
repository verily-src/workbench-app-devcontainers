import { useMemo } from "react";
import { Box } from "@mui/material";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { FilterOption } from "../../types";

const PALETTE = [
  "#087a6a", "#0a9e89", "#3bb09e", "#6bc4b5", "#84bdb5",
  "#074D43", "#0b6b5c", "#4da396", "#96d4cb", "#b5e2dc",
];

interface Props {
  data: FilterOption[];
  selected: string[];
  onBarClick: (value: string) => void;
}

export default function CategoricalBarChart({ data, selected, onBarClick }: Props) {
  const sorted = useMemo(
    () => [...data].sort((a, b) => b.count - a.count),
    [data],
  );

  const hasSelection = selected.length > 0;

  return (
    <Box sx={{ flex: 1, minHeight: 0 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={sorted} layout="vertical" margin={{ left: 10, right: 30 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" fontSize={11} />
          <YAxis
            type="category"
            dataKey="label"
            width={150}
            fontSize={11}
            tick={{ fill: "#212529" }}
          />
          <Tooltip
            formatter={(value) => [Number(value).toLocaleString(), "Samples"]}
            labelFormatter={(label) => String(label)}
          />
          <Bar
            dataKey="count"
            cursor="pointer"
            onClick={(_data, index) => onBarClick(sorted[index].value)}
            radius={[0, 3, 3, 0]}
          >
            {sorted.map((entry, i) => (
              <Cell
                key={entry.value}
                fill={PALETTE[i % PALETTE.length]}
                opacity={hasSelection && !selected.includes(entry.value) ? 0.35 : 1}
                stroke={hasSelection && selected.includes(entry.value) ? "#054f45" : "none"}
                strokeWidth={hasSelection && selected.includes(entry.value) ? 2 : 0}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </Box>
  );
}
