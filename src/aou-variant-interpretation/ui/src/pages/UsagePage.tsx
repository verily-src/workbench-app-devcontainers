import UsagePanel from "../components/settings/UsagePanel";
import SettingsPage from "./SettingsPage";

export default function UsagePage() {
  return (
    <SettingsPage title="Usage" width="wide">
      <UsagePanel />
    </SettingsPage>
  );
}
