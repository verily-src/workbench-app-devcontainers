import { Navigate, Route, Routes } from "react-router-dom";
import { useMemo, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { SettingsPanel } from "./components/SettingsPanel";
import ChatPanel, { ChatToggleButton } from "./components/ChatPanel";
import { useCatalog, useConfig } from "./hooks/useDatasets";
import CatalogHome from "./pages/CatalogPage";
import TablePage from "./pages/TablePage";
import TerminologyPage from "./pages/TerminologyPage";
import CohortsPage from "./pages/CohortsPage";

export default function App() {
  const { config, save: saveConfig, reload: reloadConfig } = useConfig();
  const [refreshKey, setRefreshKey] = useState(0);
  const [showSettings, setShowSettings] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);

  const configured = config?.configured ?? false;
  const dataProject = config?.data_project ?? "";

  const { data, loading } = useCatalog(
    configured ? dataProject : "",
    refreshKey,
  );

  const datasets = useMemo(() => data?.datasets ?? [], [data]);

  const handleRefresh = () => {
    reloadConfig();
    setRefreshKey((k) => k + 1);
  };

  if (!configured) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh" }}>
        <div style={{ maxWidth: 600, width: "100%" }}>
          <div style={{ textAlign: "center", marginBottom: 24 }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: "var(--wb-primary)" }}>workbench</div>
            <div style={{ color: "var(--wb-muted)", fontSize: 14 }}>Data Catalog v2</div>
          </div>
          <SettingsPanel
            config={config}
            onSave={saveConfig}
            onSaved={handleRefresh}
          />
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <Sidebar
        projectId={dataProject}
        projectName={config?.data_project_name || ""}
        onSettingsClick={() => setShowSettings((s) => !s)}
        onRefresh={handleRefresh}
        onNavigate={() => setShowSettings(false)}
      />

      <main
        style={{
          flex: 1,
          overflow: "auto",
          height: "100vh",
        }}
      >
        {showSettings ? (
          <div style={{ padding: 32, maxWidth: 640 }}>
            <button
              type="button"
              onClick={() => setShowSettings(false)}
              style={{
                background: "none",
                border: "none",
                color: "var(--wb-primary)",
                cursor: "pointer",
                fontSize: 14,
                fontFamily: "var(--wb-font)",
                padding: 0,
                marginBottom: 16,
              }}
            >
              &larr; Back
            </button>
            <SettingsPanel
              config={config}
              onSave={saveConfig}
              onSaved={() => {
                handleRefresh();
                setShowSettings(false);
              }}
            />
          </div>
        ) : (
          <Routes>
            <Route
              path="/"
              element={
                <CatalogHome
                  config={config}
                  datasets={datasets}
                  loading={loading}
                  onRefresh={handleRefresh}
                />
              }
            />
            <Route path="/table/:project/:dataset/:table" element={<TablePage />} />
            <Route path="/terminology" element={<TerminologyPage />} />
            <Route path="/cohorts" element={<CohortsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        )}
      </main>

      <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} />
      {!chatOpen && <ChatToggleButton onClick={() => setChatOpen(true)} />}
    </div>
  );
}
