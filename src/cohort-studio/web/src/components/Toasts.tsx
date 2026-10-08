import type { Toast } from "../workflowAlerts";

export function Toasts({ toasts, onDismiss }:
    { toasts: Toast[]; onDismiss: (id: string) => void }) {
  if (toasts.length === 0) return null;
  return (
    <div className="toast-stack">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.tone}`}>
          <span className={`toast-dot toast-dot-${t.tone}`} />
          <div className="toast-body">
            <div className="toast-title">{t.title}</div>
            <div className="toast-text">{t.body}</div>
          </div>
          <button className="quiet" onClick={() => onDismiss(t.id)}>✕</button>
        </div>
      ))}
    </div>
  );
}
