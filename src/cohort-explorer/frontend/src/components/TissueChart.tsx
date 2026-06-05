import { useMemo } from "react";
import { Box, Typography } from "@mui/material";
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
import type { FilterOption } from "../types";

interface Props {
  data: FilterOption[];
  selected: string[];
  onBarClick: (tissue: string) => void;
}

const SELECTED_COLOR = "#1565c0";
const UNSELECTED_COLOR = "#90caf9";
const DEFAULT_COLOR = "#42a5f5";

export default function TissueChart({ data, selected, onBarClick }: Props) {
  const sorted = useMemo(
    () => [...data].sort((a, b) => b.count - a.count),
    [data],
  );

  const hasSelection = selected.length > 0;

  return (
    <Box sx={{ height: "100%", px: 2, pt: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 0.5, flexShrink: 0 }}>
        Samples by Tissue Type
      </Typography>
      <Box sx={{ flex: 1, minHeight: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={sorted} layout="vertical" margin={{ left: 10, right: 30 }}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" fontSize={11} />
            <YAxis
              type="category"
              dataKey="label"
              width={180}
              fontSize={11}
              tick={{ fill: "#333" }}
            />
            <Tooltip
              formatter={(value) => [Number(value).toLocaleString(), "Samples"]}
            />
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
    </Box>
  );
}
