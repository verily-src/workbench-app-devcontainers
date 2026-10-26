import type { StudioAgentResponse } from "./api";

export interface AgentProgress {
  type: string;
  run_id?: string;
  stage?: string;
  tool_name?: string;
  turn?: number;
  reply?: string;
  session_id?: string;
}

export async function streamAgent(message: string, sessionId: string | undefined,
  newSession: boolean, onProgress: (event: AgentProgress) => void,
  signal: AbortSignal): Promise<StudioAgentResponse | null> {
  const response = await fetch("/api/agent/chat/stream", {
    method: "POST", headers: { "Content-Type": "application/json" }, signal,
    body: JSON.stringify({ message, ...(sessionId ? { session_id: sessionId } : {}),
      new_session: newSession }),
  });
  if (!response.ok || !response.body) throw new Error(`Agent request failed (${response.status}).`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let result: StudioAgentResponse | null = null;
  let ended = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      let newline: number;
      while ((newline = pending.indexOf("\n")) >= 0) {
        const line = pending.slice(0, newline);
        pending = pending.slice(newline + 1);
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === "error") throw new Error(event.message);
        if (event.type === "result") result = event.result;
        if (event.type === "end") ended = true;
        onProgress(event);
      }
    }
    if (!ended) throw new Error("Agent connection ended before completion.");
    return result;
  } finally {
    reader.releaseLock();
  }
}

export async function cancelAgent(runId: string) {
  const response = await fetch(`/api/agent/chat/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
  });
  if (!response.ok) throw new Error("Could not request cancellation. The run may have finished.");
}
