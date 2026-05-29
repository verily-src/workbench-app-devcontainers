import { useState } from "react";
import { Box, Button, Chip, Typography } from "@mui/material";
import DownloadIcon from "@mui/icons-material/Download";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import type { Counts, FilterState } from "../types";
import { exportUrl } from "../api";
import RunSalmonDialog from "./RunSalmonDialog";

interface Props {
  counts: Counts | null;
  filters: FilterState;
  loading: boolean;
}

export default function SummaryBar({ counts, filters, loading }: Props) {
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
      <Typography variant="h6" sx={{ fontWeight: 600, mr: 1 }}>
        Cohort Explorer
      </Typography>
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
      <Button
        variant="outlined"
        size="small"
        startIcon={<PlayArrowIcon />}
        onClick={() => setSalmonOpen(true)}
        disabled={!counts || counts.fastq_pairs === 0}
      >
        Run Salmon
      </Button>
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
