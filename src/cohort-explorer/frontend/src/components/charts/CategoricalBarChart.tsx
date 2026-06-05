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

const SELECTED_COLOR = "#087a6a";
const UNSELECTED_COLOR = "#84bdb5";
const DEFAULT_COLOR = "#087a6a";

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
          <Tooltip formatter={(value) => [Number(value).toLocaleString(), "Samples"]} />
          <Bar
            dataKey="count"
            cursor="pointer"
            onClick={(_data, index) => onBarClick(sorted[index].value)}
            radius={[0, 3, 3, 0]}
          >
            {sorted.map((entry) => (
              <Cell
                key={entry.value}
                fill={
                  hasSelection
                    ? selected.includes(entry.value)
                      ? SELECTED_COLOR
                      : UNSELECTED_COLOR
                    : DEFAULT_COLOR
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </Box>
  );
}
