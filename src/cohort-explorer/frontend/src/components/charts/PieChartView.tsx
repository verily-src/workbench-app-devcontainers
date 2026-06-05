import { useMemo } from "react";
import { Box } from "@mui/material";
import {
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import type { FilterOption } from "../../types";

const SELECTED_COLOR = "#087a6a";
const UNSELECTED_COLOR = "#84bdb5";
const PALETTE = [
  "#087a6a", "#0a9e89", "#3bb09e", "#6bc4b5", "#84bdb5",
  "#074D43", "#0b6b5c", "#4da396", "#96d4cb", "#b5e2dc",
];

interface Props {
  data: FilterOption[];
  selected: string[];
  onSliceClick: (value: string) => void;
}

export default function PieChartView({ data, selected, onSliceClick }: Props) {
  const sorted = useMemo(
    () => [...data].sort((a, b) => b.count - a.count),
    [data],
  );

  const hasSelection = selected.length > 0;

  return (
    <Box sx={{ flex: 1, minHeight: 0 }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={sorted}
            dataKey="count"
            nameKey="label"
            cx="50%"
            cy="50%"
            outerRadius="70%"
            cursor="pointer"
            onClick={(_data, index) => onSliceClick(sorted[index].value)}
          >
            {sorted.map((entry, i) => (
              <Cell
                key={entry.value}
                fill={
                  hasSelection
                    ? selected.includes(entry.value)
                      ? SELECTED_COLOR
                      : UNSELECTED_COLOR
                    : PALETTE[i % PALETTE.length]
                }
              />
            ))}
          </Pie>
          <Tooltip formatter={(value) => [Number(value).toLocaleString(), "Samples"]} />
          <Legend
            layout="vertical"
            align="right"
            verticalAlign="middle"
            wrapperStyle={{ fontSize: 11, maxHeight: "100%", overflowY: "auto" }}
          />
        </PieChart>
      </ResponsiveContainer>
    </Box>
  );
}
