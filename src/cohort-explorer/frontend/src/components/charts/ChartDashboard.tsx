import { Box } from "@mui/material";
import type { ChartConfig, FilterState, FiltersResponse, SampleRow } from "../../types";
import ChartCard from "./ChartCard";
import AddChartButton from "./AddChartButton";

interface Props {
  chartConfigs: ChartConfig[];
  available: FiltersResponse | null;
  rows: SampleRow[];
  applied: FilterState;
  onChartFilter: (fieldKey: string, value: string | { min: number; max: number }) => void;
  onAddChart: (fieldKey: string) => void;
  onRemoveChart: (id: string) => void;
  onUpdateChart: (id: string, updates: Partial<Pick<ChartConfig, "fieldKey" | "chartType" | "field2Key">>) => void;
}

export default function ChartDashboard({
  chartConfigs,
  available,
  rows,
  applied,
  onChartFilter,
  onAddChart,
  onRemoveChart,
  onUpdateChart,
}: Props) {
  return (
    <Box sx={{ height: "100%", overflow: "auto", p: 1.5, display: "flex", flexDirection: "column", gap: 1.5 }}>
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1.5, flex: 1 }}>
        {chartConfigs.map((config) => (
          <ChartCard
            key={config.id}
            config={config}
            available={available}
            rows={rows}
            applied={applied}
            onChartFilter={onChartFilter}
            onRemove={() => onRemoveChart(config.id)}
            onUpdate={(updates) => onUpdateChart(config.id, updates)}
          />
        ))}
      </Box>
      <Box sx={{ display: "flex", justifyContent: "center", py: 1 }}>
        <AddChartButton onAdd={onAddChart} />
      </Box>
    </Box>
  );
}
