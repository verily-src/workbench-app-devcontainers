import { useMemo } from "react";
import { AgGridReact } from "ag-grid-react";
import { AllCommunityModule, type ColDef, ModuleRegistry } from "ag-grid-community";
import type { SampleRow } from "../types";

ModuleRegistry.registerModules([AllCommunityModule]);

interface Props {
  rows: SampleRow[];
  loading: boolean;
  error?: string | null;
}

export default function DataGrid({ rows, loading, error }: Props) {
  const columnDefs = useMemo<ColDef<SampleRow>[]>(
    () => [
      { field: "subject_id", headerName: "Subject", width: 130, pinned: "left" },
      { field: "gtex_sample_id", headerName: "Sample ID", width: 220 },
      { field: "tissue_type", headerName: "Tissue", width: 150 },
      { field: "tissue_type_detail", headerName: "Tissue Detail", width: 220 },
      { field: "rin_number", headerName: "RIN", width: 80, type: "numericColumn" },
      {
        field: "total_ischemic_time",
        headerName: "Ischemic (min)",
        width: 120,
        type: "numericColumn",
      },
      { field: "autolysis_score", headerName: "Autolysis", width: 100 },
      { field: "current_material_type", headerName: "Material", width: 180 },
      { field: "specimen_id", headerName: "Specimen", width: 160 },
      { field: "srr_id", headerName: "SRR ID", width: 120 },
      { field: "fastq1_path", headerName: "FASTQ R1", width: 300 },
      { field: "fastq2_path", headerName: "FASTQ R2", width: 300 },
      { field: "tissue_location", headerName: "Location", width: 160 },
      { field: "bss_collection_site", headerName: "BSS Site", width: 100 },
      { field: "paxgene_time", headerName: "PAXgene (min)", width: 120, type: "numericColumn" },
      { field: "original_material_type", headerName: "Orig. Material", width: 180 },
    ],
    [],
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
