import { useCallback, useEffect, useState } from "react";
import {
  Box, Button, Chip, Divider, IconButton, ListItemIcon, ListItemText,
  Menu, MenuItem, Tooltip, Typography,
} from "@mui/material";
import BookmarkIcon from "@mui/icons-material/Bookmark";
import BookmarkBorderIcon from "@mui/icons-material/BookmarkBorder";
import DeleteIcon from "@mui/icons-material/Delete";
import DownloadIcon from "@mui/icons-material/Download";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import SaveIcon from "@mui/icons-material/Save";
import SwapHorizIcon from "@mui/icons-material/SwapHoriz";
import ViewSidebarIcon from "@mui/icons-material/ViewSidebar";
import TableRowsIcon from "@mui/icons-material/TableRows";
import type { CohortSummary } from "../api";
import { deleteCohort, exportUrl, listCohorts } from "../api";
import type { Counts, FilterState } from "../types";
import RunSalmonDialog from "./RunSalmonDialog";
import SaveCohortDialog from "./SaveCohortDialog";

interface Props {
  counts: Counts | null;
  filters: FilterState;
  loading: boolean;
  onDisconnect: () => void;
  filterPaneVisible: boolean;
  gridPaneVisible: boolean;
  onToggleFilterPane: () => void;
  onToggleGridPane: () => void;
  activeCohort: string | null;
  datasource: string;
  onLoadCohort: (name: string) => void;
  onCohortSaved: (name: string) => void;
}

export default function SummaryBar({
  counts, filters, loading, onDisconnect,
  filterPaneVisible, gridPaneVisible, onToggleFilterPane, onToggleGridPane,
  activeCohort, datasource, onLoadCohort, onCohortSaved,
}: Props) {
  const [salmonOpen, setSalmonOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [cohortAnchor, setCohortAnchor] = useState<null | HTMLElement>(null);
  const [cohorts, setCohorts] = useState<CohortSummary[]>([]);

  const refreshCohorts = useCallback(async () => {
    try {
      setCohorts(await listCohorts(datasource));
    } catch { /* ignore */ }
  }, [datasource]);

  useEffect(() => { refreshCohorts(); }, [refreshCohorts]);

  const handleDelete = async (name: string) => {
    if (!window.confirm(`Delete cohort "${name}"?`)) return;
    try {
      await deleteCohort(name);
      setCohorts((prev) => prev.filter((c) => c.name !== name));
    } catch { /* ignore */ }
  };

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
      {activeCohort && (
        <Chip
          icon={<BookmarkIcon />}
          label={activeCohort}
          size="small"
          color="primary"
          variant="outlined"
        />
      )}
      {loading ? (
        <Typography variant="body2" color="text.secondary">
          Loading...
        </Typography>
      ) : counts ? (
        <>
          {counts.subjects != null && (
            <Chip
              label={`${counts.subjects.toLocaleString()} subjects`}
              color="primary"
              variant="outlined"
              size="small"
            />
          )}
          <Chip
            label={`${counts.samples.toLocaleString()} samples`}
            color="primary"
            size="small"
          />
          {counts.fastq_pairs != null && (
            <Chip
              label={`${counts.fastq_pairs.toLocaleString()} FASTQ pairs`}
              variant="outlined"
              size="small"
            />
          )}
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
      <Button
        variant="outlined"
        size="small"
        startIcon={<SaveIcon />}
        onClick={() => setSaveOpen(true)}
        disabled={!counts || counts.samples === 0}
      >
        Save
      </Button>
      <Button
        variant="outlined"
        size="small"
        startIcon={<BookmarkBorderIcon />}
        onClick={(e) => { setCohortAnchor(e.currentTarget); refreshCohorts(); }}
      >
        Cohorts
      </Button>
      <Menu
        anchorEl={cohortAnchor}
        open={Boolean(cohortAnchor)}
        onClose={() => setCohortAnchor(null)}
        slotProps={{ paper: { sx: { minWidth: 280, maxHeight: 400 } } }}
      >
        {cohorts.length === 0 ? (
          <MenuItem disabled>
            <ListItemText primary="No saved cohorts" />
          </MenuItem>
        ) : (
          cohorts.map((c) => (
            <MenuItem
              key={c.name}
              selected={c.name === activeCohort}
              onClick={() => { onLoadCohort(c.name); setCohortAnchor(null); }}
            >
              <ListItemText
                primary={c.name}
                secondary={`${c.sampleCount.toLocaleString()} samples`}
              />
              <ListItemIcon sx={{ minWidth: "auto", ml: 1 }}>
                <IconButton
                  size="small"
                  onClick={(e) => { e.stopPropagation(); handleDelete(c.name); }}
                >
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </ListItemIcon>
            </MenuItem>
          ))
        )}
        {cohorts.length > 0 && <Divider />}
        <MenuItem onClick={() => { setSaveOpen(true); setCohortAnchor(null); }}>
          <ListItemIcon><SaveIcon fontSize="small" /></ListItemIcon>
          <ListItemText primary="Save current as..." />
        </MenuItem>
      </Menu>
      <Tooltip
        title={counts && (counts.fastq_pairs ?? 0) === 0 ? "No samples with FASTQ paths in current filter" : ""}
      >
        <span>
          <Button
            variant="outlined"
            size="small"
            startIcon={<PlayArrowIcon />}
            onClick={() => setSalmonOpen(true)}
            disabled={!counts || (counts.fastq_pairs ?? 0) === 0}
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
      <SaveCohortDialog
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        filters={filters}
        sampleCount={counts?.samples ?? 0}
        datasource={datasource}
        onSaved={(name) => { onCohortSaved(name); refreshCohorts(); }}
      />
    </Box>
  );
}
