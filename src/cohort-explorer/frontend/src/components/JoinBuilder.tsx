import { useEffect, useMemo, useState } from "react";
import {
  Alert, Box, Button, Chip, CircularProgress, FormControl, IconButton,
  InputLabel, MenuItem, Select, Stack, Tooltip, Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CloseIcon from "@mui/icons-material/Close";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import type { AuroraColumn, AuroraTable, JoinPreviewStep, JoinStep as ApiJoinStep } from "../api";
import { fetchTableColumns, previewJoinGrowth, validateJoin } from "../api";
import TableSelect from "./TableSelect";

// BENCH-10344's decided answer to Q2: 3 tables is enough for the UI's
// exploratory join builder. Saved/activated joins (joins.py) aren't capped —
// this limit is a UI decision, not a backend one.
const MAX_TABLES = 3;

const JOIN_TYPE_LABELS: Record<ApiJoinStep["join_type"] & string, string> = {
  inner: "Inner", left: "Left", full: "Full outer",
};

interface StepState {
  table: string;
  joinTo?: string;
  leftKey?: string;
  rightKey?: string;
  joinType: "inner" | "left" | "full";
  columns: AuroraColumn[];
}

function hasColumn(columns: AuroraColumn[], name: string): boolean {
  return columns.some((c) => c.column === name);
}

// Column names that every table with loaded columns has. Needs two tables to mean anything.
function commonColumnNames(steps: StepState[]): string[] {
  const loaded = steps.filter((s) => s.columns.length > 0);
  if (loaded.length < 2) return [];
  return loaded[0].columns.map((c) => c.column).filter((name) => loaded.every((s) => hasColumn(s.columns, name)));
}

// Join a step to the base table on `key`, if both tables have that column.
function joinToBaseOnKey(step: StepState, base: StepState, key: string): StepState {
  if (!hasColumn(step.columns, key) || !hasColumn(base.columns, key)) return step;
  return { ...step, joinTo: base.table, leftKey: key, rightKey: key };
}

function emptyStep(): StepState {
  return { table: "", joinType: "inner", columns: [] };
}

function isStepComplete(step: StepState, isBase: boolean): boolean {
  if (!step.table) return false;
  return isBase || !!(step.joinTo && step.leftKey && step.rightKey);
}

function toApiSteps(steps: StepState[]): ApiJoinStep[] {
  return steps.map((s, i) =>
    i === 0
      ? { table: s.table }
      : { table: s.table, join_to: s.joinTo, left_key: s.leftKey, right_key: s.rightKey, join_type: s.joinType },
  );
}

interface Props {
  resourceId: string;
  tables: AuroraTable[];
  onChange: (steps: ApiJoinStep[] | null) => void;
}

export default function JoinBuilder({ resourceId, tables, onChange }: Props) {
  const [steps, setSteps] = useState<StepState[]>([emptyStep()]);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<JoinPreviewStep[] | null>(null);
  const [commonKey, setCommonKey] = useState("");
  const commonColumns = useMemo(() => commonColumnNames(steps), [steps]);

  const invalidate = () => {
    onChange(null);
    setPreview(null);
    setError(null);
  };

  const loadColumns = async (index: number, table: string) => {
    try {
      const columns = await fetchTableColumns(resourceId, table);
      setSteps((prev) => prev.map((s, i) => {
        if (i !== index) return s;
        const loaded = { ...s, columns };
        return i === 0 || !commonKey ? loaded : joinToBaseOnKey(loaded, prev[0], commonKey);
      }));
    } catch {
      setSteps((prev) => prev.map((s, i) => (i === index ? { ...s, columns: [] } : s)));
    }
  };

  const updateStep = (index: number, updates: Partial<StepState>) => {
    invalidate();
    setSteps((prev) => prev.map((s, i) => (i === index ? { ...s, ...updates } : s)));
  };

  const selectCommonKey = (key: string) => {
    invalidate();
    setCommonKey(key);
    if (key) setSteps((prev) => prev.map((s, i) => (i === 0 ? s : joinToBaseOnKey(s, prev[0], key))));
  };

  // When the tables share exactly one column, use it as the key without asking.
  useEffect(() => {
    if (!commonKey && commonColumns.length === 1) selectCommonKey(commonColumns[0]);
  }, [commonKey, commonColumns]);

  const handleTableChange = (index: number, table: string) => {
    updateStep(index, { table, joinTo: undefined, leftKey: undefined, rightKey: undefined, columns: [] });
    if (table) loadColumns(index, table);
  };

  const addStep = () => {
    invalidate();
    setSteps((prev) => [...prev, emptyStep()]);
  };

  const removeLastStep = () => {
    invalidate();
    setSteps((prev) => prev.slice(0, -1));
  };

  const usedTableNames = steps.map((s) => s.table).filter(Boolean);
  const lastStep = steps[steps.length - 1];
  const canAddStep = steps.length < MAX_TABLES && isStepComplete(lastStep, steps.length === 1);
  const canCheck = steps.length >= 2 && steps.every((s, i) => isStepComplete(s, i === 0));

  const handleCheck = async () => {
    setChecking(true);
    setError(null);
    try {
      const apiSteps = toApiSteps(steps);
      const result = await validateJoin(resourceId, apiSteps);
      if (!result.valid) {
        setError(result.error ?? "Join is invalid");
        setPreview(null);
        onChange(null);
        return;
      }
      const growth = await previewJoinGrowth(resourceId, apiSteps);
      setPreview(growth);
      onChange(apiSteps);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Join check failed");
      onChange(null);
    } finally {
      setChecking(false);
    }
  };

  return (
    <Box sx={{ mb: 2 }}>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Join up to {MAX_TABLES} tables on a shared key column.
      </Typography>
      {commonColumns.length > 0 && (
        <FormControl size="small" sx={{ minWidth: 220, mb: 1.5 }}>
          <InputLabel>Common key column</InputLabel>
          <Select
            label="Common key column"
            value={commonColumns.includes(commonKey) ? commonKey : ""}
            onChange={(e) => selectCommonKey(e.target.value)}
          >
            {commonColumns.length > 1 && <MenuItem value="">None (set keys per table)</MenuItem>}
            {commonColumns.map((name) => (
              <MenuItem key={name} value={name}>{name}</MenuItem>
            ))}
          </Select>
        </FormControl>
      )}
      <Stack spacing={1.5}>
        {steps.map((step, i) => {
          const isBase = i === 0;
          const parentOptions = steps.slice(0, i).filter((s) => s.table);
          const parent = steps.find((s) => s.table === step.joinTo);
          return (
            <Box key={i} sx={{ border: 1, borderColor: "divider", borderRadius: 1, p: 1.5 }}>
              <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                <Typography variant="caption" sx={{ minWidth: 36, color: "text.secondary" }}>
                  {isBase ? "Base" : `+ Table ${i + 1}`}
                </Typography>
                <TableSelect
                  label={isBase ? "Base table" : "Join table"}
                  tables={tables}
                  value={step.table}
                  onChange={(t) => handleTableChange(i, t)}
                  disabledNames={usedTableNames.filter((n) => n !== step.table)}
                />
                {!isBase && i === steps.length - 1 && (
                  <Tooltip title="Remove this table">
                    <IconButton size="small" onClick={removeLastStep}>
                      <CloseIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                )}
              </Stack>

              {!isBase && step.table && (
                <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: "wrap", rowGap: 1.5 }}>
                  <FormControl size="small" sx={{ minWidth: 150 }}>
                    <InputLabel>Join to</InputLabel>
                    <Select
                      label="Join to"
                      value={step.joinTo ?? ""}
                      onChange={(e) => updateStep(i, { joinTo: e.target.value, leftKey: undefined })}
                    >
                      {parentOptions.map((p) => (
                        <MenuItem key={p.table} value={p.table}>{p.table}</MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 150 }} disabled={!step.joinTo}>
                    <InputLabel>{parent ? `${parent.table} key` : "Left key"}</InputLabel>
                    <Select
                      label={parent ? `${parent.table} key` : "Left key"}
                      value={step.leftKey ?? ""}
                      onChange={(e) => updateStep(i, { leftKey: e.target.value })}
                    >
                      {(parent?.columns ?? []).map((c) => (
                        <MenuItem key={c.column} value={c.column}>{c.column}</MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 150 }}>
                    <InputLabel>{step.table} key</InputLabel>
                    <Select
                      label={`${step.table} key`}
                      value={step.rightKey ?? ""}
                      onChange={(e) => updateStep(i, { rightKey: e.target.value })}
                    >
                      {step.columns.map((c) => (
                        <MenuItem key={c.column} value={c.column}>{c.column}</MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                  <FormControl size="small" sx={{ minWidth: 130 }}>
                    <InputLabel>Join type</InputLabel>
                    <Select
                      label="Join type"
                      value={step.joinType}
                      onChange={(e) => updateStep(i, { joinType: e.target.value as StepState["joinType"] })}
                    >
                      {(Object.entries(JOIN_TYPE_LABELS) as [StepState["joinType"], string][]).map(([val, label]) => (
                        <MenuItem key={val} value={val}>{label}</MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                </Stack>
              )}
            </Box>
          );
        })}
      </Stack>

      <Stack direction="row" spacing={1} sx={{ mt: 1.5, alignItems: "center" }}>
        <Tooltip title={steps.length >= MAX_TABLES ? `UI limit of ${MAX_TABLES} tables (BENCH-10344)` : ""}>
          <span>
            <Button size="small" startIcon={<AddIcon />} onClick={addStep} disabled={!canAddStep}>
              Add table
            </Button>
          </span>
        </Tooltip>
        <Button
          size="small"
          variant="outlined"
          onClick={handleCheck}
          disabled={!canCheck || checking}
          startIcon={checking ? <CircularProgress size={14} /> : undefined}
        >
          {checking ? "Checking..." : "Check join"}
        </Button>
      </Stack>

      {error && <Alert severity="error" sx={{ mt: 1.5 }}>{error}</Alert>}

      {preview && (
        <Stack spacing={0.5} sx={{ mt: 1.5 }}>
          {preview.map((p, i) => {
            const prevCount = i > 0 ? preview[i - 1].row_count : null;
            const grew = prevCount != null && p.row_count != null && p.row_count > prevCount * 1.5;
            return (
              <Stack key={p.table} direction="row" spacing={1} sx={{ alignItems: "center" }}>
                <CheckCircleIcon fontSize="small" color="success" />
                <Typography variant="body2">
                  {p.table}: {p.timed_out || p.row_count === null ? "too large to count" : `${p.row_count.toLocaleString()} rows`}
                </Typography>
                {grew && (
                  <Chip
                    size="small"
                    color="warning"
                    icon={<WarningAmberIcon />}
                    label="row count grew — check this join's cardinality"
                  />
                )}
              </Stack>
            );
          })}
        </Stack>
      )}
    </Box>
  );
}
