import { Box } from "@mui/material";
import type { ChartConfig, ChartType, FieldMeta, FilterState, FiltersResponse, SampleRow } from "../../types";
import ChartCard from "./ChartCard";
import AddChartButton from "./AddChartButton";

interface Props {
  chartConfigs: ChartConfig[];
  available: FiltersResponse | null;
  rows: SampleRow[];
  applied: FilterState;
  fieldMeta: FieldMeta[];
  onChartFilter: (fieldKey: string, value: string | { min: number; max: number }) => void;
  onAddChart: (fieldKey: string, chartType?: ChartType, field2Key?: string) => void;
  onRemoveChart: (id: string) => void;
  onUpdateChart: (id: string, updates: Partial<Pick<ChartConfig, "fieldKey" | "chartType" | "field2Key">>) => void;
}

export default function ChartDashboard({
  chartConfigs,
  available,
  rows,
  applied,
  fieldMeta,
  onChartFilter,
  onAddChart,
  onRemoveChart,
  onUpdateChart,
}: Props) {
  return (
    <Box sx={{ height: "100%", overflow: "auto", p: 1.5, display: "flex", flexWrap: "wrap", gap: 1.5, alignContent: "flex-start" }}>
      {chartConfigs.map((config) => (
        <ChartCard
          key={config.id}
          config={config}
          available={available}
          rows={rows}
          applied={applied}
          fieldMeta={fieldMeta}
          onChartFilter={onChartFilter}
          onRemove={() => onRemoveChart(config.id)}
          onUpdate={(updates) => onUpdateChart(config.id, updates)}
        />
      ))}
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "center", minWidth: 120 }}>
        <AddChartButton onAdd={onAddChart} usedFields={new Set(chartConfigs.map((c) => c.fieldKey))} fieldMeta={fieldMeta} />
      </Box>
    </Box>
  );
}
