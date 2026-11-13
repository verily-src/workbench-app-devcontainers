import { useMemo, useState } from "react";
import { Box, Button, Checkbox, FormControlLabel, Menu, MenuItem } from "@mui/material";
import { AgGridReact } from "ag-grid-react";
import { AllCommunityModule, type ColDef, ModuleRegistry } from "ag-grid-community";
import type { ColumnMapping } from "../api";
import type { SampleRow } from "../types";

ModuleRegistry.registerModules([AllCommunityModule]);

interface Props {
  rows: SampleRow[];
  loading: boolean;
  error?: string | null;
  mappings: ColumnMapping[];
}

export default function DataGrid({ rows, loading, error, mappings }: Props) {
  const [hiddenColumns, setHiddenColumns] = useState<Set<string>>(new Set());
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);

  const toggleColumn = (column: string) => {
    setHiddenColumns((prev) => {
      const next = new Set(prev);
      if (next.has(column)) next.delete(column);
      else next.add(column);
      return next;
    });
  };

  const columnDefs = useMemo<ColDef<SampleRow>[]>(
    () => mappings.map((m) => ({
      field: m.column,
      tooltipField: m.column,
      headerName: m.label,
      width: m.type === "text" ? 200 : 120,
      type: m.type === "float" || m.type === "integer" ? "numericColumn" : undefined,
      hide: hiddenColumns.has(m.column),
    })),
    [mappings, hiddenColumns],
  );

  const defaultColDef = useMemo<ColDef>(
    () => ({
      sortable: true,
      filter: true,
      resizable: true,
    }),
    [],
  );

  const visibleCount = mappings.length - mappings.filter((m) => hiddenColumns.has(m.column)).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", width: "100%", height: "100%" }}>
      <Box sx={{ display: "flex", justifyContent: "flex-end", px: 1, py: 0.5 }}>
        <Button size="small" onClick={(e) => setMenuAnchor(e.currentTarget)}>
          Columns ({visibleCount}/{mappings.length})
        </Button>
        <Menu anchorEl={menuAnchor} open={menuAnchor !== null} onClose={() => setMenuAnchor(null)}>
          {mappings.map((m) => (
            <MenuItem key={m.column} dense disableRipple>
              <FormControlLabel
                label={m.label}
                control={
                  <Checkbox
                    size="small"
                    checked={!hiddenColumns.has(m.column)}
                    onChange={() => toggleColumn(m.column)}
                  />
                }
              />
            </MenuItem>
          ))}
        </Menu>
      </Box>
      <div style={{
        flex: 1,
        minHeight: 0,
        width: "100%",
        // @ts-expect-error ag-grid CSS custom properties
        "--ag-active-color": "#087a6a",
        "--ag-selected-row-background-color": "rgba(8,122,106,0.08)",
        "--ag-row-hover-color": "rgba(8,122,106,0.04)",
        "--ag-header-background-color": "#F5F6F7",
      }}>
        <AgGridReact<SampleRow>
          rowData={rows}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          tooltipShowDelay={300}
          loading={loading}
          overlayNoRowsTemplate={
            error
              ? "Failed to load data"
              : "No matching samples — adjust your filters"
          }
          enableCellTextSelection
          animateRows={false}
          pagination
          paginationAutoPageSize
        />
      </div>
    </div>
  );
}
