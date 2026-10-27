import { AgentText } from "./AgentText";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { streamAgent, cancelAgent } from "../agentStreaming";
import type {
  AgentDashboardAction, AgentWorkflowPlan, AgentWorkflowVerification, ChatHistory,
} from "../api";
import type { ChatMsg } from "../types";
import { AgentIntegrations } from "./AgentIntegrations";
import "./StudioAgent.css";

const CLOSED_SESSION_IDS_KEY = "cohort-studio-agent-closed-session-ids";

interface AgentChatSession {
  session_id: string;
  title: string;
  updated_at: string;
}

function storedClosedSessionIds(): string[] {
  try {
    const raw = window.localStorage.getItem(CLOSED_SESSION_IDS_KEY);
    const values: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(values) ? [...new Set(values.filter((value): value is string =>
      typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)))].slice(0, 20) : [];
  } catch {
    return [];
  }
}

interface Props {
  onOpenSettings: () => void;
  onOpenDashboard: (action: AgentDashboardAction,
                     verification?: AgentWorkflowVerification) => void;
}

interface AgentMessage extends Omit<ChatMsg, "actions"> {
  toolCalls?: string[];
  toolResults?: { name: string; status: "completed" | "failed" }[];
  limitReached?: boolean;
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

export function StudioAgent({ onOpenSettings, onOpenDashboard }: Props) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [sessions, setSessions] = useState<AgentChatSession[]>([]);
  const [closedSessionIds, setClosedSessionIds] = useState<string[]>(storedClosedSessionIds);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [newSessionPending, setNewSessionPending] = useState(false);
  const [input, setInput] = useState("");
  const [restoring, setRestoring] = useState(true);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [queuedMessages, setQueuedMessages] = useState<{ id: number; text: string }[]>([]);
  const [queuePaused, setQueuePaused] = useState(false);
  const nextQueuedId = useRef(0);
  const [progressText, setProgressText] = useState("");
  const [runId, setRunId] = useState<string>();
  const [cancelling, setCancelling] = useState(false);
  const streamController = useRef<AbortController | null>(null);
  const celebrationTimer = useRef<number | undefined>(undefined);
  const [celebrating, setCelebrating] = useState(false);
  const [dancing, setDancing] = useState(false);
  const [driving, setDriving] = useState(false);
  const [chaseScene, setChaseScene] = useState<"chase" | "rescue" | "flee">("chase");
  useEffect(() => () => streamController.current?.abort(), []);
  useEffect(() => () => window.clearTimeout(celebrationTimer.current), []);
  useEffect(() => {
    setDancing(false);
    setDriving(false);
    setChaseScene("chase");
    if (busy || celebrating) return;
    let timer: number, driveTimer: number, rescueTimer: number, fleeTimer: number;
    const reset = () => {
      setDancing(false); setDriving(false); setChaseScene("chase");
      window.clearTimeout(timer); window.clearTimeout(driveTimer);
      window.clearTimeout(rescueTimer); window.clearTimeout(fleeTimer);
      timer = window.setTimeout(() => setDancing(true), 10000);
      driveTimer = window.setTimeout(() => { setDancing(false); setDriving(true); }, 30000);
      rescueTimer = window.setTimeout(() => setChaseScene("rescue"), 120000);
      fleeTimer = window.setTimeout(() => setChaseScene("flee"), 130000);
    };
    const events = ["pointerdown", "pointermove", "keydown", "wheel", "touchstart"] as const;
    events.forEach(name => window.addEventListener(name, reset, { passive: true }));
    reset();
    return () => { window.clearTimeout(timer); window.clearTimeout(driveTimer); window.clearTimeout(rescueTimer); window.clearTimeout(fleeTimer); events.forEach(name => window.removeEventListener(name, reset)); };
  }, [busy, celebrating]);
  const [error, setError] = useState("");
  const [before, setBefore] = useState<number | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [plans, setPlans] = useState<AgentWorkflowPlan[]>([]);
  const [legacyPlans, setLegacyPlans] = useState<AgentWorkflowPlan[] | null>(null);
  const [plansLoading, setPlansLoading] = useState(true);
  const [planUi, setPlanUi] = useState<Record<string, PlanUiState>>({});
  const inFlight = useRef(new Set<string>());
  const scrollRef = useRef<HTMLDivElement>(null);
  const conversationRequest = useRef(0);
  const sessionsRequest = useRef(0);

  const refreshSessions = async () => {
    const requestId = ++sessionsRequest.current;
    try {
      const { sessions: available } = await api.agentChatSessions();
      if (requestId === sessionsRequest.current) setSessions(available);
      return available;
    } finally {
      if (requestId === sessionsRequest.current) setSessionsLoading(false);
    }
  };

  useEffect(() => {
    try { window.localStorage.setItem(CLOSED_SESSION_IDS_KEY, JSON.stringify(closedSessionIds.slice(0, 50))); }
    catch {}
  }, [closedSessionIds]);

  useEffect(() => {
    let cancelled = false;
    api.agentChatHistory().then((history: ChatHistory) => {
      if (cancelled) return;
      const restoredId = history.session_id ?? undefined;
      if (restoredId && closedSessionIds.includes(restoredId)) {
        setSessionId(undefined);
        setNewSessionPending(true);
        setMessages([]);
        setBefore(null);
        return;
      }
      setSessionId(restoredId);
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
    void refreshSessions().catch((caught) => {
      if (!cancelled) setError(safeError(caught));
    });
    return () => { cancelled = true; sessionsRequest.current += 1; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setPlans([]);
    setPlanUi({});
    if (!sessionId || newSessionPending) { setPlansLoading(false); return; }
    setPlansLoading(true);
    api.agentWorkflowPlans(sessionId).then((result) => {
      if (!cancelled) setPlans(result.plans);
    }).catch((caught) => {
      if (!cancelled) setError(safeError(caught));
    }).finally(() => {
      if (!cancelled) setPlansLoading(false);
    });
    return () => { cancelled = true; };
  }, [sessionId, newSessionPending]);

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

  const runMessage = async (message: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    window.clearTimeout(celebrationTimer.current);
    setCelebrating(false);
    setBusy(true);
    setError("");
    setMessages((current) => [...current, { role: "user", content: message }]);
    try {
      const controller = new AbortController();
      streamController.current = controller;
      setProgressText("Starting…");
      setCancelling(false);
      const result = await streamAgent(message, sessionId, newSessionPending, (event) => {
        if (event.type === "started") setRunId(event.run_id);
        if (event.type === "progress") {
          if (event.stage === "model_start") setProgressText("Planning next step…");
          if (event.stage === "tool_start") setProgressText(`Running ${(event.tool_name ?? "tool").replaceAll("_", " ")}…`);
          if (event.stage === "tool_end") setProgressText("Step finished.");
        }
        if (event.type === "cancelled") {
          setQueuePaused(true);
          if (event.session_id) { setSessionId(event.session_id); setNewSessionPending(false); }
          setMessages((current) => [...current, { role: "assistant", content: event.reply ?? "Stopped." }]);
          void refreshSessions().catch((caught) => setError(safeError(caught)));
        }
      }, controller.signal);
      if (!result) { setQueuePaused(true); return; }
      setCelebrating(true);
      celebrationTimer.current = window.setTimeout(() => setCelebrating(false), 1800);
      if (result.workflow_plans?.some((plan) => plan.status === "ready")) setQueuePaused(true);
      setSessionId(result.session_id);
      setNewSessionPending(false);
      void refreshSessions()
        .catch((caught) => setError(safeError(caught)));
      setPlans((current) => mergePlans(current, result.workflow_plans));
      setMessages((current) => [...current, {
        role: "assistant", content: result.reply,
        toolCalls: result.tool_calls, toolResults: result.tool_results,
        limitReached: result.limit_reached, actions: result.actions,
      }]);
    } catch (caught) {
      setQueuePaused(true);
      const detail = safeError(caught);
      setError(detail);
      setMessages((current) => [...current, {
        role: "assistant", content: detail,
      }]);
    } finally {
      busyRef.current = false;
      setBusy(false);
      setRunId(undefined);
      setProgressText("");
      setCancelling(false);
      streamController.current = null;
    }
  };

  const send = () => {
    const message = input.trim();
    if (!message || restoring || queuedMessages.length >= 10) return;
    setInput("");
    if (busyRef.current || queuedMessages.length) {
      setQueuedMessages((current) => [...current, { id: ++nextQueuedId.current, text: message }]);
    } else {
      setQueuePaused(false);
      void runMessage(message);
    }
  };

  useEffect(() => {
    if (busy || busyRef.current || queuePaused || restoring || !queuedMessages.length) return;
    const next = queuedMessages[0];
    setQueuedMessages((current) => current.slice(1));
    void runMessage(next.text);
  }, [busy, queuePaused, restoring, queuedMessages, sessionId, newSessionPending]);

  const clearToNewConversation = () => {
    conversationRequest.current += 1;
    setSessionId(undefined);
    setNewSessionPending(true);
    setMessages([]);
    setPlans([]);
    setPlanUi({});
    setBefore(null);
    setInput("");
    setError("");
  };

  const startNewConversation = () => {
    if (busy || restoring || loadingOlder || queuedMessages.length) return;
    clearToNewConversation();
  };

  const selectConversation = async (id: string) => {
    if (!id) {
      startNewConversation();
      return;
    }
    if (id === sessionId || busy || restoring || loadingOlder || queuedMessages.length) return;
    const requestId = ++conversationRequest.current;
    setRestoring(true);
    setError("");
    setPlans([]);
    setPlanUi({});
    try {
      const history = await api.agentChatHistory(id);
      if (requestId !== conversationRequest.current) return;
      const restoredId = history.session_id ?? id;
      setSessionId(restoredId);
      setNewSessionPending(false);
      setMessages(history.messages.map((message) => ({
        role: message.role, content: message.content,
      })));
      setBefore(history.has_more ? history.next_before_message_id : null);
      setInput("");
    } catch (caught) {
      if (requestId === conversationRequest.current) setError(safeError(caught));
    } finally {
      if (requestId === conversationRequest.current) setRestoring(false);
    }
  };

  const closeConversation = (id: string) => {
    if (busy || restoring || loadingOlder || queuedMessages.length) return;
    const next = sessions.find((session) => session.session_id !== id
      && !closedSessionIds.includes(session.session_id));
    setClosedSessionIds((current) => current.includes(id) ? current : [...current, id].slice(-50));
    if (sessionId === id) {
      clearToNewConversation();
      if (next) void selectConversation(next.session_id);
    }
  };

  const reopenConversation = (id: string) => {
    if (busy || restoring || loadingOlder || queuedMessages.length) return;
    setClosedSessionIds((current) => current.filter((closedId) => closedId !== id));
    void selectConversation(id);
  };

  const loadEarlier = async () => {
    if (before === null || loadingOlder || restoring || busy) return;
    const requestId = conversationRequest.current;
    setLoadingOlder(true);
    try {
      const history = await api.agentChatHistory(sessionId, before);
      if (requestId !== conversationRequest.current) return;
      setMessages((current) => [...history.messages.map((message) => ({
        role: message.role, content: message.content,
      })), ...current]);
      setBefore(history.has_more ? history.next_before_message_id : null);
    } catch (caught) {
      if (requestId === conversationRequest.current) setError(safeError(caught));
    } finally {
      if (requestId === conversationRequest.current) setLoadingOlder(false);
    }
  };

  const runWorkflow = async (plan: AgentWorkflowPlan) => {
    if (plan.status !== "ready" || inFlight.current.has(plan.id)) return;
    inFlight.current.add(plan.id);
    setPlanUi((current) => ({ ...current, [plan.id]: { working: true } }));
    setPlans((current) => current.some((item) => item.id === plan.id) ? mergePlans(current, [{ ...plan, status: "submitting" }]) : current);
    setLegacyPlans((current) => current?.some((item) => item.id === plan.id) ? mergePlans(current, [{ ...plan, status: "submitting" }]) : current);
    try {
      const result = await api.approveAgentWorkflow(plan.id);
      setPlans((current) => current.some((item) => item.id === plan.id) ? mergePlans(current, [result]) : current);
      setLegacyPlans((current) => current?.some((item) => item.id === plan.id) ? mergePlans(current, [result]) : current);
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
      setPlans((current) => current.some((item) => item.id === plan.id) ? mergePlans(current, [result]) : current);
      setLegacyPlans((current) => current?.some((item) => item.id === plan.id) ? mergePlans(current, [result]) : current);
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

  const openSessions = sessions.filter((session) => !closedSessionIds.includes(session.session_id));
  const closedSessions = sessions.filter((session) => closedSessionIds.includes(session.session_id));
  const currentTitle = sessions.find((session) => session.session_id === sessionId)?.title;

  return (
    <section className="studio-agent" aria-label="Studio Agent">
      <aside className="studio-agent-sidebar" aria-label="Conversations">
        <button type="button" className="primary studio-agent-new-chat"
          disabled={busy || restoring || loadingOlder || queuedMessages.length > 0} onClick={startNewConversation}>
          New chat
        </button>
        <div className="studio-agent-session-heading">
          <h2>Chats</h2>
          {sessionsLoading && <span role="status">Loading…</span>}
        </div>
        <nav className="studio-agent-session-list" aria-label="Open chats">
          {openSessions.map((session) => (
            <div className="studio-agent-session-row" key={session.session_id}>
              <button type="button" className="studio-agent-session-link"
                aria-current={session.session_id === sessionId ? "page" : undefined}
                disabled={busy || restoring || loadingOlder || queuedMessages.length > 0}
                onClick={() => void selectConversation(session.session_id)}>
                <span>{session.title || "Untitled conversation"}</span>
              </button>
              <button type="button" className="studio-agent-session-close"
                aria-label={`Close ${session.title || "conversation"}`}
                title="Close chat" disabled={busy || restoring || loadingOlder || queuedMessages.length > 0}
                onClick={() => closeConversation(session.session_id)}>×</button>
            </div>
          ))}
          {!sessionsLoading && openSessions.length === 0 && (
            <p className="studio-agent-empty-list">No open chats</p>
          )}
        </nav>
        {closedSessions.length > 0 && <details className="studio-agent-closed-list">
          <summary>Closed chats ({closedSessions.length})</summary>
          <nav aria-label="Closed chats">
            {closedSessions.map((session) => (
              <div className="studio-agent-session-row" key={session.session_id}>
                <span className="studio-agent-session-name">{session.title || "Untitled conversation"}</span>
                <button type="button" className="studio-agent-session-reopen"
                  disabled={busy || restoring || loadingOlder || queuedMessages.length > 0}
                  onClick={() => reopenConversation(session.session_id)}>Open</button>
              </div>
            ))}
          </nav>
        </details>}
        <AgentIntegrations onOpenSettings={onOpenSettings} />
      </aside>

      <div className="studio-agent-workspace">
        <header className="studio-agent-head">
          <div className="studio-agent-identity">
            <picture aria-hidden="true" className="studio-agent-avatar">
              <source media="(prefers-reduced-motion: reduce)" srcSet="/mascot/still.webp" />
              <img src={busy ? "/mascot/thinking.webp" : celebrating ? "/mascot/greeting.webp" : dancing ? "/mascot/dance.webp" : "/mascot/idle.webp"} alt="" />
            </picture>
            <div>
              <h1>Studio Agent</h1>
              <p>{currentTitle || (newSessionPending ? "New chat" : "Start a conversation")}</p>
            </div>
          </div>
          {(restoring || plansLoading) && <span role="status">
            {restoring ? "Loading conversation…" : "Loading workflow plans…"}
          </span>}
        </header>

      <div className="studio-agent-messages" ref={scrollRef} aria-live="polite">
        {before !== null && <button type="button" className="quiet"
          disabled={loadingOlder || restoring || busy} onClick={() => void loadEarlier()}>
          {loadingOlder ? "Loading…" : "Earlier messages"}
        </button>}
        {messages.length === 0 && !restoring && (
          <p className="studio-agent-empty">Describe the question or analysis you need.</p>
        )}
        {messages.map((message, index) => (
          <article key={`${index}-${message.role}`} className={`studio-agent-message ${message.role}`}>
            <div className="studio-agent-bubble">{message.role === "assistant" ? <AgentText text={message.content} /> : message.content}</div>
            {message.toolResults && message.toolResults.length > 0 ? (
              <details className="studio-agent-tools" aria-label="Tool results">
                <summary>Tool results ({message.toolResults.length})</summary>
                <ul>{message.toolResults.map((tool, i) => <li key={`${tool.name}-${i}`}>
                  {tool.name} · {tool.status === "completed" ? "Completed" : "Failed"}
                </li>)}</ul>
              </details>
            ) : message.toolCalls && message.toolCalls.length > 0 ? (
              <details className="studio-agent-tools" aria-label="Tool calls">
                <summary>Tool calls · outcome not reported ({message.toolCalls.length})</summary>
                <ul>{message.toolCalls.map((tool, i) => <li key={`${tool}-${i}`}>{tool}</li>)}</ul>
              </details>
            ) : null}
            {message.limitReached && <p className="studio-agent-limit" role="status">
              The agent stopped before completing the request. Review the failed steps before retrying.
            </p>}
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

      <details className="studio-agent-legacy-plans" onToggle={(event) => {
        if (event.currentTarget.open && legacyPlans === null) {
          api.agentWorkflowPlans().then((result) => setLegacyPlans(result.plans.filter((plan) => !plan.session_id)))
            .catch((caught) => setError(safeError(caught)));
        }
      }}>
        <summary>Earlier workflow plans</summary>
        {legacyPlans === null ? <span>Loading…</span> : legacyPlans.length === 0 ? <span>None</span> :
          legacyPlans.map((plan) => <article className="studio-agent-card workflow-plan" key={plan.id}>
            <strong>Review workflow: {plan.workflow}</strong>
            <span>Status: {workflowStatus(plan)}</span>
            <span>{plan.rows.toLocaleString()} input rows</span>
            {plan.column_mapping && <div className="studio-agent-column-mapping"><strong>Column mapping</strong>
              {Object.entries(plan.column_mapping).map(([key, value]) => <code key={key}>{key} → {value}</code>)}</div>}
            {plan.output_path && <span>Planned output: {plan.output_resource_id}/{plan.output_path}</span>}
            {plan.errors.length > 0 && <ul>{plan.errors.map((item, i) => <li key={i}>{item}</li>)}</ul>}
            {planUi[plan.id]?.error && <p role="alert">{planUi[plan.id].error}</p>}
            {plan.status === "ready" && <button type="button" disabled={busy || planUi[plan.id]?.working}
              onClick={() => void runWorkflow(plan)}>Run workflow</button>}
            {plan.status === "submission_unknown" && <button type="button" disabled={busy || planUi[plan.id]?.working}
              onClick={() => void checkWorkflowRun(plan)}>Check run</button>}
            {isCompleted(plan) && <button type="button" disabled={busy || planUi[plan.id]?.working}
              onClick={() => void openResults(plan)}>Open results</button>}
          </article>)}
      </details>

      {error && <p className="studio-agent-error" role="alert">{error}</p>}
      {busy && <div role="status" aria-live="polite" className="studio-agent-progress">
        {cancelling ? "Stopping after the current operation…" : progressText}
      </div>}
      {queuedMessages.length > 0 && <div className="studio-agent-queued" aria-label="Queued messages">
        {queuedMessages.map((queued) => <div key={queued.id}>
          <span>Queued: {queued.text}</span>
          <button type="button" className="quiet" aria-label="Remove queued message"
            onClick={() => setQueuedMessages((current) => current.filter((item) => item.id !== queued.id))}>✕</button>
        </div>)}
        {queuePaused && <button type="button" onClick={() => setQueuePaused(false)}>Send queued messages</button>}
      </div>}
      <form className="studio-agent-input" onSubmit={(event) => {
        event.preventDefault(); send();
      }}>
        <textarea aria-label="Message the Studio Agent"
          placeholder="What would you like to analyze?" value={input}
          maxLength={8000} disabled={restoring}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              if (!event.repeat) send();
            }
          }}
          onChange={(event) => setInput(event.target.value)} />
        {busy && <button type="button" disabled={!runId || cancelling} onClick={async () => {
          if (!runId) return;
          setCancelling(true);
          try { await cancelAgent(runId); }
          catch { setCancelling(false); setError("Could not stop this run. Wait for its current operation to finish."); }
        }}>{cancelling ? "Stopping…" : "Cancel"}</button>}
        <button type="submit" className="primary"
          disabled={restoring || !input.trim() || queuedMessages.length >= 10}>{busy ? "Queue" : "Send"}</button>
      </form>
      </div>
      {driving && <div className="mascot-drive" aria-hidden="true">
        {chaseScene !== "rescue" && <img className="mascot-chaser" src="/mascot/godzilla-classic.png" alt="" />}
        <img className="mascot-truck" src="/mascot/cybertruck.png" alt="" />
        <img className="mascot-driver" src="/mascot/idle.webp" alt="" />
        {chaseScene === "flee" && <img className="mascot-wizard-rider" src="/mascot/gandalf.png" alt="" />}
        {chaseScene !== "rescue" && <><svg className="mascot-launcher" viewBox="0 0 60 20" focusable="false"><path d="M7 5h37v10H7z" fill="#63736b" stroke="#263e38" strokeWidth="2" /><path d="M44 3h8v14h-8z" fill="#31463d" /><path d="M8 4 2 2v16l6-2z" fill="#31463d" /><path d="M30 15h6v5h-6z" fill="#263e38" /></svg>
        <span className="mascot-shot" />
        <span className="mascot-bang">BANG!</span></>}
      </div>}
      {driving && chaseScene === "rescue" && <div className="mascot-rescue" aria-hidden="true">
        <img src="/mascot/gandalf.png" alt="" />
        <span className="mascot-magic" />
      </div>}
    </section>
  );
}
