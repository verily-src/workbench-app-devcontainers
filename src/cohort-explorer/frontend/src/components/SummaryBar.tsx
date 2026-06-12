import { useState } from "react";
import { Box, Button, Chip, IconButton, Tooltip, Typography } from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import SwapHorizIcon from "@mui/icons-material/SwapHoriz";
import ViewSidebarIcon from "@mui/icons-material/ViewSidebar";
import TableRowsIcon from "@mui/icons-material/TableRows";
import type { Counts, FilterState } from "../types";
import { exportUrl } from "../api";
import RunSalmonDialog from "./RunSalmonDialog";

interface Props {
  counts: Counts | null;
  filters: FilterState;
  loading: boolean;
  onDisconnect: () => void;
  filterPaneVisible: boolean;
  gridPaneVisible: boolean;
  onToggleFilterPane: () => void;
  onToggleGridPane: () => void;
}

export default function SummaryBar({
  counts, filters, loading, onDisconnect,
  filterPaneVisible, gridPaneVisible, onToggleFilterPane, onToggleGridPane,
}: Props) {
  const [salmonOpen, setSalmonOpen] = useState(false);

  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "center",
        gap: 2,
        px: 2,
        py: 1.5,
        borderBottom: 1,
        borderColor: "divider",
        bgcolor: "grey.50",
      }}
    >
      <Typography variant="h6" sx={{ fontWeight: 600, fontFamily: "'Poppins', sans-serif" }}>
        Cohort Explorer
      </Typography>
      <Tooltip title="Change datasource">
        <IconButton size="small" onClick={onDisconnect} sx={{ ml: -1 }}>
          <SwapHorizIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      {loading ? (
        <Typography variant="body2" color="text.secondary">
          Loading...
        </Typography>
      ) : counts ? (
        <>
          <Chip
            label={`${counts.subjects.toLocaleString()} subjects`}
            color="primary"
            variant="outlined"
            size="small"
          />
          <Chip
            label={`${counts.samples.toLocaleString()} samples`}
            color="primary"
            size="small"
          />
          <Chip
            label={`${counts.fastq_pairs.toLocaleString()} FASTQ pairs`}
            variant="outlined"
            size="small"
          />
        </>
      ) : null}
      <Box sx={{ flex: 1 }} />
      <Tooltip title={filterPaneVisible ? "Hide filters" : "Show filters"}>
        <IconButton
          size="small"
          onClick={onToggleFilterPane}
          color={filterPaneVisible ? "default" : "primary"}
        >
          <ViewSidebarIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip title={gridPaneVisible ? "Hide data grid" : "Show data grid"}>
        <IconButton
          size="small"
          onClick={onToggleGridPane}
          color={gridPaneVisible ? "default" : "primary"}
        >
          <TableRowsIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip
        title={counts && counts.fastq_pairs === 0 ? "No samples with FASTQ paths in current filter" : ""}
      >
        <span>
          <Button
            variant="outlined"
            size="small"
            startIcon={<PlayArrowIcon />}
            onClick={() => setSalmonOpen(true)}
            disabled={!counts || counts.fastq_pairs === 0}
          >
            Run Salmon
          </Button>
        </span>
      </Tooltip>
      <Button
        variant="contained"
        size="small"
        startIcon={<DownloadIcon />}
        href={exportUrl(filters)}
        disabled={!counts || counts.samples === 0}
      >
        Export TSV
      </Button>
      <RunSalmonDialog
        open={salmonOpen}
        onClose={() => setSalmonOpen(false)}
        filters={filters}
      />
    </Box>
  );
}
