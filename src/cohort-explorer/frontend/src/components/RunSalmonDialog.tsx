import { useEffect, useState } from "react";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import type { FilterState } from "../types";
import type { SalmonDefaults, SalmonPrepareResponse, WorkflowConfig } from "../api";
import { checkSalmonStatus, fetchSalmonDefaults, prepareSalmon, submitSalmon } from "../api";

interface Props {
  open: boolean;
  onClose: () => void;
  filters: FilterState;
}

export default function RunSalmonDialog({ open, onClose, filters }: Props) {
  const [defaults, setDefaults] = useState<SalmonDefaults | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [prepData, setPrepData] = useState<SalmonPrepareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [transcriptome, setTranscriptome] = useState("");
  const [inputBucket, setInputBucket] = useState("");
  const [outputBucket, setOutputBucket] = useState("");
  const [outputPath, setOutputPath] = useState("");

  useEffect(() => {
    if (!open) return;
    setPreparing(true);
    setError(null);
    setSuccess(null);
    setPrepData(null);

    fetchSalmonDefaults()
      .then((d) => {
        setDefaults(d);
        setTranscriptome(d.transcriptome);
        setInputBucket(d.input_bucket_id);
        setOutputBucket(d.output_bucket_id);
        const ts = new Date().toISOString().replace(/[:\-T]/g, "").slice(0, 15);
        setOutputPath(`salmon_outputs/${ts}`);
        return prepareSalmon(filters, { transcriptome: d.transcriptome, transcript_map: d.transcript_map });
      })
      .then(setPrepData)
      .catch((e) => setError(e.message))
      .finally(() => setPreparing(false));
  }, [open, filters]);

  const buildConfig = (): WorkflowConfig => ({
    transcriptome,
    transcript_map: defaults?.transcript_map,
    input_bucket_id: inputBucket,
    output_bucket_id: outputBucket,
    output_path: outputPath,
    workflow_id: defaults?.workflow_id,
    column_mapping_uri: defaults?.column_mapping_uri,
  });

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const result = await submitSalmon(filters, buildConfig());
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

  const s3Folders = defaults?.s3_folders ?? [];

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

        {defaults && !preparing && !success && (
          <Accordion variant="outlined" sx={{ mb: 2 }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle2">Configuration</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <TextField
                  label="Transcriptome"
                  value={transcriptome}
                  onChange={(e) => setTranscriptome(e.target.value)}
                  size="small"
                  fullWidth
                />
                <FormControl size="small" fullWidth>
                  <InputLabel>Input bucket</InputLabel>
                  <Select
                    value={inputBucket}
                    label="Input bucket"
                    onChange={(e) => setInputBucket(e.target.value)}
                  >
                    {s3Folders.map((f) => (
                      <MenuItem key={f.id} value={f.id}>{f.name}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <FormControl size="small" fullWidth>
                  <InputLabel>Output bucket</InputLabel>
                  <Select
                    value={outputBucket}
                    label="Output bucket"
                    onChange={(e) => setOutputBucket(e.target.value)}
                  >
                    {s3Folders.map((f) => (
                      <MenuItem key={f.id} value={f.id}>{f.name}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  label="Output path"
                  value={outputPath}
                  onChange={(e) => setOutputPath(e.target.value)}
                  size="small"
                  fullWidth
                  helperText="Path prefix within the output bucket"
                />
              </Box>
            </AccordionDetails>
          </Accordion>
        )}

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
