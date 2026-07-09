import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
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
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import type { FilterState } from "../types";
import type { SalmonDefaults, SalmonPrepareResponse, WdlInput, WorkflowConfig } from "../api";
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
  const [showFilter, setShowFilter] = useState<"required" | "all">("required");

  const [inputValues, setInputValues] = useState<Record<string, string>>({});
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
        setInputBucket(d.input_bucket_id);
        setOutputBucket(d.output_bucket_id);
        const ts = new Date().toISOString().replace(/[:\-T]/g, "").slice(0, 15);
        setOutputPath(`salmon_outputs/${ts}`);

        const vals: Record<string, string> = {};
        for (const inp of d.inputs) {
          if (inp.value != null) {
            vals[inp.short_name] = typeof inp.value === "string" ? inp.value : JSON.stringify(inp.value);
          } else if (inp.defaultValue != null) {
            vals[inp.short_name] = inp.defaultValue;
          }
        }
        setInputValues(vals);

        const transcriptome = vals["transcriptome"] ?? "";
        const transcriptMap = d.inputs.find((i) => i.short_name === "transcript_map")?.value;
        return prepareSalmon(filters, {
          transcriptome,
          transcript_map: transcriptMap as Record<string, unknown> | undefined,
        });
      })
      .then(setPrepData)
      .catch((e) => setError(e.message))
      .finally(() => setPreparing(false));
  }, [open, filters]);

  const buildConfig = (): WorkflowConfig => {
    const staticInputs: Record<string, string> = {};
    if (defaults) {
      for (const inp of defaults.inputs) {
        if (inp.source === "static" && inputValues[inp.short_name] != null) {
          staticInputs[inp.name] = inputValues[inp.short_name];
        }
      }
    }
    return {
      transcriptome: inputValues["transcriptome"],
      transcript_map: (() => {
        try { return JSON.parse(inputValues["transcript_map"] ?? "{}"); }
        catch { return undefined; }
      })(),
      input_bucket_id: inputBucket,
      output_bucket_id: outputBucket,
      output_path: outputPath,
      workflow_id: defaults?.workflow_id,
      column_mapping_uri: defaults?.column_mapping_uri,
      static_inputs: Object.keys(staticInputs).length > 0 ? staticInputs : undefined,
    };
  };

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
  const visibleInputs = (defaults?.inputs ?? []).filter(
    (inp) => showFilter === "all" || inp.isRequired || inp.source === "batch",
  );

  const renderInputValue = (inp: WdlInput) => {
    if (inp.source === "batch" && (inp.short_name === "input_files" || inp.short_name === "sample_name")) {
      return <Chip label="From cohort data" size="small" variant="outlined" />;
    }
    const val = inputValues[inp.short_name] ?? inp.defaultValue ?? "";
    const isLong = val.length > 60;
    return (
      <TextField
        value={val}
        onChange={(e) => setInputValues((prev) => ({ ...prev, [inp.short_name]: e.target.value }))}
        size="small"
        fullWidth
        multiline={isLong}
        maxRows={3}
        sx={{ "& .MuiInputBase-input": { fontFamily: "monospace", fontSize: 12 } }}
      />
    );
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

        {defaults && !preparing && !success && (
          <>
            <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}>
              <Typography variant="subtitle2">Input form</Typography>
              <ToggleButtonGroup
                value={showFilter}
                exclusive
                onChange={(_, v) => { if (v) setShowFilter(v); }}
                size="small"
              >
                <ToggleButton value="required">Required</ToggleButton>
                <ToggleButton value="all">All</ToggleButton>
              </ToggleButtonGroup>
            </Box>
            <Table size="small" sx={{ mb: 2 }}>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600, width: "35%" }}>Input Key</TableCell>
                  <TableCell sx={{ fontWeight: 600, width: "15%" }}>Type</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Values</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {visibleInputs.map((inp) => (
                  <TableRow key={inp.name}>
                    <TableCell sx={{ fontFamily: "monospace", fontSize: 12, verticalAlign: "top" }}>
                      {inp.name}
                    </TableCell>
                    <TableCell sx={{ fontSize: 12, verticalAlign: "top" }}>
                      {inp.type}
                    </TableCell>
                    <TableCell>{renderInputValue(inp)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            <Divider sx={{ my: 2 }} />

            <Typography variant="subtitle2" sx={{ mb: 1 }}>Output</Typography>
            <Box sx={{ display: "flex", gap: 2, mb: 2 }}>
              <FormControl size="small" sx={{ minWidth: 200 }}>
                <InputLabel>Input bucket</InputLabel>
                <Select value={inputBucket} label="Input bucket" onChange={(e) => setInputBucket(e.target.value)}>
                  {s3Folders.map((f) => <MenuItem key={f.id} value={f.id}>{f.name}</MenuItem>)}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 200 }}>
                <InputLabel>Output bucket</InputLabel>
                <Select value={outputBucket} label="Output bucket" onChange={(e) => setOutputBucket(e.target.value)}>
                  {s3Folders.map((f) => <MenuItem key={f.id} value={f.id}>{f.name}</MenuItem>)}
                </Select>
              </FormControl>
              <TextField
                label="Output path"
                value={outputPath}
                onChange={(e) => setOutputPath(e.target.value)}
                size="small"
                fullWidth
              />
            </Box>

            <Divider sx={{ my: 2 }} />
          </>
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
