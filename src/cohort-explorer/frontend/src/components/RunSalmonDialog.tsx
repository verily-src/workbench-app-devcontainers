import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import type { FilterState } from "../types";
import type { SalmonPrepareResponse } from "../api";
import { prepareSalmon, submitSalmon, checkSalmonStatus } from "../api";

interface Props {
  open: boolean;
  onClose: () => void;
  filters: FilterState;
}

export default function RunSalmonDialog({ open, onClose, filters }: Props) {
  const [preparing, setPreparing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [prepData, setPrepData] = useState<SalmonPrepareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setPreparing(true);
    setError(null);
    setSuccess(null);
    setPrepData(null);

    prepareSalmon(filters)
      .then(setPrepData)
      .catch((e) => setError(e.message))
      .finally(() => setPreparing(false));
  }, [open, filters]);

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const result = await submitSalmon(filters);
      setSuccess(`Submitting ${result.samples_submitted} samples... Job ID: ${result.job_id}`);

      const poll = setInterval(async () => {
        try {
          const status = await checkSalmonStatus(result.job_id);
          if (status.status === "submitted") {
            clearInterval(poll);
            setSuccess(`Submitted successfully. Job ID: ${result.job_id}`);
          } else if (status.status === "failed") {
            clearInterval(poll);
            setError(`Submission failed: ${status.error}`);
            setSuccess(null);
          }
        } catch {
          // still polling
        }
      }, 3000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Submission failed");
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    setError(null);
    setSuccess(null);
    setPrepData(null);
    onClose();
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>Run Salmon Quantification</DialogTitle>
      <DialogContent>
        {preparing && (
          <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
            <CircularProgress />
          </Box>
        )}

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {success && <Alert severity="success" sx={{ mb: 2 }}>{success}</Alert>}

        {prepData && !success && (
          <>
            <Typography variant="body1" sx={{ mb: 2 }}>
              <strong>{prepData.samples_with_fastq}</strong> samples have FASTQ
              data and will be submitted as individual Salmon jobs.
            </Typography>

            {prepData.samples_without_fastq > 0 && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                {prepData.samples_without_fastq} samples have no FASTQ paths and
                will be skipped.
              </Alert>
            )}

            {prepData.samples_with_fastq === 0 && (
              <Alert severity="error" sx={{ mb: 2 }}>
                No samples in the current filter have FASTQ paths. Cannot submit.
              </Alert>
            )}

            {prepData.preview.length > 0 && (
              <>
                <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
                  Preview (first {prepData.preview.length} of {prepData.samples_with_fastq})
                </Typography>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Sample</TableCell>
                      <TableCell>FASTQ Files</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {prepData.preview.map((row) => (
                      <TableRow key={row.sample_name}>
                        <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>
                          {row.sample_name}
                        </TableCell>
                        <TableCell sx={{ fontFamily: "monospace", fontSize: 11, maxWidth: 400, overflow: "hidden", textOverflow: "ellipsis" }}>
                          {row.input_files}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </>
            )}
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>
          {success ? "Close" : "Cancel"}
        </Button>
        {!success && (
          <Button
            variant="contained"
            onClick={handleSubmit}
            disabled={submitting || preparing || !prepData || prepData.samples_with_fastq === 0}
          >
            {submitting ? "Submitting..." : `Submit ${prepData?.samples_with_fastq ?? 0} Jobs`}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
