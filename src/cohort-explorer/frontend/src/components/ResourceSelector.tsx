import { useEffect, useState } from "react";
import {
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Tooltip,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import StorageIcon from "@mui/icons-material/Storage";
import type { AuroraTable, Datasource, S3File, S3Folder } from "../api";
import { connectResource, fetchDatasources, listAuroraTables, listS3Files, refreshDatasources } from "../api";

export interface ConnectionMeta {
  sourceType: "file" | "aurora";
  folderId?: string;
  s3Path?: string;
  table?: string;
  sourceName?: string;
}

interface Props {
  onConnected: (resourceId: string, meta?: ConnectionMeta) => void;
}

export default function ResourceSelector({ onConnected }: Props) {
  const [resources, setResources] = useState<Datasource[]>([]);
  const [s3Folders, setS3Folders] = useState<S3Folder[]>([]);
  const [selected, setSelected] = useState("__file__");
  const [selectedFolder, setSelectedFolder] = useState("");
  const [selectedFile, setSelectedFile] = useState("");
  const [selectedTable, setSelectedTable] = useState("");
  const [s3Files, setS3Files] = useState<S3File[]>([]);
  const [auroraTables, setAuroraTables] = useState<AuroraTable[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [loadingTables, setLoadingTables] = useState(false);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isFileMode = selected === "__file__";
  const isAuroraMode = resources.some((r) => r.id === selected);

  useEffect(() => {
    fetchDatasources()
      .then((data) => {
        setResources(data.resources);
        setS3Folders(data.s3_folders ?? []);
        if (data.active) setSelected(data.active);
        if (data.s3_folders?.length) setSelectedFolder(data.s3_folders[0].id);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const data = await refreshDatasources();
      setResources(data.resources);
      setS3Folders(data.s3_folders ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  };

  const handleFolderChange = async (folderId: string) => {
    setSelectedFolder(folderId);
    setSelectedFile("");
    if (isFileMode && folderId) {
      setLoadingFiles(true);
      try {
        const files = await listS3Files(folderId);
        setS3Files(files);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to list files");
        setS3Files([]);
      } finally {
        setLoadingFiles(false);
      }
    }
  };

  const handleDatasourceChange = async (value: string) => {
    setSelected(value);
    setSelectedTable("");
    setAuroraTables([]);
    if (value === "__file__" && selectedFolder) {
      setLoadingFiles(true);
      try {
        const files = await listS3Files(selectedFolder);
        setS3Files(files);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to list files");
        setS3Files([]);
      } finally {
        setLoadingFiles(false);
      }
    } else if (value !== "__local__" && value !== "__file__") {
      setLoadingTables(true);
      try {
        const tables = await listAuroraTables(value);
        setAuroraTables(tables);
        if (tables.length === 1) setSelectedTable(tables[0].name);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to list tables");
        setAuroraTables([]);
      } finally {
        setLoadingTables(false);
      }
    }
  };

  const handleConnect = async () => {
    setConnecting(true);
    setError(null);
    try {
      if (isFileMode) {
        await connectResource("__local__", selectedFolder || undefined, selectedFile || undefined);
        const fileName = selectedFile.split("/").pop() ?? "file";
        onConnected("__local__", {
          sourceType: "file",
          folderId: selectedFolder,
          s3Path: selectedFile,
          sourceName: fileName,
        });
      } else if (isAuroraMode) {
        await connectResource(selected, selectedFolder || undefined);
        onConnected(selected, {
          sourceType: "aurora",
          folderId: selectedFolder,
          table: selectedTable,
          sourceName: selectedTable || selected,
        });
      } else {
        await connectResource(selected, selectedFolder || undefined);
        onConnected(selected);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connection failed");
    } finally {
      setConnecting(false);
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const canConnect = (() => {
    if (connecting) return false;
    if (isFileMode) return !!selectedFile;
    if (isAuroraMode) return !!selectedTable;
    return true;
  })();

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
            <Typography variant="h5" sx={{ fontWeight: 600, fontFamily: "'Poppins', sans-serif" }}>
              Cohort Explorer
            </Typography>
          </Box>

          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            Connect to an Aurora database or load a TSV/CSV from S3.
          </Typography>

          <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 2 }}>
            <FormControl fullWidth>
              <InputLabel>Datasource</InputLabel>
              <Select
                value={selected}
                label="Datasource"
                onChange={(e) => handleDatasourceChange(e.target.value)}
              >
                <MenuItem value="__file__">
                  Load from file (S3)
                </MenuItem>
                {resources.map((r) => (
                  <MenuItem key={r.id} value={r.id}>
                    {r.name}
                    {r.database ? ` — ${r.database}` : ""}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Tooltip title="Refresh resource list">
              <IconButton onClick={handleRefresh} disabled={refreshing} size="small">
                {refreshing ? <CircularProgress size={20} /> : <RefreshIcon />}
              </IconButton>
            </Tooltip>
          </Box>

          {isAuroraMode && (
            <FormControl fullWidth sx={{ mb: 2 }}>
              <InputLabel>Table / View</InputLabel>
              <Select
                value={selectedTable}
                label="Table / View"
                onChange={(e) => setSelectedTable(e.target.value)}
                disabled={loadingTables}
              >
                {loadingTables ? (
                  <MenuItem disabled>Loading tables...</MenuItem>
                ) : auroraTables.length === 0 ? (
                  <MenuItem disabled>No tables found</MenuItem>
                ) : (
                  auroraTables.map((t) => (
                    <MenuItem key={t.name} value={t.name}>
                      {t.name} ({t.type})
                    </MenuItem>
                  ))
                )}
              </Select>
            </FormControl>
          )}

          {s3Folders.length > 0 && (
            <FormControl fullWidth sx={{ mb: 2 }}>
              <InputLabel>{isFileMode ? "S3 folder" : "Cohort storage folder"}</InputLabel>
              <Select
                value={selectedFolder}
                label={isFileMode ? "S3 folder" : "Cohort storage folder"}
                onChange={(e) => handleFolderChange(e.target.value)}
              >
                {s3Folders.map((f) => (
                  <MenuItem key={f.id} value={f.id}>
                    {f.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}

          {isFileMode && (
            <FormControl fullWidth sx={{ mb: 2 }}>
              <InputLabel>File</InputLabel>
              <Select
                value={selectedFile}
                label="File"
                onChange={(e) => setSelectedFile(e.target.value)}
                disabled={loadingFiles}
              >
                {loadingFiles ? (
                  <MenuItem disabled>Loading files...</MenuItem>
                ) : s3Files.length === 0 ? (
                  <MenuItem disabled>No TSV/CSV/TXT files found</MenuItem>
                ) : (
                  s3Files.map((f) => (
                    <MenuItem key={f.s3_path} value={f.s3_path}>
                      {f.name} ({formatSize(f.size)})
                    </MenuItem>
                  ))
                )}
              </Select>
            </FormControl>
          )}

          {error && (
            <Typography variant="body2" color="error" sx={{ mb: 2 }}>
              {error}
            </Typography>
          )}

          <Button
            variant="contained"
            fullWidth
            onClick={handleConnect}
            disabled={!canConnect}
          >
            {connecting ? "Connecting..." : "Connect"}
          </Button>
        </CardContent>
      </Card>
    </Box>
  );
}
