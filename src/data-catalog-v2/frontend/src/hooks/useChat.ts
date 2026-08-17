import { useState, useCallback } from "react";
import type { ChatMessageData, ChatResponse } from "../types/chat";

export type ChatMode = "metadata" | "agent";

export function useChat() {
  const [messages, setMessages] = useState<ChatMessageData[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<ChatMode>("metadata");
  const [error, setError] = useState<string | null>(null);

  const sendMessage = useCallback(
    async (text: string, fqTable?: string | null) => {
      if (!text.trim()) return;
      setError(null);

      const userMsg: ChatMessageData = {
        role: "user",
        content: text,
        timestamp: new Date().toISOString(),
        mode,
      };
      setMessages((prev) => [...prev, userMsg]);
      setLoading(true);

      try {
        const body: Record<string, unknown> = {
          message: text,
          mode,
        };
        if (fqTable) body.fq_table = fqTable;
        if (sessionId) body.session_id = sessionId;

        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });

        if (!res.ok) {
          const errBody = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(errBody.detail || `Chat failed: ${res.status}`);
        }

        const data: ChatResponse = await res.json();
        setSessionId(data.session_id);
        setMessages((prev) => [...prev, data.message]);
      } catch (e: any) {
        setError(e.message || "Chat request failed");
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: `Error: ${e.message || "Request failed"}`,
            timestamp: new Date().toISOString(),
            mode,
          },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [mode, sessionId],
  );

  const clearChat = useCallback(async () => {
    if (sessionId) {
      await fetch("/api/chat/clear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      }).catch(() => {});
    }
    setMessages([]);
    setSessionId(null);
    setError(null);
  }, [sessionId]);

  const toggleMode = useCallback(() => {
    setMode((m) => (m === "metadata" ? "agent" : "metadata"));
  }, []);

  return { messages, loading, error, mode, sessionId, sendMessage, clearChat, toggleMode, setMode };
}
