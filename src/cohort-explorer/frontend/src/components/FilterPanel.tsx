import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
  Slider,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import type { FilterOption, FilterState, FiltersResponse, RangeFilter } from "../types";
import { EMPTY_FILTERS } from "../types";

interface Props {
  available: FiltersResponse | null;
  filters: FilterState;
  onChange: (updated: FilterState) => void;
  dirty: boolean;
  onApply: () => void;
  onReset: () => void;
}

function CategoricalFilter({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string;
  options: FilterOption[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <Accordion defaultExpanded={label === "Tissue Type"} disableGutters>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {label}
        </Typography>
        {selected.length > 0 && (
          <Chip label={selected.length} size="small" color="primary" sx={{ ml: 1 }} />
        )}
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 0, maxHeight: 240, overflow: "auto" }}>
        {options.map((opt) => (
          <FormControlLabel
            key={opt.value}
            sx={{ display: "flex", mx: 0 }}
            control={
              <Checkbox
                size="small"
                checked={selected.includes(opt.value)}
                onChange={() => onToggle(opt.value)}
              />
            }
            label={
              <Typography variant="body2">
                {opt.label}{" "}
                <Typography component="span" variant="caption" color="text.secondary">
                  ({opt.count})
                </Typography>
              </Typography>
            }
          />
        ))}
      </AccordionDetails>
    </Accordion>
  );
}

function RangeFilterControl({
  label,
  range,
  currentMin,
  currentMax,
  onChange,
  step,
}: {
  label: string;
  range: RangeFilter;
  currentMin: number | null;
  currentMax: number | null;
  onChange: (min: number | null, max: number | null) => void;
  step: number;
}) {
  if (range.min === null || range.max === null) return null;
  const lo = currentMin ?? range.min;
  const hi = currentMax ?? range.max;

  return (
    <Accordion disableGutters>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {label}
        </Typography>
        {(currentMin !== null || currentMax !== null) && (
          <Chip label="active" size="small" color="primary" sx={{ ml: 1 }} />
        )}
      </AccordionSummary>
      <AccordionDetails>
        <Box sx={{ px: 1 }}>
          <Slider
            value={[lo, hi]}
            min={range.min}
            max={range.max}
            step={step}
            valueLabelDisplay="auto"
            onChange={(_, v) => {
              const [newMin, newMax] = v as number[];
              onChange(
                newMin === range.min ? null : newMin,
                newMax === range.max ? null : newMax,
              );
            }}
            size="small"
          />
          <Box sx={{ display: "flex", justifyContent: "space-between" }}>
            <Typography variant="caption">{range.min}</Typography>
            <Typography variant="caption">{range.max}</Typography>
          </Box>
        </Box>
      </AccordionDetails>
    </Accordion>
  );
}

export default function FilterPanel({ available, filters, onChange, dirty, onApply, onReset }: Props) {
  if (!available) return null;

  const toggleCategorical = (field: keyof FilterState, value: string) => {
    const current = filters[field] as string[];
    const updated = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    onChange({ ...filters, [field]: updated });
  };

  return (
    <Box sx={{ width: 280, flexShrink: 0, display: "flex", flexDirection: "column", borderRight: 1, borderColor: "divider" }}>
      <Box sx={{ p: 1.5, borderBottom: 1, borderColor: "divider", display: "flex", alignItems: "center", gap: 1 }}>
        <Typography variant="overline" color="text.secondary" sx={{ flex: 1 }}>
          Filters
        </Typography>
        <Button size="small" onClick={onReset} disabled={JSON.stringify(filters) === JSON.stringify(EMPTY_FILTERS)}>
          Reset
        </Button>
      </Box>

      <Box sx={{ flex: 1, overflow: "auto" }}>

      <CategoricalFilter
        label="Tissue Type"
        options={available.tissue_type}
        selected={filters.tissue_type}
        onToggle={(v) => toggleCategorical("tissue_type", v)}
      />
      <CategoricalFilter
        label="Tissue Detail"
        options={available.tissue_type_detail}
        selected={filters.tissue_type_detail}
        onToggle={(v) => toggleCategorical("tissue_type_detail", v)}
      />
      <CategoricalFilter
        label="Autolysis Score"
        options={available.autolysis_score}
        selected={filters.autolysis_score}
        onToggle={(v) => toggleCategorical("autolysis_score", v)}
      />
      <CategoricalFilter
        label="Material Type"
        options={available.current_material_type}
        selected={filters.current_material_type}
        onToggle={(v) => toggleCategorical("current_material_type", v)}
      />
      <CategoricalFilter
        label="Collection Kit"
        options={available.sample_collection_kit}
        selected={filters.sample_collection_kit}
        onToggle={(v) => toggleCategorical("sample_collection_kit", v)}
      />

      <RangeFilterControl
        label="RIN Number"
        range={available.rin_number}
        currentMin={filters.rin_number_min}
        currentMax={filters.rin_number_max}
        onChange={(min, max) =>
          onChange({ ...filters, rin_number_min: min, rin_number_max: max })
        }
        step={0.1}
      />
      <RangeFilterControl
        label="Ischemic Time (min)"
        range={available.total_ischemic_time}
        currentMin={filters.total_ischemic_time_min}
        currentMax={filters.total_ischemic_time_max}
        onChange={(min, max) =>
          onChange({
            ...filters,
            total_ischemic_time_min: min,
            total_ischemic_time_max: max,
          })
        }
        step={10}
      />
      <RangeFilterControl
        label="PAXgene Time (min)"
        range={available.paxgene_time}
        currentMin={filters.paxgene_time_min}
        currentMax={filters.paxgene_time_max}
        onChange={(min, max) =>
          onChange({ ...filters, paxgene_time_min: min, paxgene_time_max: max })
        }
        step={10}
      />
      </Box>

      <Box sx={{ p: 1.5, borderTop: 1, borderColor: "divider" }}>
        <Button
          variant={dirty ? "contained" : "outlined"}
          fullWidth
          onClick={onApply}
          disabled={!dirty}
        >
          Apply Filters
        </Button>
      </Box>
    </Box>
  );
}
