import { useState } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from "@mui/material";
import { cohortExists, saveCohort } from "../api";
import type { FilterState } from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
  filters: FilterState;
  sampleCount: number;
  datasource: string;
  onSaved: (name: string) => void;
}

export default function SaveCohortDialog({ open, onClose, filters, sampleCount, datasource, onSaved }: Props) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;

    setSaving(true);
    setError(null);
    try {
      const exists = await cohortExists(trimmed);
      if (exists && !window.confirm(`A cohort named "${trimmed}" already exists. Overwrite?`)) {
        setSaving(false);
        return;
      }
      await saveCohort(trimmed, description.trim(), filters, sampleCount, datasource);
      onSaved(trimmed);
      setName("");
      setDescription("");
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Save Cohort</DialogTitle>
      <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}>
        <Typography variant="body2" color="text.secondary">
          Save the current filter state as a named cohort ({sampleCount.toLocaleString()} samples).
        </Typography>
        <TextField
          label="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
          fullWidth
          size="small"
        />
        <TextField
          label="Description (optional)"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          fullWidth
          size="small"
          multiline
          rows={2}
        />
        {error && (
          <Typography variant="body2" color="error">{error}</Typography>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleSave}
          disabled={!name.trim() || saving}
        >
          {saving ? "Saving..." : "Save"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
