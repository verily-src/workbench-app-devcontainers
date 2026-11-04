import { useEffect, useState } from "react";
import { api } from "../api";

type Status = Awaited<ReturnType<typeof api.agentStoreStatus>>;

/** Choose where agent conversations are stored and create that storage. */
export function AgentMemorySettings() {
  const [status, setStatus] = useState<Status | null>(null);
  const [choice, setChoice] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const load = () => api.agentStoreStatus().then((s) => {
    setStatus(s);
    setChoice((current) => current || s.resource_id || s.aurora[0] || "");
  }).catch((e) => setMessage((e as Error).message));
  useEffect(() => { void load(); }, []);
  const setup = async () => {
    setBusy(true); setMessage("");
    try {
      const result = await api.setupAgentStore(choice);
      setMessage(`Agent memory is ready on ${result.resource_id} (${result.mode}).`);
      await load();
    } catch (e) { setMessage((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="settings-card" aria-label="Agent memory">
      <div className="field-label">Agent memory</div>
      {!status ? <p className="settings-caption">Checking…</p> : <>
        <p className="settings-caption">
          {status.ready
            ? <>Conversations are stored in <strong>{status.resource_id}</strong>.</>
            : status.resource_id
              ? <>Configured for <strong>{status.resource_id}</strong>, but its storage tables are missing.</>
              : <>Not set up: the Agent can't keep conversation history until you choose an Aurora datasource.</>}
        </p>
        {!status.from_environment && (!status.ready || status.aurora.length > 1) && (
          <div className="join-row">
            <select aria-label="Agent memory datasource" value={choice} onChange={(e) => setChoice(e.target.value)}>
              {status.aurora.length === 0 && <option value="">No Aurora datasource available</option>}
              {status.aurora.map((id) => <option key={id} value={id}>{id}</option>)}
            </select>
            <button className="primary" disabled={!choice || busy || (status.ready && choice === status.resource_id)}
                    onClick={() => void setup()}>{busy ? "Setting up…" : "Set up agent memory"}</button>
          </div>
        )}
        <p className="settings-caption">Creates an internal <code>_studio_agent</code> schema (hidden from tables, SQL
          and joins). It keeps the database's existing permissions, so other readers of that database can read
          stored conversations. API keys are never stored there.</p>
      </>}
      {message && <p role="status">{message}</p>}
    </div>
  );
}
