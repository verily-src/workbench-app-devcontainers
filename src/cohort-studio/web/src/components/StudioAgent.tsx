import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type {
  AgentDashboardAction, AgentWorkflowPlan, AgentWorkflowVerification, ChatHistory,
} from "../api";
import type { ChatMsg } from "../types";
import "./StudioAgent.css";

interface Props {
  onOpenDashboard: (action: AgentDashboardAction,
                     verification?: AgentWorkflowVerification) => void;
}

interface AgentMessage extends Omit<ChatMsg, "actions"> {
  toolCalls?: string[];
  actions?: AgentDashboardAction[];
}

interface PlanUiState {
  working?: boolean;
  error?: string;
  opening?: boolean;
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
  if (/could not be verified|verification/i.test(message))
    return "The workflow results could not be verified. No dashboard was opened.";
  return "The request could not be completed. Check the connection and try again.";
}

function isPolling(status: string): boolean {
  return ["APPROVED", "QUEUED", "RUNNING", "SUBMITTING", "SUBMITTED", "PENDING", "IN_PROGRESS"]
    .includes(status.toUpperCase());
}

function isCompleted(plan: AgentWorkflowPlan): boolean {
  return plan.status === "completed"
    || (plan.run?.status ?? "").toUpperCase() === "COMPLETED";
}

function workflowStatus(plan: AgentWorkflowPlan): string {
  if (plan.status === "submission_unknown") return "Submission needs checking";
  return plan.run?.status ?? plan.status;
}

function mergePlans(current: AgentWorkflowPlan[], incoming: AgentWorkflowPlan[]): AgentWorkflowPlan[] {
  const map = new Map(current.map((plan) => [plan.id, plan]));
  incoming.forEach((plan) => map.set(plan.id, { ...map.get(plan.id), ...plan }));
  return [...map.values()];
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
  const [plans, setPlans] = useState<AgentWorkflowPlan[]>([]);
  const [plansLoading, setPlansLoading] = useState(true);
  const [planUi, setPlanUi] = useState<Record<string, PlanUiState>>({});
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
    let cancelled = false;
    api.agentWorkflowPlans().then((result) => {
      if (!cancelled) setPlans(result.plans);
    }).catch((caught) => {
      if (!cancelled) setError(safeError(caught));
    }).finally(() => {
      if (!cancelled) setPlansLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages.length, busy]);

  useEffect(() => {
    const pending = plans.filter((plan) => isPolling(plan.status));
    if (!pending.length) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      for (const plan of pending) {
        api.agentWorkflowStatus(plan.id).then((result) => {
          if (cancelled) return;
          setPlans((current) => mergePlans(current, [result]));
        }).catch((caught) => {
          if (!cancelled) setPlanUi((current) => ({ ...current, [plan.id]: {
            ...current[plan.id], error: safeError(caught),
          } }));
        });
      }
    }, 1500);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [plans]);

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
      setPlans((current) => mergePlans(current, result.workflow_plans));
      setMessages((current) => [...current, {
        role: "assistant", content: result.reply,
        toolCalls: result.tool_calls, actions: result.actions,
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
    setPlanUi((current) => ({ ...current, [plan.id]: { working: true } }));
    setPlans((current) => mergePlans(current, [{ ...plan, status: "submitting" }]));
    try {
      const result = await api.approveAgentWorkflow(plan.id);
      setPlans((current) => mergePlans(current, [result]));
      setPlanUi((current) => ({ ...current, [plan.id]: { working: false } }));
    } catch (caught) {
      setPlanUi((current) => ({ ...current, [plan.id]: {
        working: false, error: safeError(caught),
      } }));
    } finally {
      inFlight.current.delete(plan.id);
    }
  };

  const checkWorkflowRun = async (plan: AgentWorkflowPlan) => {
    if (plan.status !== "submission_unknown" || inFlight.current.has(plan.id)) return;
    inFlight.current.add(plan.id);
    setPlanUi((current) => ({ ...current, [plan.id]: { working: true } }));
    try {
      const result = await api.agentWorkflowStatus(plan.id);
      setPlans((current) => mergePlans(current, [result]));
      setPlanUi((current) => ({ ...current, [plan.id]: { working: false } }));
    } catch (caught) {
      setPlanUi((current) => ({ ...current, [plan.id]: {
        working: false, error: safeError(caught),
      } }));
    } finally {
      inFlight.current.delete(plan.id);
    }
  };

  const openResults = async (plan: AgentWorkflowPlan) => {
    if (!isCompleted(plan) || inFlight.current.has(plan.id)) return;
    inFlight.current.add(plan.id);
    setPlanUi((current) => ({ ...current, [plan.id]: { working: true, opening: true } }));
    try {
      const result = await api.openAgentWorkflowResults(plan.id);
      if (!result.verification?.verified || !result.action) {
        throw new Error("The workflow results could not be verified. No dashboard was opened.");
      }
      onOpenDashboard(result.action, result.verification);
    } catch (caught) {
      setPlanUi((current) => ({ ...current, [plan.id]: {
        working: false, opening: false, error: safeError(caught),
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
        {(restoring || plansLoading) && <span role="status">
          {restoring ? "Loading conversation…" : "Loading workflow plans…"}
        </span>}
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
          </article>
        ))}
        {busy && <div className="studio-agent-message assistant" role="status">
          <div className="studio-agent-bubble">Working…</div>
        </div>}
      </div>

      {plans.length > 0 && (
        <section className="studio-agent-plans" aria-label="Workflow plans">
          <h2>Workflow plans</h2>
          {plans.map((plan) => {
            const ui = planUi[plan.id];
            const blocked = plan.status === "blocked";
            const completed = isCompleted(plan);
            const canRun = plan.status === "ready";
            const location = plan.results_location;
            return (
              <article className="studio-agent-card workflow-plan" key={plan.id}>
                <strong>Review workflow: {plan.workflow}</strong>
                <span>Status: {workflowStatus(plan)}</span>
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
                {plan.output_path && <span>Planned output: {plan.output_resource_id}/{plan.output_path}</span>}
                {location && <span>Run output: {location.output_bucket_resource
                  ?? location.output_bucket_uuid ?? "S3"}{location.output_bucket_path
                  ? `/${location.output_bucket_path}` : ""}</span>}
                {plan.errors.length > 0 && (
                  <ul>{plan.errors.map((item, i) => <li key={i}>{item}</li>)}</ul>
                )}
                {ui?.error && <p role="alert">{ui.error}</p>}
                {canRun && <button type="button" className="primary"
                  disabled={Boolean(ui?.working) || busy}
                  onClick={() => void runWorkflow(plan)}>
                  {ui?.working ? "Submitting…" : "Run workflow"}
                </button>}
                {plan.status === "submission_unknown" && <button type="button" className="primary"
                  disabled={Boolean(ui?.working) || busy}
                  onClick={() => void checkWorkflowRun(plan)}>
                  {ui?.working ? "Checking run…" : "Check run"}
                </button>}
                {blocked && <button type="button" className="primary" disabled>Blocked</button>}
                {completed && <button type="button" className="primary"
                  disabled={Boolean(ui?.working) || busy}
                  onClick={() => void openResults(plan)}>
                  {ui?.opening ? "Verifying results…" : "Open results"}
                </button>}
              </article>
            );
          })}
        </section>
      )}

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
