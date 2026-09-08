import { useRef, useEffect, useState, type CSSProperties } from "react";
import { useParams } from "react-router-dom";
import { useChat } from "../hooks/useChat";
import type { ChatMessageData } from "../types/chat";

/* ── Styles ─────────────────────────────────────────────────────────────── */

const overlay: CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0,0,0,0.25)",
  zIndex: 900,
};

const panel: CSSProperties = {
  position: "fixed",
  top: 0,
  right: 0,
  bottom: 0,
  width: 420,
  maxWidth: "100vw",
  background: "#fff",
  boxShadow: "-4px 0 24px rgba(0,0,0,0.12)",
  zIndex: 910,
  display: "flex",
  flexDirection: "column",
};

const header: CSSProperties = {
  background: "var(--wb-primary, #1a5c5e)",
  color: "#fff",
  padding: "14px 18px",
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  fontSize: 15,
  fontWeight: 600,
};

const msgArea: CSSProperties = {
  flex: 1,
  overflow: "auto",
  padding: "16px 14px",
  display: "flex",
  flexDirection: "column",
  gap: 12,
};

const inputBar: CSSProperties = {
  borderTop: "1px solid var(--wb-border, #dde)",
  padding: "10px 14px",
  display: "flex",
  gap: 8,
  alignItems: "flex-end",
};

/* ── Toggle button ──────────────────────────────────────────────────────── */

const fabStyle: CSSProperties = {
  position: "fixed",
  bottom: 24,
  right: 24,
  zIndex: 800,
  width: 52,
  height: 52,
  borderRadius: "50%",
  background: "var(--wb-primary, #1a5c5e)",
  color: "#fff",
  border: "none",
  fontSize: 22,
  cursor: "pointer",
  boxShadow: "0 4px 14px rgba(0,0,0,0.18)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
};

export function ChatToggleButton(props: { onClick: () => void }) {
  return (
    <button style={fabStyle} onClick={props.onClick} title="Open chat">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    </button>
  );
}

/* ── Message bubble ─────────────────────────────────────────────────────── */

function MessageBubble({ msg }: { msg: ChatMessageData }) {
  const isUser = msg.role === "user";
  const [copied, setCopied] = useState(false);

  const bubbleStyle: CSSProperties = {
    maxWidth: "85%",
    alignSelf: isUser ? "flex-end" : "flex-start",
    background: isUser ? "var(--wb-primary, #1a5c5e)" : "#f4f6f8",
    color: isUser ? "#fff" : "#222",
    padding: "10px 14px",
    borderRadius: isUser ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
    fontSize: 13.5,
    lineHeight: 1.55,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  };

  const copySQL = () => {
    if (msg.sql) {
      navigator.clipboard.writeText(msg.sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <div style={bubbleStyle}>
      <div dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }} />
      {msg.sql && (
        <div style={{ marginTop: 8, background: isUser ? "rgba(0,0,0,0.15)" : "#e8ecef", borderRadius: 6, padding: "8px 10px", fontSize: 12, fontFamily: "monospace" }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <span style={{ fontWeight: 600, fontSize: 11, opacity: 0.7 }}>SQL</span>
            <button onClick={copySQL} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: isUser ? "#ddd" : "#666" }}>
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
          <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{msg.sql}</pre>
        </div>
      )}
    </div>
  );
}

function renderMarkdown(text: string): string {
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, _lang, code) => `<pre style="background:#e8ecef;padding:8px;border-radius:4px;overflow-x:auto;font-size:12px">${code}</pre>`);
  html = html.replace(/`([^`]+)`/g, '<code style="background:#e8ecef;padding:1px 4px;border-radius:3px;font-size:12px">$1</code>');
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\n/g, "<br/>");
  return html;
}

/* ── Main panel ─────────────────────────────────────────────────────────── */

export default function ChatPanel(props: { open: boolean; onClose: () => void }) {
  const { messages, loading, error, mode, sendMessage, clearChat, toggleMode } = useChat();
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const params = useParams<{ project?: string; dataset?: string; table?: string }>();

  const fqTable = params.project && params.dataset && params.table
    ? `${params.project}.${params.dataset}.${params.table}`
    : null;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (!props.open) return null;

  const handleSend = () => {
    if (!input.trim() || loading) return;
    sendMessage(input.trim(), fqTable);
    setInput("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <>
      <div style={overlay} onClick={props.onClose} />
      <div style={panel}>
        {/* Header */}
        <div style={header}>
          <div>
            <span>Chat</span>
            {fqTable && (
              <span style={{ fontSize: 11, opacity: 0.75, marginLeft: 8 }}>
                {fqTable.split(".").pop()}
              </span>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button
              onClick={toggleMode}
              style={{
                background: mode === "agent" ? "#ffc107" : "rgba(255,255,255,0.2)",
                color: mode === "agent" ? "#000" : "#fff",
                border: "none",
                borderRadius: 12,
                padding: "3px 10px",
                fontSize: 11,
                cursor: "pointer",
                fontWeight: 600,
              }}
              title={mode === "metadata" ? "Switch to Agent mode (SQL execution)" : "Switch to Metadata Q&A mode"}
            >
              {mode === "metadata" ? "Q&A" : "Agent"}
            </button>
            <button onClick={clearChat} style={{ background: "none", border: "none", color: "#fff", cursor: "pointer", fontSize: 14 }} title="Clear chat">
              Clear
            </button>
            <button onClick={props.onClose} style={{ background: "none", border: "none", color: "#fff", cursor: "pointer", fontSize: 18, lineHeight: 1 }} title="Close">
              &times;
            </button>
          </div>
        </div>

        {/* Messages */}
        <div style={msgArea}>
          {messages.length === 0 && (
            <div style={{ color: "#999", textAlign: "center", marginTop: 60, fontSize: 13 }}>
              {fqTable
                ? `Ask anything about ${fqTable.split(".").pop()}`
                : "Ask about your datasets and tables"}
              <br />
              <span style={{ fontSize: 11, opacity: 0.7 }}>
                Mode: {mode === "metadata" ? "Metadata Q&A" : "Agent (SQL execution)"}
              </span>
            </div>
          )}
          {messages.map((m, i) => (
            <MessageBubble key={i} msg={m} />
          ))}
          {loading && (
            <div style={{ alignSelf: "flex-start", color: "#999", fontSize: 13, padding: "4px 10px" }}>
              Thinking...
            </div>
          )}
          {error && !loading && (
            <div style={{ color: "#c00", fontSize: 12, padding: "4px 10px" }}>{error}</div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div style={inputBar}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={mode === "agent" ? "Ask a question or request a SQL query..." : "Ask about your data..."}
            rows={2}
            style={{
              flex: 1,
              resize: "none",
              border: "1px solid var(--wb-border, #dde)",
              borderRadius: 8,
              padding: "8px 12px",
              fontSize: 13,
              fontFamily: "inherit",
              outline: "none",
            }}
            disabled={loading}
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            style={{
              background: "var(--wb-primary, #1a5c5e)",
              color: "#fff",
              border: "none",
              borderRadius: 8,
              padding: "8px 16px",
              fontSize: 13,
              fontWeight: 600,
              cursor: loading || !input.trim() ? "not-allowed" : "pointer",
              opacity: loading || !input.trim() ? 0.5 : 1,
            }}
          >
            Send
          </button>
        </div>
      </div>
    </>
  );
}
