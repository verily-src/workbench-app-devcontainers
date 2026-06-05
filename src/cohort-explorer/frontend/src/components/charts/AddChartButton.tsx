import { useState } from "react";
import { Button, Divider, ListItemText, ListSubheader, Menu, MenuItem } from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import type { ChartType } from "../../types";
import { FIELD_META } from "../../types";

interface Props {
  onAdd: (fieldKey: string, chartType?: ChartType, field2Key?: string) => void;
}

export default function AddChartButton({ onAdd }: Props) {
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);

  const categoricalFields = FIELD_META.filter((f) => f.dataType === "categorical");
  const numericFields = FIELD_META.filter((f) => f.dataType === "numeric");

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
        <ListSubheader>Categorical</ListSubheader>
        {categoricalFields.map((f) => (
          <MenuItem key={f.key} onClick={() => { onAdd(f.key); setAnchorEl(null); }}>
            <ListItemText primary={f.label} />
          </MenuItem>
        ))}
        <ListSubheader>Numeric</ListSubheader>
        {numericFields.map((f) => (
          <MenuItem key={f.key} onClick={() => { onAdd(f.key); setAnchorEl(null); }}>
            <ListItemText primary={f.label} />
          </MenuItem>
        ))}
        <Divider />
        <ListSubheader>2D Charts</ListSubheader>
        <MenuItem onClick={() => { onAdd("rin_number", "scatter", "total_ischemic_time"); setAnchorEl(null); }}>
          <ListItemText primary="Scatter Plot" secondary="Pick two numeric fields" slotProps={{ secondary: { variant: "caption" } }} />
        </MenuItem>
        <MenuItem onClick={() => { onAdd("tissue_type", "cat-boxplot", "rin_number"); setAnchorEl(null); }}>
          <ListItemText primary="Box Plot by Category" secondary="Categorical × Numeric" slotProps={{ secondary: { variant: "caption" } }} />
        </MenuItem>
        <MenuItem onClick={() => { onAdd("tissue_type", "heatmap", "current_material_type"); setAnchorEl(null); }}>
          <ListItemText primary="Heatmap" secondary="Categorical × Categorical" slotProps={{ secondary: { variant: "caption" } }} />
        </MenuItem>
      </Menu>
    </>
  );
}
