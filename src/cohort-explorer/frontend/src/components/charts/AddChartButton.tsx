import { useState } from "react";
import { Button, Divider, ListItemText, ListSubheader, Menu, MenuItem } from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import type { ChartType, FieldMeta } from "../../types";

interface Props {
  onAdd: (fieldKey: string, chartType?: ChartType, field2Key?: string) => void;
  usedFields: Set<string>;
  fieldMeta: FieldMeta[];
}

export default function AddChartButton({ onAdd, usedFields, fieldMeta }: Props) {
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);

  const categoricalFields = fieldMeta.filter((f) => f.dataType === "categorical");
  const numericFields = fieldMeta.filter((f) => f.dataType === "numeric");

  const firstNumeric = numericFields[0];
  const secondNumeric = numericFields[1];
  const firstCategorical = categoricalFields[0];
  const secondCategorical = categoricalFields[1];

  return (
    <>
      <Button
        size="small"
        variant="outlined"
        startIcon={<AddIcon />}
        onClick={(e) => setAnchorEl(e.currentTarget)}
      >
        Add Chart
      </Button>
      <Menu
        anchorEl={anchorEl}
        open={Boolean(anchorEl)}
        onClose={() => setAnchorEl(null)}
        slotProps={{ paper: { sx: { maxHeight: 400 } } }}
      >
        {categoricalFields.length > 0 && <ListSubheader>Categorical</ListSubheader>}
        {categoricalFields.map((f) => (
          <MenuItem key={f.key} disabled={usedFields.has(f.key)} onClick={() => { onAdd(f.key); setAnchorEl(null); }}>
            <ListItemText primary={f.label} />
          </MenuItem>
        ))}
        {numericFields.length > 0 && <ListSubheader>Numeric</ListSubheader>}
        {numericFields.map((f) => (
          <MenuItem key={f.key} disabled={usedFields.has(f.key)} onClick={() => { onAdd(f.key); setAnchorEl(null); }}>
            <ListItemText primary={f.label} />
          </MenuItem>
        ))}
        {(firstNumeric || firstCategorical) && <Divider />}
        {(firstNumeric || firstCategorical) && <ListSubheader>2D Charts</ListSubheader>}
        {firstNumeric && secondNumeric && (
          <MenuItem onClick={() => { onAdd(firstNumeric.key, "scatter", secondNumeric.key); setAnchorEl(null); }}>
            <ListItemText primary="Scatter Plot" secondary={`${firstNumeric.label} × ${secondNumeric.label}`} slotProps={{ secondary: { variant: "caption" } }} />
          </MenuItem>
        )}
        {firstCategorical && firstNumeric && (
          <MenuItem onClick={() => { onAdd(firstCategorical.key, "cat-boxplot", firstNumeric.key); setAnchorEl(null); }}>
            <ListItemText primary="Box Plot by Category" secondary={`${firstCategorical.label} × ${firstNumeric.label}`} slotProps={{ secondary: { variant: "caption" } }} />
          </MenuItem>
        )}
        {firstCategorical && secondCategorical && (
          <MenuItem onClick={() => { onAdd(firstCategorical.key, "heatmap", secondCategorical.key); setAnchorEl(null); }}>
            <ListItemText primary="Heatmap" secondary={`${firstCategorical.label} × ${secondCategorical.label}`} slotProps={{ secondary: { variant: "caption" } }} />
          </MenuItem>
        )}
      </Menu>
    </>
  );
}
