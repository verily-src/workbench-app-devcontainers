import { useEffect, useState } from "react";
import type { Dataset } from "../types";

interface Props {
  datasets: Dataset[];
  busy: boolean;
  onJoin: (p: { leftId: string; rightId: string; leftOn: string;
                rightOn: string; how: string }) => void;
  onClose: () => void;
}

const HOWS = ["inner", "left", "right", "outer"];

export function JoinPanel({ datasets, busy, onJoin, onClose }: Props) {
  const [leftId, setLeftId] = useState(datasets[0]?.id ?? "");
  const [rightId, setRightId] = useState(datasets[1]?.id ?? "");
  const [leftOn, setLeftOn] = useState("");
  const [rightOn, setRightOn] = useState("");
  const [how, setHow] = useState("inner");

  const left = datasets.find((d) => d.id === leftId);
  const right = datasets.find((d) => d.id === rightId);
  const leftCols = left?.columns.map((c) => c.name) ?? [];
  const rightCols = right?.columns.map((c) => c.name) ?? [];

  // Default the keys to a shared column name when one exists.
  useEffect(() => {
    const shared = leftCols.find((c) => rightCols.includes(c));
    setLeftOn((v) => (leftCols.includes(v) ? v : shared ?? leftCols[0] ?? ""));
    setRightOn((v) => (rightCols.includes(v) ? v : shared ?? rightCols[0] ?? ""));
  }, [leftId, rightId]); // eslint-disable-line react-hooks/exhaustive-deps

  const canJoin = left && right && leftId !== rightId && leftOn && rightOn;

  return (
    <div className="join-panel">
      <div className="join-row">
        <label>Left
          <select value={leftId} onChange={(e) => setLeftId(e.target.value)}>
            {datasets.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
          </select>
        </label>
        <label>on key
          <select value={leftOn} onChange={(e) => setLeftOn(e.target.value)}>
            {leftCols.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
      </div>
      <div className="join-row">
        <label>Right
          <select value={rightId} onChange={(e) => setRightId(e.target.value)}>
            {datasets.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
          </select>
        </label>
        <label>on key
          <select value={rightOn} onChange={(e) => setRightOn(e.target.value)}>
            {rightCols.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
      </div>
      <div className="join-row">
        <label>Join type
          <select value={how} onChange={(e) => setHow(e.target.value)}>
            {HOWS.map((h) => <option key={h}>{h}</option>)}
          </select>
        </label>
        <div style={{ flex: 1 }} />
        <button className="primary" disabled={!canJoin || busy}
                onClick={() => onJoin({ leftId, rightId, leftOn, rightOn, how })}>
          {busy ? "Joining…" : "Join into new tab"}
        </button>
        <button className="quiet" onClick={onClose}>✕</button>
      </div>
      {leftId === rightId && (
        <div className="settings-hint">Pick two different tables to join.</div>
      )}
    </div>
  );
}
