import { useState } from "react";
import {
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import type { ColumnMapping } from "../api";
import { confirmSchema } from "../api";

const TYPE_OPTIONS = ["boolean", "integer", "float", "text", "date"];
const FILTER_OPTIONS = ["categorical", "range", "none"];

interface Props {
  mappings: ColumnMapping[];
  sourceName: string;
  tableName?: string;
  filePath?: string;
  folderId?: string;
  onConfirmed: (mappings: ColumnMapping[]) => void;
  onBack: () => void;
}

export default function SchemaReview({ mappings: initial, sourceName, tableName, filePath, folderId, onConfirmed, onBack }: Props) {
  const [mappings, setMappings] = useState<ColumnMapping[]>(initial);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const updateMapping = (index: number, field: keyof ColumnMapping, value: string) => {
    setMappings((prev) => prev.map((m, i) => (i === index ? { ...m, [field]: value } : m)));
  };

  const handleConfirm = async () => {
    setConfirming(true);
    setError(null);
    try {
      await confirmSchema({ mappings, folder_id: folderId, source_name: sourceName, table_name: tableName, file_path: filePath });
      onConfirmed(mappings);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to confirm schema");
    } finally {
      setConfirming(false);
    }
  };

  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: "center",
        alignItems: "flex-start",
        minHeight: "100vh",
        bgcolor: "grey.50",
        py: 4,
      }}
    >
      <Card sx={{ maxWidth: 900, width: "100%" }}>
        <CardContent sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ fontWeight: 600, mb: 1 }}>
            Review Schema
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {mappings.length} columns inferred from <strong>{sourceName}</strong>.
            Adjust types, filters, and labels as needed before loading.
          </Typography>

          <TableContainer sx={{ maxHeight: 500, mb: 2 }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600 }}>Column</TableCell>
                  <TableCell sx={{ fontWeight: 600, width: 130 }}>Type</TableCell>
                  <TableCell sx={{ fontWeight: 600, width: 140 }}>Filter</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Label</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {mappings.map((m, i) => (
                  <TableRow key={m.column}>
                    <TableCell>
                      <Typography variant="body2" sx={{ fontFamily: "monospace", fontSize: 12 }}>
                        {m.column}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Select
                        size="small"
                        value={m.type}
                        onChange={(e) => updateMapping(i, "type", e.target.value)}
                        fullWidth
                        sx={{ fontSize: 13 }}
                      >
                        {TYPE_OPTIONS.map((t) => (
                          <MenuItem key={t} value={t}>{t}</MenuItem>
                        ))}
                      </Select>
                    </TableCell>
                    <TableCell>
                      <Select
                        size="small"
                        value={m.filter}
                        onChange={(e) => updateMapping(i, "filter", e.target.value)}
                        fullWidth
                        sx={{ fontSize: 13 }}
                      >
                        {FILTER_OPTIONS.map((f) => (
                          <MenuItem key={f} value={f}>{f}</MenuItem>
                        ))}
                      </Select>
                    </TableCell>
                    <TableCell>
                      <TextField
                        size="small"
                        value={m.label}
                        onChange={(e) => updateMapping(i, "label", e.target.value)}
                        fullWidth
                        slotProps={{ input: { sx: { fontSize: 13 } } }}
                      />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          {error && (
            <Typography variant="body2" color="error" sx={{ mb: 2 }}>
              {error}
            </Typography>
          )}

          <Box sx={{ display: "flex", justifyContent: "space-between" }}>
            <Button onClick={onBack}>Back</Button>
            <Button
              variant="contained"
              onClick={handleConfirm}
              disabled={confirming}
              startIcon={confirming ? <CircularProgress size={16} /> : undefined}
            >
              {confirming ? "Confirming..." : "Confirm & Load"}
            </Button>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}
