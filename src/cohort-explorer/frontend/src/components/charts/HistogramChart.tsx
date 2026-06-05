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
import { computeHistogramBins } from "../../utils/chartData";

const SELECTED_COLOR = "#087a6a";
const UNSELECTED_COLOR = "#84bdb5";
const DEFAULT_COLOR = "#087a6a";

interface Props {
  values: number[];
  appliedMin: number | null;
  appliedMax: number | null;
  onBinClick: (min: number, max: number) => void;
}

export default function HistogramChart({ values, appliedMin, appliedMax, onBinClick }: Props) {
  const bins = useMemo(() => computeHistogramBins(values), [values]);

  const hasRangeFilter = appliedMin !== null || appliedMax !== null;

  function isBinSelected(bin: { binStart: number; binEnd: number }) {
    if (!hasRangeFilter) return false;
    const lo = appliedMin ?? -Infinity;
    const hi = appliedMax ?? Infinity;
    return bin.binStart >= lo && bin.binEnd <= hi;
  }

  if (bins.length === 0) {
    return (
      <Box sx={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "text.secondary" }}>
        No data
      </Box>
    );
  }

  return (
    <Box sx={{ flex: 1, minHeight: 0 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={bins} margin={{ left: 10, right: 20, bottom: 20 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="label"
            fontSize={10}
            angle={-35}
            textAnchor="end"
            interval={0}
            height={50}
          />
          <YAxis fontSize={11} />
          <Tooltip
            formatter={(value) => [Number(value).toLocaleString(), "Samples"]}
            labelFormatter={(label) => `Range: ${label}`}
          />
          <Bar
            dataKey="count"
            cursor="pointer"
            onClick={(_data, index) => onBinClick(bins[index].binStart, bins[index].binEnd)}
            radius={[3, 3, 0, 0]}
          >
            {bins.map((bin, i) => (
              <Cell
                key={i}
                fill={
                  hasRangeFilter
                    ? isBinSelected(bin) ? SELECTED_COLOR : UNSELECTED_COLOR
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
