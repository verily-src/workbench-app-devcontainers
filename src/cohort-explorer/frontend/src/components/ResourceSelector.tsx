import { useEffect, useState } from "react";
import {
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Typography,
} from "@mui/material";
import StorageIcon from "@mui/icons-material/Storage";
import type { Datasource } from "../api";
import { connectResource, fetchDatasources } from "../api";

interface Props {
  onConnected: (resourceId: string) => void;
}

export default function ResourceSelector({ onConnected }: Props) {
  const [resources, setResources] = useState<Datasource[]>([]);
  const [selected, setSelected] = useState("__local__");
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDatasources()
      .then((data) => {
        setResources(data.resources);
        if (data.active) setSelected(data.active);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const handleConnect = async () => {
    setConnecting(true);
    setError(null);
    try {
      await connectResource(selected);
      onConnected(selected);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connection failed");
    } finally {
      setConnecting(false);
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh" }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        height: "100vh",
        bgcolor: "grey.50",
      }}
    >
      <Card sx={{ minWidth: 400, maxWidth: 500 }}>
        <CardContent sx={{ p: 4 }}>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 3 }}>
            <StorageIcon color="primary" />
            <Typography variant="h5" sx={{ fontWeight: 600 }}>
              Cohort Explorer
            </Typography>
          </Box>

          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            Select a datasource to explore. Choose an Aurora database from
            this workspace, or use the local demo data.
          </Typography>

          <FormControl fullWidth sx={{ mb: 2 }}>
            <InputLabel>Datasource</InputLabel>
            <Select
              value={selected}
              label="Datasource"
              onChange={(e) => setSelected(e.target.value)}
            >
              <MenuItem value="__local__">
                Local data (SQLite)
              </MenuItem>
              {resources.map((r) => (
                <MenuItem key={r.id} value={r.id}>
                  {r.name}
                  {r.database ? ` — ${r.database}` : ""}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          {error && (
            <Typography variant="body2" color="error" sx={{ mb: 2 }}>
              {error}
            </Typography>
          )}

          <Button
            variant="contained"
            fullWidth
            onClick={handleConnect}
            disabled={connecting}
          >
            {connecting ? "Connecting..." : "Connect"}
          </Button>
        </CardContent>
      </Card>
    </Box>
  );
}
