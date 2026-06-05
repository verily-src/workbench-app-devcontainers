import { useMemo } from "react";
import {
  Box,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import type { ChartConfig, FilterState, FiltersResponse, SampleRow, ChartType, FilterOption } from "../../types";
import { CHART_TYPES_FOR, DEFAULT_CHART_TYPE, FIELD_META } from "../../types";
import CategoricalBarChart from "./CategoricalBarChart";
import PieChartView from "./PieChartView";
import HistogramChart from "./HistogramChart";
import BoxPlotChart from "./BoxPlotChart";

const CHART_TYPE_LABELS: Record<ChartType, string> = {
  bar: "Bar",
  pie: "Pie",
  histogram: "Histogram",
  boxplot: "Box Plot",
};

interface Props {
  config: ChartConfig;
  available: FiltersResponse | null;
  rows: SampleRow[];
  applied: FilterState;
  onChartFilter: (fieldKey: string, value: string | { min: number; max: number }) => void;
  onRemove: () => void;
  onUpdate: (updates: Partial<Pick<ChartConfig, "fieldKey" | "chartType">>) => void;
}

export default function ChartCard({
  config,
  available,
  rows,
  applied,
  onChartFilter,
  onRemove,
  onUpdate,
}: Props) {
  const fieldMeta = FIELD_META.find((f) => f.key === config.fieldKey);
  const dataType = fieldMeta?.dataType ?? "categorical";
  const compatibleTypes = CHART_TYPES_FOR[dataType];

  const categoricalData = available
    ? (available as unknown as Record<string, FilterOption[]>)[config.fieldKey]
    : undefined;

  const numericValues = useMemo(() => {
    if (dataType !== "numeric") return [];
    const key = config.fieldKey as keyof SampleRow;
    return rows
      .map((r) => r[key] as number | null)
      .filter((v): v is number => v !== null);
  }, [rows, config.fieldKey, dataType]);

  const selectedValues = (applied as unknown as Record<string, string[]>)[config.fieldKey] as string[] | undefined;

  const appliedMin = (applied as unknown as Record<string, number | null>)[`${config.fieldKey}_min`] ?? null;
  const appliedMax = (applied as unknown as Record<string, number | null>)[`${config.fieldKey}_max`] ?? null;

  function handleFieldChange(newFieldKey: string) {
    const newMeta = FIELD_META.find((f) => f.key === newFieldKey);
    const newDataType = newMeta?.dataType ?? "categorical";
    if (newDataType !== dataType) {
      onUpdate({ fieldKey: newFieldKey, chartType: DEFAULT_CHART_TYPE[newDataType] });
    } else {
      onUpdate({ fieldKey: newFieldKey });
    }
  }

  return (
    <Paper variant="outlined" sx={{ display: "flex", flexDirection: "column", minHeight: 280, flex: "1 1 400px" }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, px: 1.5, py: 1, borderBottom: 1, borderColor: "divider" }}>
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>Field</InputLabel>
          <Select
            value={config.fieldKey}
            label="Field"
            onChange={(e) => handleFieldChange(e.target.value)}
          >
            {FIELD_META.map((f) => (
              <MenuItem key={f.key} value={f.key}>{f.label}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <ToggleButtonGroup
          value={config.chartType}
          exclusive
          size="small"
          onChange={(_, v) => { if (v) onUpdate({ chartType: v }); }}
        >
          {compatibleTypes.map((t) => (
            <ToggleButton key={t} value={t} sx={{ textTransform: "none", px: 1.5 }}>
              {CHART_TYPE_LABELS[t]}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>
        <Box sx={{ flex: 1 }} />
        <Tooltip title="Remove chart">
          <IconButton size="small" onClick={onRemove}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>

      <Box sx={{ flex: 1, minHeight: 0, display: "flex", overflow: "hidden" }}>
        {config.chartType === "bar" && categoricalData && (
          <CategoricalBarChart
            data={categoricalData}
            selected={selectedValues ?? []}
            onBarClick={(v) => onChartFilter(config.fieldKey, v)}
          />
        )}
        {config.chartType === "pie" && categoricalData && (
          <PieChartView
            data={categoricalData}
            selected={selectedValues ?? []}
            onSliceClick={(v) => onChartFilter(config.fieldKey, v)}
          />
        )}
        {config.chartType === "histogram" && (
          <HistogramChart
            values={numericValues}
            appliedMin={appliedMin}
            appliedMax={appliedMax}
            onBinClick={(min, max) => onChartFilter(config.fieldKey, { min, max })}
          />
        )}
        {config.chartType === "boxplot" && (
          <BoxPlotChart values={numericValues} />
        )}
      </Box>
    </Paper>
  );
}
