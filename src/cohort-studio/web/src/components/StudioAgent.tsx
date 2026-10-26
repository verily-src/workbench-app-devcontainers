import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type {
  AgentDashboardAction, AgentWorkflowPlan, ChatHistory,
} from "../api";
import type { ChatMsg } from "../types";
import "./StudioAgent.css";

interface Props {
  onOpenDashboard: (action: AgentDashboardAction) => void;
}

interface AgentMessage extends Omit<ChatMsg, "actions"> {
  toolCalls?: string[];
  actions?: AgentDashboardAction[];
  workflowPlans?: AgentWorkflowPlan[];
}

interface RunState {
  status: string;
  error?: string;
  resultsLocation?: string;
}

function safeError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  if (/insufficient.*credit|credit balance|billing/i.test(message))
    return "The AI provider needs more credits. Check provider billing in Settings.";
  if (/unauthori[sz]ed|invalid api.?key|authentication|\b401\b/i.test(message))
    return "The AI provider rejected its key. Check the saved key in Settings.";
  if (/rate.?limit|\b429\b/i.test(message))
    return "The AI provider rate limit was reached. Wait a moment and try again.";
  if (/timeout|timed out/i.test(message))
    return "The request timed out. Try again with a shorter message.";
  return "The request could not be completed. Check the connection and try again.";
}

function isPolling(status: string): boolean {
  return ["APPROVED", "QUEUED", "RUNNING", "SUBMITTING", "SUBMITTED", "PENDING", "IN_PROGRESS"]
    .includes(status.toUpperCase());
}

function statusLabel(state: RunState | undefined, plan: AgentWorkflowPlan): string {
  return state?.status ?? plan.status;
}

export function StudioAgent({ onOpenDashboard }: Props) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [input, setInput] = useState("");
  const [restoring, setRestoring] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [before, setBefore] = useState<number | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [runs, setRuns] = useState<Record<string, RunState>>({});
  const inFlight = useRef(new Set<string>());
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    api.agentChatHistory().then((history: ChatHistory) => {
      if (cancelled) return;
      setSessionId(history.session_id ?? undefined);
      setMessages(history.messages.map((message) => ({
        role: message.role, content: message.content,
      })));
      setBefore(history.has_more ? history.next_before_message_id : null);
    }).catch((caught) => {
      if (!cancelled) setError(safeError(caught));
    }).finally(() => {
      if (!cancelled) setRestoring(false);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length, busy]);

  useEffect(() => {
    const pending = Object.entries(runs).filter(([, run]) => isPolling(run.status));
    if (!pending.length) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      for (const [id] of pending) {
        api.agentWorkflowStatus(id).then((result) => {
          if (cancelled) return;
          setRuns((current) => ({ ...current, [id]: {
            status: result.run?.status ?? result.status,
            resultsLocation: result.results_location ?? current[id]?.resultsLocation,
            error: result.error ? safeError(new Error(result.error)) : undefined,
          } }));
        }).catch((caught) => {
          if (!cancelled) setRuns((current) => ({ ...current, [id]: {
            ...current[id], error: safeError(caught),
          } }));
        });
      }
    }, 1500);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [runs]);

  const send = async () => {
    const message = input.trim();
    if (!message || busy || restoring) return;
    setInput("");
    setBusy(true);
    setError("");
    setMessages((current) => [...current, { role: "user", content: message }]);
    try {
      const result = await api.agentChat(message, sessionId);
      setSessionId(result.session_id);
      setMessages((current) => [...current, {
        role: "assistant", content: result.reply,
        toolCalls: result.tool_calls, actions: result.actions,
        workflowPlans: result.workflow_plans,
      }]);
    } catch (caught) {
      const detail = safeError(caught);
      setError(detail);
      setMessages((current) => [...current, {
        role: "assistant", content: detail,
      }]);
    } finally {
      setBusy(false);
    }
  };

  const loadEarlier = async () => {
    if (before === null || loadingOlder) return;
    setLoadingOlder(true);
    try {
      const history = await api.agentChatHistory(sessionId, before);
      setMessages((current) => [...history.messages.map((message) => ({
        role: message.role, content: message.content,
      })), ...current]);
      setBefore(history.has_more ? history.next_before_message_id : null);
    } catch (caught) {
      setError(safeError(caught));
    } finally {
      setLoadingOlder(false);
    }
  };

  const runWorkflow = async (plan: AgentWorkflowPlan) => {
    if (plan.status !== "ready" || inFlight.current.has(plan.id)) return;
    inFlight.current.add(plan.id);
    setRuns((current) => ({ ...current, [plan.id]: { status: "submitting" } }));
    try {
      const result = await api.approveAgentWorkflow(plan.id);
      setRuns((current) => ({ ...current, [plan.id]: {
        status: result.run?.status ?? result.status,
        resultsLocation: result.results_location ?? undefined,
        error: result.error
          ? safeError(new Error(result.error)) : undefined,
      } }));
    } catch (caught) {
      setRuns((current) => ({ ...current, [plan.id]: {
        status: "failed", error: safeError(caught),
      } }));
    } finally {
      inFlight.current.delete(plan.id);
    }
  };

  return (
    <section className="studio-agent" aria-label="Studio Agent">
      <header className="studio-agent-head">
        <div>
          <h1>Studio Agent</h1>
          <p>Ask for cohort analysis, dashboards, or a workflow plan.</p>
        </div>
        {restoring && <span role="status">Loading conversation…</span>}
      </header>

      <div className="studio-agent-messages" ref={scrollRef} aria-live="polite">
        {before !== null && <button type="button" className="quiet"
          disabled={loadingOlder} onClick={() => void loadEarlier()}>
          {loadingOlder ? "Loading…" : "Earlier messages"}
        </button>}
        {messages.length === 0 && !restoring && (
          <p className="studio-agent-empty">Describe the question or analysis you need.</p>
        )}
        {messages.map((message, index) => (
          <article key={`${index}-${message.role}`} className={`studio-agent-message ${message.role}`}>
            <div className="studio-agent-bubble">{message.content}</div>
            {message.toolCalls && message.toolCalls.length > 0 && (
              <div className="studio-agent-tools" aria-label="Completed steps">
                <strong>Completed steps</strong>
                <ul>{message.toolCalls.map((tool, i) => <li key={`${tool}-${i}`}>{tool}</li>)}</ul>
              </div>
            )}
            {message.actions?.map((action, i) => (
              <div className="studio-agent-card" key={`${action.title}-${i}`}>
                <strong>{action.title}</strong>
                <span>{action.dataset.rows.toLocaleString()} rows</span>
                <button type="button" className="primary"
                  onClick={() => onOpenDashboard(action)}>Open dashboard</button>
              </div>
            ))}
            {message.workflowPlans?.map((plan) => {
              const run = runs[plan.id];
              const label = statusLabel(run, plan);
              const blocked = plan.status !== "ready";
              return (
                <div className="studio-agent-card workflow-plan" key={plan.id}>
                  <strong>Review workflow: {plan.workflow}</strong>
                  <span>Status: {label}</span>
                  <span>{plan.rows.toLocaleString()} input rows</span>
                  <span>Required columns: {plan.required_columns.join(", ") || "None"}</span>
                  {plan.column_mapping && Object.keys(plan.column_mapping).length > 0 && (
                    <div className="studio-agent-column-mapping" aria-label="Column mapping">
                      <strong>Column mapping</strong>
                      {Object.entries(plan.column_mapping).map(([canonical, actual]) => (
                        <code key={canonical}>{canonical} → {actual}</code>
                      ))}
                    </div>
                  )}
                  {plan.output_path && <span>Output: {plan.output_resource_id}/{plan.output_path}</span>}
                  {blocked && plan.errors.length > 0 && (
                    <ul>{plan.errors.map((item, i) => <li key={i}>{item}</li>)}</ul>
                  )}
                  {run?.error && <p role="alert">{run.error}</p>}
                  {run?.resultsLocation && <span>Results: {run.resultsLocation}</span>}
                  <button type="button" className="primary"
                    disabled={blocked || Boolean(run) || busy}
                    onClick={() => void runWorkflow(plan)}>
                    {run ? "Workflow submitted" : blocked ? "Blocked" : "Run workflow"}
                  </button>
                </div>
              );
            })}
          </article>
        ))}
        {busy && <div className="studio-agent-message assistant" role="status">
          <div className="studio-agent-bubble">Working…</div>
        </div>}
      </div>

      {error && <p className="studio-agent-error" role="alert">{error}</p>}
      <form className="studio-agent-input" onSubmit={(event) => {
        event.preventDefault(); void send();
      }}>
        <textarea aria-label="Message the Studio Agent"
          placeholder="What would you like to analyze?" value={input}
          maxLength={8000} disabled={busy || restoring}
          onChange={(event) => setInput(event.target.value)} />
        <button type="submit" className="primary"
          disabled={busy || restoring || !input.trim()}>
          {busy ? "Working…" : "Send"}
        </button>
      </form>
    </section>
  );
}
