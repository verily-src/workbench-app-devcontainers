import { Autocomplete, TextField } from "@mui/material";
import type { AuroraTable } from "../api";

// Rendering every match as a DOM node stops scaling long before a dataset
// like "one table per UKB field" (~10k tables) does. Capping the rendered
// list keeps the dropdown responsive without pulling in a virtualized-list
// dependency; the search itself still runs over the full in-memory list.
const MAX_RESULTS = 200;

interface Props {
  label: string;
  tables: AuroraTable[];
  value: string;
  onChange: (tableName: string) => void;
  disabledNames?: string[];
  disabled?: boolean;
}

export default function TableSelect({ label, tables, value, onChange, disabledNames, disabled }: Props) {
  const selected = tables.find((t) => t.name === value) ?? null;

  return (
    <Autocomplete
      size="small"
      fullWidth
      disabled={disabled}
      options={tables}
      value={selected}
      onChange={(_, newVal) => onChange(newVal?.name ?? "")}
      getOptionLabel={(t) => t.name}
      isOptionEqualToValue={(a, b) => a.name === b.name}
      getOptionDisabled={(t) => !!disabledNames?.includes(t.name)}
      filterOptions={(options, state) => {
        const input = state.inputValue.trim().toLowerCase();
        const filtered = input
          ? options.filter((t) => t.name.toLowerCase().includes(input))
          : options;
        return filtered.slice(0, MAX_RESULTS);
      }}
      renderOption={(props, t) => {
        const { key, ...rest } = props as typeof props & { key?: string };
        return (
          <li key={key ?? t.name} {...rest}>
            {t.name}
            <span style={{ opacity: 0.6, marginLeft: 6 }}>({t.type})</span>
          </li>
        );
      }}
      renderInput={(params) => (
        <TextField {...params} label={label} placeholder="Search tables…" />
      )}
      noOptionsText={tables.length === 0 ? "No tables found" : "No matching tables"}
    />
  );
}
