import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Box, CircularProgress, CssBaseline, IconButton, Snackbar, Tooltip } from "@mui/material";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import { Allotment } from "allotment";
import "allotment/dist/style.css";
import FilterPanel from "./components/FilterPanel.tsx";
import DataGrid from "./components/DataGrid.tsx";
import SummaryBar from "./components/SummaryBar.tsx";
import ChartDashboard from "./components/charts/ChartDashboard.tsx";
import ResourceSelector from "./components/ResourceSelector.tsx";
import ConnectionError from "./components/ConnectionError.tsx";
import { connectResource, fetchCounts, fetchFilters, fetchSamples, seedData } from "./api.ts";
import type { ChartConfig, Counts, FilterState, FiltersResponse, SampleRow } from "./types.ts";
import { DEFAULT_CHART_TYPE, EMPTY_FILTERS, FIELD_META } from "./types.ts";

const STORAGE_KEY = "cohort-explorer-state";

function saveState(resourceId: string, filters: FilterState) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ resourceId, filters }));
}

function loadSavedState(): { resourceId: string; filters: FilterState } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed?.resourceId && parsed?.filters) return parsed;
  } catch { /* corrupt data */ }
  return null;
}

const theme = createTheme({
  palette: {
    primary: { main: "#087a6a", dark: "#054f45", light: "#84bdb5" },
    background: { default: "#F5F6F7" },
    text: { primary: "#212529", secondary: "rgba(0,0,0,0.6)" },
  },
  typography: {
    fontFamily: "'Open Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
  },
  shape: { borderRadius: 6 },
});

function filtersEqual(a: FilterState, b: FilterState): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export default function App() {
  const [connected, setConnected] = useState(false);
  const [resourceId, setResourceId] = useState<string>("__local__");
  const [pending, setPending] = useState<FilterState>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<FilterState>(EMPTY_FILTERS);
  const [available, setAvailable] = useState<FiltersResponse | null>(null);
  const [rows, setRows] = useState<SampleRow[]>([]);
  const [counts, setCounts] = useState<Counts | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [chartConfigs, setChartConfigs] = useState<ChartConfig[]>([
    { id: "default", fieldKey: "tissue_type", chartType: "bar" },
  ]);
  const [filterPaneVisible, setFilterPaneVisible] = useState(true);
  const [gridPaneVisible, setGridPaneVisible] = useState(true);
  const initialized = useRef(false);
  const fetchIdRef = useRef(0);

  useEffect(() => {
    const saved = loadSavedState();
    if (!saved) { setRestoring(false); return; }
    connectResource(saved.resourceId)
      .then(() => {
        setResourceId(saved.resourceId);
        setPending(saved.filters);
        setApplied(saved.filters);
        setConnected(true);
      })
      .catch((e) => {
        console.warn("Auto-reconnect failed, showing selector:", e);
      })
      .finally(() => setRestoring(false));
  }, []);

  const dirty = !filtersEqual(pending, applied);

  const loadData = useCallback(async (f: FilterState) => {
    const fetchId = ++fetchIdRef.current;
    setLoading(true);
    try {
      const [samplesData, filtersData, countsData] = await Promise.all([
        fetchSamples(f),
        fetchFilters(f),
        fetchCounts(f),
      ]);
      if (fetchId !== fetchIdRef.current) return;
      setRows(samplesData);
      setAvailable(filtersData);
      setCounts(countsData);
      setError(null);
    } catch (e) {
      if (fetchId !== fetchIdRef.current) return;
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      if (fetchId === fetchIdRef.current) setLoading(false);
    }
  }, []);

  const initializeData = useCallback(async () => {
    if (initialized.current) return;
    initialized.current = true;

    let needsSeed = false;
    try {
      const countsData = await fetchCounts(EMPTY_FILTERS);
      needsSeed = countsData.samples === 0;
    } catch {
      needsSeed = true;
    }

    if (needsSeed && resourceId === "__local__") {
      setSeeding(true);
      try {
        const result = await seedData();
        if (result.seeded === 0) {
          setError("No local data found. Try selecting an Aurora datasource instead.");
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Seed failed");
      }
      setSeeding(false);
    }

    await loadData(applied);
  }, [loadData, applied, resourceId]);

  useEffect(() => {
    if (connected) initializeData();
  }, [connected, initializeData]);

  const handleApply = useCallback(() => {
    setApplied(pending);
    loadData(pending);
    saveState(resourceId, pending);
  }, [pending, loadData, resourceId]);

  const handleReset = useCallback(() => {
    setPending(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    loadData(EMPTY_FILTERS);
    saveState(resourceId, EMPTY_FILTERS);
  }, [loadData, resourceId]);

  const handleDisconnect = useCallback(() => {
    setConnected(false);
    setResourceId("__local__");
    setPending(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    setAvailable(null);
    setRows([]);
    setCounts(null);
    setError(null);
    setLoading(true);
    initialized.current = false;
    clearSavedState();
  }, []);

  const handleChartFilter = useCallback(
    (fieldKey: string, value: string | { min: number; max: number }) => {
      let newPending: FilterState;
      if (typeof value === "string") {
        const current = (pending as unknown as Record<string, string[]>)[fieldKey] ?? [];
        const updated = current.includes(value)
          ? current.filter((v) => v !== value)
          : [...current, value];
        newPending = { ...pending, [fieldKey]: updated };
      } else {
        newPending = {
          ...pending,
          [`${fieldKey}_min`]: value.min,
          [`${fieldKey}_max`]: value.max,
        };
      }
      setPending(newPending);
      setApplied(newPending);
      loadData(newPending);
      saveState(resourceId, newPending);
    },
    [pending, loadData, resourceId],
  );

  const handleAddChart = useCallback((fieldKey: string) => {
    const meta = FIELD_META.find((f) => f.key === fieldKey);
    const chartType = meta ? DEFAULT_CHART_TYPE[meta.dataType] : "bar";
    setChartConfigs((prev) => [
      ...prev,
      { id: crypto.randomUUID(), fieldKey, chartType },
    ]);
  }, []);

  const handleRemoveChart = useCallback((id: string) => {
    setChartConfigs((prev) => prev.filter((c) => c.id !== id));
  }, []);

  const handleUpdateChart = useCallback(
    (id: string, updates: Partial<Pick<ChartConfig, "fieldKey" | "chartType">>) => {
      setChartConfigs((prev) =>
        prev.map((c) => (c.id === id ? { ...c, ...updates } : c)),
      );
    },
    [],
  );

  if (restoring) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh" }}>
        <CircularProgress />
      </Box>
    );
  }

  if (!connected) {
    return (
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <ResourceSelector onConnected={(id) => { setResourceId(id); setConnected(true); saveState(id, EMPTY_FILTERS); }} />
      </ThemeProvider>
    );
  }

  if (seeding) {
    return (
      <Box
        sx={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          height: "100vh",
          gap: 2,
        }}
      >
        <CircularProgress />
        <Box>Seeding GTEx V8 data (17,350 samples)...</Box>
      </Box>
    );
  }

  const hasData = rows.length > 0 || available !== null;
  const blockingError = error && !hasData;

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ display: "flex", flexDirection: "column", height: "100vh" }}>
        <SummaryBar counts={counts} filters={applied} loading={loading} onDisconnect={handleDisconnect} />
        <Box sx={{ flex: 1, overflow: "hidden", position: "relative" }}>
          {!filterPaneVisible && (
            <Tooltip title="Show filters">
              <IconButton
                size="small"
                onClick={() => setFilterPaneVisible(true)}
                sx={{
                  position: "absolute",
                  left: 4,
                  top: 8,
                  zIndex: 10,
                  bgcolor: "background.paper",
                  border: 1,
                  borderColor: "divider",
                  "&:hover": { bgcolor: "action.hover" },
                }}
              >
                <ChevronRightIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
          {!gridPaneVisible && (
            <Tooltip title="Show data grid">
              <IconButton
                size="small"
                onClick={() => setGridPaneVisible(true)}
                sx={{
                  position: "absolute",
                  right: 16,
                  bottom: 4,
                  zIndex: 10,
                  bgcolor: "background.paper",
                  border: 1,
                  borderColor: "divider",
                  "&:hover": { bgcolor: "action.hover" },
                }}
              >
                <ExpandLessIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
          <Allotment defaultSizes={[280, 1000]} snap>
            <Allotment.Pane minSize={150} maxSize={500} visible={filterPaneVisible}>
              <FilterPanel
                available={available}
                filters={pending}
                onChange={setPending}
                dirty={dirty}
                onApply={handleApply}
                onReset={handleReset}
                onCollapse={() => setFilterPaneVisible(false)}
              />
            </Allotment.Pane>
            <Allotment.Pane>
              {blockingError ? (
                <ConnectionError
                  message={error}
                  onRetry={() => loadData(applied)}
                  onDisconnect={handleDisconnect}
                />
              ) : (
                <Allotment vertical defaultSizes={[300, 500]} snap>
                  <Allotment.Pane minSize={100}>
                    <ChartDashboard
                      chartConfigs={chartConfigs}
                      available={available}
                      rows={rows}
                      applied={applied}
                      onChartFilter={handleChartFilter}
                      onAddChart={handleAddChart}
                      onRemoveChart={handleRemoveChart}
                      onUpdateChart={handleUpdateChart}
                    />
                  </Allotment.Pane>
                  <Allotment.Pane minSize={100} visible={gridPaneVisible}>
                    <DataGrid rows={rows} loading={loading} error={error} />
                  </Allotment.Pane>
                </Allotment>
              )}
            </Allotment.Pane>
          </Allotment>
        </Box>
      </Box>
      {error && hasData && (
        <Snackbar open autoHideDuration={6000} onClose={() => setError(null)}>
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        </Snackbar>
      )}
    </ThemeProvider>
  );
}
