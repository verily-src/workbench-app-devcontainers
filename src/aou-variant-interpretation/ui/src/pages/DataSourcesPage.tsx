import DataSourcesPanel from "../components/settings/DataSourcesPanel";
import SettingsPage from "./SettingsPage";

export default function DataSourcesPage() {
  return (
    <SettingsPage title="Sources">
      <DataSourcesPanel />
    </SettingsPage>
  );
}
