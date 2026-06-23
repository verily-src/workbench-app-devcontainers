import { useEffect, useRef, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
  InputAdornment,
  Slider,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import SearchIcon from "@mui/icons-material/Search";
import type { ColumnMapping } from "../api";
import type { FilterOption, FilterState, FiltersResponse, RangeFilter } from "../types";

interface Props {
  available: FiltersResponse | null;
  filters: FilterState;
  mappings: ColumnMapping[];
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
  searchable = false,
}: {
  label: string;
  options: FilterOption[];
  selected: string[];
  onToggle: (value: string) => void;
  searchable?: boolean;
}) {
  const [search, setSearch] = useState("");
  const filtered = searchable && search
    ? options.filter((opt) => opt.label.toLowerCase().includes(search.toLowerCase()))
    : options;

  return (
    <Accordion disableGutters>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {label}
        </Typography>
        {selected.length > 0 && (
          <Chip label={selected.length} size="small" color="primary" sx={{ ml: 1 }} />
        )}
      </AccordionSummary>
      <AccordionDetails sx={{ pt: 0, display: "flex", flexDirection: "column", maxHeight: 300, overflow: "hidden" }}>
        {searchable && (
          <TextField
            size="small"
            placeholder={`Search ${label.toLowerCase()}...`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            slotProps={{
              input: {
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon fontSize="small" color="action" />
                  </InputAdornment>
                ),
              },
            }}
            sx={{ mb: 1, flexShrink: 0 }}
          />
        )}
        <Box sx={{ overflow: "auto", flex: 1 }}>
          {filtered.map((opt) => (
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
          {searchable && search && filtered.length === 0 && (
            <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
              No matches
            </Typography>
          )}
        </Box>
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

function isFiltersEmpty(filters: FilterState): boolean {
  return Object.values(filters).every((v) =>
    Array.isArray(v) ? v.length === 0 : v === null,
  );
}

export default function FilterPanel({ available, filters, mappings, onChange, dirty, onApply, onReset }: Props) {
  const globalRanges = useRef<Record<string, RangeFilter>>({});
  const rangeKeys = mappings.filter((m) => m.filter === "range").map((m) => m.column);

  useEffect(() => {
    if (!available) return;
    for (const key of rangeKeys) {
      const val = available[key];
      if (!(key in globalRanges.current) && val && "min" in val && val.min !== null) {
        globalRanges.current[key] = { ...val };
      }
    }
  }, [available, rangeKeys]);

  if (!available) return null;

  const rangeFor = (key: string): RangeFilter =>
    globalRanges.current[key] ?? (available[key] as RangeFilter) ?? { min: null, max: null };

  const toggleCategorical = (field: string, value: string) => {
    const current = (filters[field] as string[]) ?? [];
    const updated = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    onChange({ ...filters, [field]: updated });
  };

  const categoricalMappings = mappings.filter((m) => m.filter === "categorical");
  const rangeMappings = mappings.filter((m) => m.filter === "range");

  return (
    <Box sx={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <Box sx={{ p: 1.5, borderBottom: 1, borderColor: "divider", display: "flex", alignItems: "center", gap: 1 }}>
        <Typography variant="overline" color="text.secondary" sx={{ flex: 1 }}>
          Filters
        </Typography>
        <Button size="small" onClick={onReset} disabled={isFiltersEmpty(filters)}>
          Reset
        </Button>
      </Box>

      <Box sx={{ flex: 1, overflow: "auto" }}>
        {categoricalMappings.map((m) => {
          const options = (available[m.column] as FilterOption[]) ?? [];
          return (
            <CategoricalFilter
              key={m.column}
              label={m.label}
              options={options}
              selected={(filters[m.column] as string[]) ?? []}
              onToggle={(v) => toggleCategorical(m.column, v)}
              searchable={options.length > 10}
            />
          );
        })}

        {rangeMappings.map((m) => (
          <RangeFilterControl
            key={m.column}
            label={m.label}
            range={rangeFor(m.column)}
            currentMin={(filters[`${m.column}_min`] as number | null) ?? null}
            currentMax={(filters[`${m.column}_max`] as number | null) ?? null}
            onChange={(min, max) =>
              onChange({
                ...filters,
                [`${m.column}_min`]: min,
                [`${m.column}_max`]: max,
              })
            }
            step={m.type === "integer" ? 1 : 0.1}
          />
        ))}
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
