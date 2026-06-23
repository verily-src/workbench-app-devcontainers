import { useMemo } from "react";
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
  const columnDefs = useMemo<ColDef<SampleRow>[]>(
    () => mappings.map((m) => ({
      field: m.column,
      headerName: m.label,
      width: m.type === "text" ? 200 : 120,
      type: m.type === "float" || m.type === "integer" ? "numericColumn" : undefined,
    })),
    [mappings],
  );

  const defaultColDef = useMemo<ColDef>(
    () => ({
      sortable: true,
      filter: true,
      resizable: true,
    }),
    [],
  );

  return (
    <div style={{
      flex: 1,
      width: "100%",
      height: "100%",
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
  );
}
