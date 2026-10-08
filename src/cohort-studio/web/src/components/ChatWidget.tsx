import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ChatMsg, Dataset } from "../types";

interface Props {
  dataset: Dataset;
  onUpdate: (changes: Partial<Dataset>) => void;
}

export function ChatWidget({ dataset, onUpdate }: Props) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const history = dataset.chat ?? [];

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [history.length, busy, open]);

  const send = async () => {
    const message = input.trim();
    if (!message || busy) return;
    setInput("");
    setBusy(true);
    const withUser: ChatMsg[] = [...history, { role: "user", content: message }];
    onUpdate({ chat: withUser });
    try {
      const out = await api.chat(dataset.id, message, history,
        dataset.filters, dataset.charts);
      onUpdate({
        filters: out.filters,
        charts: out.charts,
        chat: [...withUser, { role: "assistant", content: out.reply,
                              actions: out.actions }],
      });
    } catch (e) {
      onUpdate({
        chat: [...withUser, { role: "assistant",
          content: `Something went wrong: ${(e as Error).message}` }],
      });
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <button className="chat-launcher" onClick={() => setOpen(true)}>
        <SparkIcon /> Chat
      </button>
    );
  }

  return (
    <div className="chat-panel">
      <div className="chat-head">
        <SparkIcon />
        <span>Data assistant</span>
        <span className="chat-dataset">{dataset.title}</span>
        <div style={{ flex: 1 }} />
        <button className="quiet" onClick={() => setOpen(false)}>✕</button>
      </div>
      <div className="chat-messages" ref={scrollRef}>
        {history.length === 0 && (
          <div className="chat-hint">
            Ask about the data or have me build the view — e.g.
            {" "}<em>"what's the mean RIN by tissue?"</em>,
            {" "}<em>"show age vs RIN"</em>,
            {" "}<em>"filter to liver and plot the distribution"</em>.
          </div>
        )}
        {history.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            <div className="chat-bubble">{m.content}</div>
            {m.actions && m.actions.length > 0 && (
              <div className="chat-actions">
                {m.actions.map((a, j) => (
                  <span key={j} className="chip">{a}</span>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="chat-msg assistant">
            <div className="chat-bubble">
              <span className="activity"><span className="pulse" />Working…</span>
            </div>
          </div>
        )}
      </div>
      <div className="chat-input">
        <input
          type="text"
          placeholder="Ask about the data…"
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") send(); }}
          autoFocus
        />
        <button className="primary" onClick={send}
                disabled={busy || !input.trim()}>
          Send
        </button>
      </div>
    </div>
  );
}

function SparkIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth="2">
      <path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4L12 3z" />
    </svg>
  );
}
