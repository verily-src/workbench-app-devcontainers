import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Autocomplete,
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
import type {
  ColumnMapping,
  S3Folder,
  WdlInput,
  Workflow,
  WorkflowInputBinding,
  WorkflowPrepareResponse,
} from "../api";
import {
  checkWorkflowJobStatus,
  getWorkflowInputs,
  listWorkflows,
  prepareWorkflow,
  submitWorkflow,
} from "../api";

interface Props {
  open: boolean;
  onClose: () => void;
  filters: FilterState;
  mappings: ColumnMapping[];
}

const COMPLEX_TYPE_PATTERN = /^(Array|Map|Pair|Object)/i;

function isComplexType(type: string): boolean {
  return COMPLEX_TYPE_PATTERN.test(type.replace(/\?$/, ""));
}

function validateStaticValue(value: string, type: string): string | null {
  if (!value || !isComplexType(type)) return null;
  try {
    JSON.parse(value);
    return null;
  } catch {
    return "Value must be valid JSON (e.g. [\"s3://a\", \"s3://b\"])";
  }
}

export default function RunWorkflowDialog({ open, onClose, filters, mappings }: Props) {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [s3Folders, setS3Folders] = useState<S3Folder[]>([]);
  const [selectedWorkflow, setSelectedWorkflow] = useState<string>("");
  const [wdlInputs, setWdlInputs] = useState<WdlInput[]>([]);
  const [bindings, setBindings] = useState<Record<string, WorkflowInputBinding>>({});

  const [inputBucket, setInputBucket] = useState("");
  const [outputBucket, setOutputBucket] = useState("");
  const [outputPath, setOutputPath] = useState("");
  const [showFilter, setShowFilter] = useState<"required" | "all">("required");

  const [loadingWorkflows, setLoadingWorkflows] = useState(false);
  const [loadingInputs, setLoadingInputs] = useState(false);
  const [prepData, setPrepData] = useState<WorkflowPrepareResponse | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const cohortColumnNames = useMemo(() => mappings.map((m) => m.column), [mappings]);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setSuccess(null);
    setLoadingWorkflows(true);
    listWorkflows()
      .then((r) => {
        setWorkflows(r.workflows);
        setS3Folders(r.s3_folders);
        if (r.s3_folders.length > 0) {
          setInputBucket((prev) => prev || r.s3_folders[0].id);
          setOutputBucket((prev) => prev || r.s3_folders[0].id);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoadingWorkflows(false));
  }, [open]);

  useEffect(() => {
    if (!selectedWorkflow) {
      setWdlInputs([]);
      setBindings({});
      setPrepData(null);
      return;
    }
    setLoadingInputs(true);
    setError(null);
    getWorkflowInputs(selectedWorkflow)
      .then((r) => {
        setWdlInputs(r.inputs);
        const initial: Record<string, WorkflowInputBinding> = {};
        for (const inp of r.inputs) {
          const match = cohortColumnNames.find(
            (c) => c.toLowerCase() === inp.short_name.toLowerCase(),
          );
          if (match) {
            initial[inp.short_name] = { mode: "cohort", value: match };
          } else if (inp.defaultValue != null) {
            initial[inp.short_name] = { mode: "static", value: inp.defaultValue };
          } else {
            initial[inp.short_name] = { mode: "static", value: "" };
          }
        }
        setBindings(initial);
        const ts = new Date().toISOString().replace(/[:\-T]/g, "").slice(0, 15);
        setOutputPath(`workflow_outputs/${selectedWorkflow}/${ts}`);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoadingInputs(false));
  }, [selectedWorkflow, cohortColumnNames]);

  useEffect(() => {
    if (!selectedWorkflow || wdlInputs.length === 0) return;
    const t = setTimeout(() => {
      setPreparing(true);
      prepareWorkflow(selectedWorkflow, filters, bindings)
        .then(setPrepData)
        .catch((e) => setError(e.message))
        .finally(() => setPreparing(false));
    }, 400);
    return () => clearTimeout(t);
  }, [selectedWorkflow, wdlInputs, bindings, filters]);

  const updateBinding = (short: string, patch: Partial<WorkflowInputBinding>) => {
    setBindings((prev) => ({
      ...prev,
      [short]: { ...(prev[short] ?? { mode: "static", value: "" }), ...patch },
    }));
  };

  const handleSubmit = async () => {
    if (!inputBucket || !outputBucket) {
      setError("Select input and output buckets first");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await submitWorkflow(
        selectedWorkflow, filters, bindings, inputBucket, outputBucket, outputPath,
      );
      setSuccess(`Submitting ${result.rows_submitted} rows... Job ID: ${result.job_id}`);

      const poll = setInterval(async () => {
        try {
          const status = await checkWorkflowJobStatus(result.job_id);
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
    setSelectedWorkflow("");
    setWdlInputs([]);
    setBindings({});
    onClose();
  };

  const visibleInputs = wdlInputs.filter(
    (inp) => showFilter === "all" || inp.isRequired,
  );
  const missingRequired = wdlInputs.filter(
    (inp) => inp.isRequired && !(bindings[inp.short_name]?.value ?? "").trim(),
  );
  const canSubmit = !!selectedWorkflow && !submitting && !preparing
    && !loadingInputs && missingRequired.length === 0
    && !!prepData && prepData.row_count > 0;

  const renderInputValue = (inp: WdlInput) => {
    const binding = bindings[inp.short_name] ?? { mode: "static", value: "" };
    const staticError = binding.mode === "static"
      ? validateStaticValue(binding.value, inp.type)
      : null;
    return (
      <Box sx={{ display: "flex", flexDirection: "column", gap: 0.5 }}>
        <Box sx={{ display: "flex", gap: 1, alignItems: "flex-start" }}>
          <ToggleButtonGroup
            value={binding.mode}
            exclusive
            size="small"
            onChange={(_, v) => { if (v) updateBinding(inp.short_name, { mode: v, value: "" }); }}
            sx={{ flexShrink: 0 }}
          >
            <ToggleButton value="cohort" sx={{ fontSize: 11, px: 1 }}>Cohort</ToggleButton>
            <ToggleButton value="static" sx={{ fontSize: 11, px: 1 }}>Static</ToggleButton>
          </ToggleButtonGroup>
          {binding.mode === "cohort" ? (
            <Autocomplete
              size="small"
              options={cohortColumnNames}
              value={binding.value || null}
              onChange={(_, v) => updateBinding(inp.short_name, { value: v ?? "" })}
              renderInput={(params) => <TextField {...params} placeholder="Pick a column" />}
              sx={{ flex: 1, minWidth: 200 }}
            />
          ) : (
            <TextField
              value={binding.value}
              onChange={(e) => updateBinding(inp.short_name, { value: e.target.value })}
              size="small"
              fullWidth
              multiline={binding.value.length > 60 || isComplexType(inp.type)}
              maxRows={4}
              placeholder={isComplexType(inp.type) ? "Enter as JSON" : "Static value"}
              error={!!staticError}
              sx={{ "& .MuiInputBase-input": { fontFamily: "monospace", fontSize: 12 } }}
            />
          )}
        </Box>
        {staticError && (
          <Typography variant="caption" color="error">{staticError}</Typography>
        )}
      </Box>
    );
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>Run Workflow</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        {success && <Alert severity="success" sx={{ mb: 2 }}>{success}</Alert>}

        {!success && (
          <Alert severity="info" sx={{ mb: 2 }}>
            This app doesn't verify that your cohort data matches the workflow's expected
            inputs (file formats, semantic types, etc.). Consult the workflow's documentation
            before submitting.
          </Alert>
        )}

        {loadingWorkflows ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
            <CircularProgress />
          </Box>
        ) : (
          <FormControl fullWidth size="small" sx={{ mb: 2 }}>
            <InputLabel>Workflow</InputLabel>
            <Select
              value={selectedWorkflow}
              label="Workflow"
              onChange={(e) => setSelectedWorkflow(e.target.value)}
            >
              {workflows.map((w) => (
                <MenuItem key={w.id} value={w.id}>
                  {w.name}
                  {w.description ? ` — ${w.description.slice(0, 80)}` : ""}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        )}

        {loadingInputs && (
          <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
            <CircularProgress />
          </Box>
        )}

        {wdlInputs.length > 0 && !success && (
          <>
            <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}>
              <Typography variant="subtitle2">Inputs</Typography>
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
                  <TableCell sx={{ fontWeight: 600, width: "30%" }}>Input Key</TableCell>
                  <TableCell sx={{ fontWeight: 600, width: "15%" }}>Type</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Values</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {visibleInputs.map((inp) => (
                  <TableRow key={inp.name}>
                    <TableCell sx={{ fontFamily: "monospace", fontSize: 12, verticalAlign: "top" }}>
                      {inp.short_name}
                      {inp.isRequired && (
                        <Chip label="required" size="small" color="warning" variant="outlined" sx={{ ml: 1, fontSize: 10, height: 18 }} />
                      )}
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
            <Box sx={{ display: "flex", gap: 2, mb: 2, flexWrap: "wrap" }}>
              <FormControl size="small" sx={{ minWidth: 180 }}>
                <InputLabel>Input bucket</InputLabel>
                <Select value={inputBucket} label="Input bucket" onChange={(e) => setInputBucket(e.target.value)}>
                  {s3Folders.map((f) => <MenuItem key={f.id} value={f.id}>{f.name}</MenuItem>)}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 180 }}>
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
                sx={{ flex: 1, minWidth: 200 }}
              />
            </Box>

            <Divider sx={{ my: 2 }} />

            {missingRequired.length > 0 && (
              <Alert severity="warning" sx={{ mb: 2 }}>
                Missing bindings: {missingRequired.map((i) => i.short_name).join(", ")}
              </Alert>
            )}

            {preparing && (
              <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1 }}>
                <CircularProgress size={16} />
                <Typography variant="caption">Building preview...</Typography>
              </Box>
            )}

            {prepData && !preparing && (
              <>
                <Typography variant="body2" sx={{ mb: 1 }}>
                  <strong>{prepData.row_count}</strong> of {prepData.sample_count} rows will be submitted
                  {prepData.skipped > 0 && ` (${prepData.skipped} skipped — missing values in bound columns)`}
                  .
                </Typography>

                {prepData.preview.length > 0 && (
                  <>
                    <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
                      Preview (first {prepData.preview.length} rows)
                    </Typography>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          {prepData.csv_columns.map((c) => (
                            <TableCell key={c} sx={{ fontFamily: "monospace", fontSize: 11 }}>{c}</TableCell>
                          ))}
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {prepData.preview.map((row, idx) => (
                          <TableRow key={idx}>
                            {prepData.csv_columns.map((c) => (
                              <TableCell
                                key={c}
                                sx={{ fontFamily: "monospace", fontSize: 11, maxWidth: 250, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                              >
                                {row[c] ?? ""}
                              </TableCell>
                            ))}
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </>
                )}
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
            disabled={!canSubmit}
          >
            {submitting ? "Submitting..." : `Submit ${prepData?.row_count ?? 0} Jobs`}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
