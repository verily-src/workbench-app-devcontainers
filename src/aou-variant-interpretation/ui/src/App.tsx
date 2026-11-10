import { Route, Routes } from "react-router-dom";
import ScrollToTop from "./components/common/ScrollToTop";
import SearchEntryPage from "./pages/SearchEntryPage";
import SearchResultsPage from "./pages/SearchResultsPage";
import DataSourcesPage from "./pages/DataSourcesPage";
import SystemStatusPage from "./pages/SystemStatusPage";
import UsagePage from "./pages/UsagePage";
import AppSettingsPage from "./pages/AppSettingsPage";

function App() {
  return (
    <>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<SearchEntryPage />} />
        <Route path="/results" element={<SearchResultsPage />} />
        <Route path="/data-sources" element={<DataSourcesPage />} />
        <Route path="/system-status" element={<SystemStatusPage />} />
        <Route path="/usage" element={<UsagePage />} />
        <Route path="/settings" element={<AppSettingsPage />} />
      </Routes>
    </>
  );
}

export default App;
