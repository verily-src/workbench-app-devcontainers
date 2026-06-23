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
import type { ChartConfig, ChartType, FieldMeta, FilterOption, FilterState, FiltersResponse, SampleRow } from "../../types";
import { CHART_TYPES_2D, CHART_TYPES_FOR, DEFAULT_CHART_TYPE } from "../../types";
import CategoricalBarChart from "./CategoricalBarChart";
import PieChartView from "./PieChartView";
import HistogramChart from "./HistogramChart";
import BoxPlotChart from "./BoxPlotChart";
import KdeChart from "./KdeChart";
import ScatterPlot from "./ScatterPlot";
import CategoricalBoxPlot from "./CategoricalBoxPlot";
import HeatmapChart from "./HeatmapChart";

const CHART_TYPE_LABELS: Record<ChartType, string> = {
  bar: "Bar",
  pie: "Pie",
  histogram: "Histogram",
  kde: "KDE",
  boxplot: "Box Plot",
  scatter: "Scatter",
  "cat-boxplot": "Box Plot",
  heatmap: "Heatmap",
};

interface Props {
  config: ChartConfig;
  available: FiltersResponse | null;
  rows: SampleRow[];
  applied: FilterState;
  fieldMeta: FieldMeta[];
  onChartFilter: (fieldKey: string, value: string | { min: number; max: number }) => void;
  onRemove: () => void;
  onUpdate: (updates: Partial<Pick<ChartConfig, "fieldKey" | "chartType" | "field2Key">>) => void;
}

export default function ChartCard({
  config,
  available,
  rows,
  applied,
  fieldMeta,
  onChartFilter,
  onRemove,
  onUpdate,
}: Props) {
  const is2D = CHART_TYPES_2D.includes(config.chartType);
  const meta = fieldMeta.find((f) => f.key === config.fieldKey);
  const field2Meta = config.field2Key ? fieldMeta.find((f) => f.key === config.field2Key) : undefined;
  const dataType = meta?.dataType ?? "categorical";

  const compatibleTypes = is2D ? CHART_TYPES_2D : CHART_TYPES_FOR[dataType];

  const categoricalData = available
    ? (available[config.fieldKey] as FilterOption[] | undefined)
    : undefined;

  const numericValues = useMemo(() => {
    if (dataType !== "numeric") return [];
    return rows
      .map((r) => r[config.fieldKey] as number | null)
      .filter((v): v is number => v !== null);
  }, [rows, config.fieldKey, dataType]);

  const selectedValues = (applied[config.fieldKey] as string[] | undefined) ?? [];
  const appliedMin = (applied[`${config.fieldKey}_min`] as number | null) ?? null;
  const appliedMax = (applied[`${config.fieldKey}_max`] as number | null) ?? null;

  function handleFieldChange(newFieldKey: string) {
    if (is2D) {
      onUpdate({ fieldKey: newFieldKey });
      return;
    }
    const newMeta = fieldMeta.find((f) => f.key === newFieldKey);
    const newDataType = newMeta?.dataType ?? "categorical";
    if (newDataType !== dataType) {
      onUpdate({ fieldKey: newFieldKey, chartType: DEFAULT_CHART_TYPE[newDataType] });
    } else {
      onUpdate({ fieldKey: newFieldKey });
    }
  }

  function handleChartTypeChange(newType: ChartType) {
    if (CHART_TYPES_2D.includes(newType) && !config.field2Key) {
      const defaultField2 = fieldMeta.find((f) => f.key !== config.fieldKey)?.key ?? config.fieldKey;
      onUpdate({ chartType: newType, field2Key: defaultField2 });
    } else {
      onUpdate({ chartType: newType });
    }
  }

  return (
    <Paper variant="outlined" sx={{ display: "flex", flexDirection: "column", minHeight: 280, flex: "1 1 400px" }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, px: 1.5, py: 1, borderBottom: 1, borderColor: "divider", flexWrap: "wrap" }}>
        <FormControl size="small" sx={{ minWidth: 130 }}>
          <InputLabel>{is2D ? "X Field" : "Field"}</InputLabel>
          <Select
            value={config.fieldKey}
            label={is2D ? "X Field" : "Field"}
            onChange={(e) => handleFieldChange(e.target.value)}
          >
            {fieldMeta.map((f) => (
              <MenuItem key={f.key} value={f.key}>{f.label}</MenuItem>
            ))}
          </Select>
        </FormControl>

        {is2D && (
          <FormControl size="small" sx={{ minWidth: 130 }}>
            <InputLabel>Y Field</InputLabel>
            <Select
              value={config.field2Key ?? ""}
              label="Y Field"
              onChange={(e) => onUpdate({ field2Key: e.target.value })}
            >
              {fieldMeta.filter((f) => f.key !== config.fieldKey).map((f) => (
                <MenuItem key={f.key} value={f.key}>{f.label}</MenuItem>
              ))}
            </Select>
          </FormControl>
        )}

        <ToggleButtonGroup
          value={config.chartType}
          exclusive
          size="small"
          onChange={(_, v) => { if (v) handleChartTypeChange(v); }}
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
            selected={selectedValues}
            onBarClick={(v) => onChartFilter(config.fieldKey, v)}
          />
        )}
        {config.chartType === "pie" && categoricalData && (
          <PieChartView
            data={categoricalData}
            selected={selectedValues}
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
        {config.chartType === "kde" && (
          <KdeChart values={numericValues} />
        )}
        {config.chartType === "boxplot" && (
          <BoxPlotChart values={numericValues} />
        )}
        {config.chartType === "scatter" && config.field2Key && (
          <ScatterPlot
            rows={rows}
            xField={config.fieldKey}
            yField={config.field2Key}
            xLabel={meta?.label ?? config.fieldKey}
            yLabel={field2Meta?.label ?? config.field2Key}
          />
        )}
        {config.chartType === "cat-boxplot" && config.field2Key && (
          <CategoricalBoxPlot
            rows={rows}
            catField={config.fieldKey}
            numField={config.field2Key}
            catLabel={meta?.label ?? config.fieldKey}
            numLabel={field2Meta?.label ?? config.field2Key}
          />
        )}
        {config.chartType === "heatmap" && config.field2Key && (
          <HeatmapChart
            rows={rows}
            xField={config.fieldKey}
            yField={config.field2Key}
            xLabel={meta?.label ?? config.fieldKey}
            yLabel={field2Meta?.label ?? config.field2Key}
            fieldMeta={fieldMeta}
          />
        )}
      </Box>
    </Paper>
  );
}
