import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Box, CircularProgress, CssBaseline, Snackbar } from "@mui/material";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import FilterPanel from "./components/FilterPanel.tsx";
import DataGrid from "./components/DataGrid.tsx";
import SummaryBar from "./components/SummaryBar.tsx";
import TissueChart from "./components/TissueChart.tsx";
import ResourceSelector from "./components/ResourceSelector.tsx";
import { connectResource, fetchCounts, fetchFilters, fetchSamples, seedData } from "./api.ts";
import type { Counts, FilterState, FiltersResponse, SampleRow } from "./types.ts";
import { EMPTY_FILTERS } from "./types.ts";

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
    primary: { main: "#1565c0" },
  },
  typography: {
    fontFamily: "'Inter', 'Roboto', 'Helvetica', 'Arial', sans-serif",
  },
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

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box sx={{ display: "flex", flexDirection: "column", height: "100vh" }}>
        <SummaryBar counts={counts} filters={applied} loading={loading} />
        <Box sx={{ display: "flex", flex: 1, overflow: "hidden" }}>
          <FilterPanel
            available={available}
            filters={pending}
            onChange={setPending}
            dirty={dirty}
            onApply={handleApply}
            onReset={handleReset}
          />
          <Box sx={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
            {available && (
              <TissueChart
                data={available.tissue_type}
                selected={applied.tissue_type}
                onBarClick={(tissue) => {
                  const current = pending.tissue_type;
                  const updated = current.includes(tissue)
                    ? current.filter((v) => v !== tissue)
                    : [...current, tissue];
                  const newPending = { ...pending, tissue_type: updated };
                  setPending(newPending);
                  setApplied(newPending);
                  loadData(newPending);
                  saveState(resourceId, newPending);
                }}
              />
            )}
            <DataGrid rows={rows} loading={loading} />
          </Box>
        </Box>
      </Box>
      <Snackbar open={!!error} autoHideDuration={6000} onClose={() => setError(null)}>
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      </Snackbar>
    </ThemeProvider>
  );
}
