import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Box, CircularProgress, CssBaseline, Snackbar } from "@mui/material";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import FilterPanel from "./components/FilterPanel.tsx";
import DataGrid from "./components/DataGrid.tsx";
import SummaryBar from "./components/SummaryBar.tsx";
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

  const loadData = useCallback(async (f: FilterState) => {
    setLoading(true);
    try {
      const [samplesData, filtersData, countsData] = await Promise.all([
        fetchSamples(f),
        fetchFilters(f),
        fetchCounts(f),
      ]);
      setRows(samplesData);
      setAvailable(filtersData);
      setCounts(countsData);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
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
      loadData(updated);
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
          <DataGrid rows={rows} loading={loading} />
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
