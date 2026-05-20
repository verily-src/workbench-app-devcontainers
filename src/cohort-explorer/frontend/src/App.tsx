import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Box, CircularProgress, CssBaseline, Snackbar } from "@mui/material";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import FilterPanel from "./components/FilterPanel.tsx";
import DataGrid from "./components/DataGrid.tsx";
import SummaryBar from "./components/SummaryBar.tsx";
import TissueChart from "./components/TissueChart.tsx";
import { fetchCounts, fetchFilters, fetchSamples, seedData } from "./api.ts";
import type { Counts, FilterState, FiltersResponse, SampleRow } from "./types.ts";
import { EMPTY_FILTERS } from "./types.ts";

const theme = createTheme({
  palette: {
    primary: { main: "#1565c0" },
  },
  typography: {
    fontFamily: "'Inter', 'Roboto', 'Helvetica', 'Arial', sans-serif",
  },
});

export default function App() {
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [available, setAvailable] = useState<FiltersResponse | null>(null);
  const [rows, setRows] = useState<SampleRow[]>([]);
  const [counts, setCounts] = useState<Counts | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);
  const initialized = useRef(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fetchIdRef = useRef(0);

  const loadData = useCallback(async (f: FilterState, showLoading = true) => {
    const fetchId = ++fetchIdRef.current;
    if (showLoading) setLoading(true);
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

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;

    (async () => {
      let needsSeed = false;
      try {
        const countsData = await fetchCounts(EMPTY_FILTERS);
        needsSeed = countsData.samples === 0;
      } catch {
        needsSeed = true;
      }

      if (needsSeed) {
        setSeeding(true);
        try {
          const result = await seedData();
          if (result.seeded === 0) {
            setError("Seed completed but loaded 0 rows. Check TSV_PATH in container logs.");
          }
        } catch (e) {
          setError(e instanceof Error ? e.message : "Seed failed");
        }
        setSeeding(false);
      }

      await loadData(EMPTY_FILTERS);
    })();
  }, [loadData]);

  const handleFilterChange = useCallback(
    (updated: FilterState) => {
      setFilters(updated);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => loadData(updated, false), 600);
    },
    [loadData],
  );

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
        <SummaryBar counts={counts} filters={filters} loading={loading} />
        <Box sx={{ display: "flex", flex: 1, overflow: "hidden" }}>
          <FilterPanel
            available={available}
            filters={filters}
            onChange={handleFilterChange}
          />
          <Box sx={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
            {available && (
              <TissueChart
                data={available.tissue_type}
                selected={filters.tissue_type}
                onBarClick={(tissue) => {
                  const current = filters.tissue_type;
                  const updated = current.includes(tissue)
                    ? current.filter((v) => v !== tissue)
                    : [...current, tissue];
                  handleFilterChange({ ...filters, tissue_type: updated });
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
