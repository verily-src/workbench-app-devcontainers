import { useState } from "react";
import { Button, ListItemText, Menu, MenuItem } from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import { FIELD_META } from "../../types";

interface Props {
  onAdd: (fieldKey: string) => void;
}

export default function AddChartButton({ onAdd }: Props) {
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null);

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
      >
        {FIELD_META.map((f) => (
          <MenuItem
            key={f.key}
            onClick={() => {
              onAdd(f.key);
              setAnchorEl(null);
            }}
          >
            <ListItemText
              primary={f.label}
              secondary={f.dataType}
              slotProps={{ secondary: { variant: "caption" } }}
            />
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}
