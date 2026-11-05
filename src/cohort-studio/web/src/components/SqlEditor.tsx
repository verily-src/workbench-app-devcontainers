import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { api } from "../api";
import type { SqlCompletions } from "../types";
import { complete, type CompletionResult } from "./sqlComplete";
import { tokenize, type Token } from "./sqlTokens";
import "./SqlEditor.css";

export { tokenize };

/** Instant client checks the server parser reports less precisely. */
export function quickLint(sql: string): string | null {
  let depth = 0;
  for (const token of tokenize(sql)) {
    if (token.kind === "str" && !token.text.startsWith("$")
        && (token.text.length < 2 || !token.text.endsWith("'")))
      return "Unclosed string literal (').";
    if (token.kind === "str" && token.text.startsWith("$")) {
      const tag = token.text.match(/^\$[A-Za-z0-9_]*\$/)?.[0] ?? "$$";
      if (token.text.length < tag.length * 2 || !token.text.endsWith(tag))
        return `Unclosed dollar-quoted string (${tag}).`;
    }
    if (token.kind === "ident" && (token.text.length < 2 || !token.text.endsWith('"')))
      return 'Unclosed quoted identifier (").';
    if (token.kind === "op") {
      if (token.text === "(") depth += 1;
      if (token.text === ")") depth -= 1;
      if (depth < 0) return "Unmatched closing parenthesis.";
    }
  }
  return depth > 0 ? `${depth} unclosed parenthesis${depth > 1 ? "es" : ""}.` : null;
}

type Lint = Awaited<ReturnType<typeof api.lintSql>>;

// Schema metadata per resource, shared by every editor; the server caches too.
const CATALOG_TTL_MS = 5 * 60_000;
const catalogs = new Map<string, { at: number; promise: Promise<SqlCompletions | null> }>();
function loadCatalog(resourceId: string): Promise<SqlCompletions | null> {
  const hit = catalogs.get(resourceId);
  if (hit && Date.now() - hit.at < CATALOG_TTL_MS) return hit.promise;
  const promise = api.sqlCompletions(resourceId).catch(() => {
    catalogs.delete(resourceId);
    return null;
  });
  catalogs.set(resourceId, { at: Date.now(), promise });
  return promise;
}

type Popup = CompletionResult & { index: number };

export function SqlEditor({ value, onChange, disabled, placeholder, label = "SQL query", resourceId }: {
  value: string; onChange: (value: string) => void; disabled?: boolean;
  placeholder?: string; label?: string;
  /** Aurora/PostgreSQL resource whose schemas, tables and columns to suggest. */
  resourceId?: string;
}) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const layer = useRef<HTMLPreElement>(null);
  const mirror = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const pendingCaret = useRef<number | null>(null);
  const listId = useId();
  const [lint, setLint] = useState<Lint | null>(null);
  const [catalog, setCatalog] = useState<SqlCompletions | null>(null);
  const [popup, setPopup] = useState<Popup | null>(null);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const local = useMemo(() => (value.trim() ? quickLint(value) : null), [value]);
  useEffect(() => {
    setLint(null);
    if (!value.trim()) return;
    // The server check is authoritative; the instant client check only shows
    // until it answers (it can't parse every PostgreSQL form).
    let current = true;
    const timer = setTimeout(() => {
      api.lintSql(value).then((result) => { if (current) setLint(result); }).catch(() => undefined);
    }, 400);
    return () => { current = false; clearTimeout(timer); };
  }, [value]);
  useEffect(() => { setCatalog(null); }, [resourceId]);
  const ensureCatalog = useCallback(() => {
    if (!resourceId || catalog?.resource_id === resourceId) return;
    void loadCatalog(resourceId).then((result) => {
      if (result && result.resource_id === resourceId) setCatalog(result);
    });
  }, [resourceId, catalog]);
  const errorLine = lint && !lint.ok ? lint.line : undefined;
  const lines = useMemo(() => {
    const out: Token[][] = [[]];
    for (const token of tokenize(value)) {
      const parts = token.text.split("\n");
      parts.forEach((part, i) => {
        if (i > 0) out.push([]);
        if (part) out[out.length - 1].push({ ...token, text: part });
      });
    }
    return out;
  }, [value]);

  // True while the user is typing a word the popup should follow, even when
  // nothing matched yet (metadata may still be loading).
  const wanted = useRef<"" | "typing" | "forced">("");
  const suggest = (text: string, caret: number, force = false) => {
    wanted.current = force ? "forced" : "typing";
    const result = complete(text, caret, catalog, force);
    setPopup(result ? { ...result, index: 0 } : null);
  };
  const close = () => { wanted.current = ""; setPopup(null); };
  // Metadata that arrives while typing refreshes the suggestions.
  useEffect(() => {
    const el = textarea.current;
    if (catalog && el && document.activeElement === el && wanted.current) {
      suggest(el.value, el.selectionStart, wanted.current === "forced");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog]);

  // Caret coordinates from a hidden copy of the text laid out like the
  // textarea. offsetTop/offsetLeft are in the same (zoomed) CSS pixels as the
  // popup, so Display-size zoom needs no conversion.
  const measure = useCallback(() => {
    const el = textarea.current, copy = mirror.current;
    if (!el || !copy || !popup) { setPosition(null); return; }
    const style = getComputedStyle(el);
    const borders = parseFloat(style.borderLeftWidth) + parseFloat(style.borderRightWidth);
    copy.style.width = `${el.clientWidth + borders}px`;
    copy.textContent = el.value.slice(0, popup.start);
    const marker = document.createElement("span");
    marker.textContent = "​";
    copy.appendChild(marker);
    const lineTop = el.clientTop + marker.offsetTop - el.scrollTop;
    const lineBottom = lineTop + marker.offsetHeight;
    const width = list.current?.offsetWidth ?? 280;
    const left = Math.max(0, Math.min(el.clientLeft + marker.offsetLeft - el.scrollLeft,
                                      el.offsetWidth - width));
    // Just below the caret line, kept within the editor when the caret is scrolled away.
    setPosition({ top: Math.max(el.clientTop, Math.min(lineBottom, el.offsetHeight)), left });
  }, [popup]);
  useLayoutEffect(() => { measure(); }, [measure, value]);
  useLayoutEffect(() => {
    if (pendingCaret.current !== null && textarea.current) {
      textarea.current.setSelectionRange(pendingCaret.current, pendingCaret.current);
      pendingCaret.current = null;
    }
  }, [value]);
  useEffect(() => {
    list.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [popup?.index, popup]);

  const accept = (index: number) => {
    if (!popup) return;
    const item = popup.items[index];
    const el = textarea.current;
    if (!item || !el) return;
    const text = el.value;
    const next = text.slice(0, popup.start) + item.insert + text.slice(popup.end);
    pendingCaret.current = popup.start + item.insert.length - (item.caretBack ?? 0);
    close();
    onChange(next);
    el.focus();
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    const el = event.currentTarget;
    if (event.ctrlKey && (event.code === "Space" || event.key === " ")) {
      event.preventDefault();
      ensureCatalog();
      suggest(el.value, el.selectionStart, true);
      return;
    }
    if (!popup) return;
    const count = popup.items.length;
    const plain = !event.shiftKey && !event.altKey && !event.metaKey && !event.ctrlKey;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setPopup({ ...popup, index: (popup.index + step + count) % count });
    } else if ((event.key === "Enter" || event.key === "Tab") && plain && count) {
      event.preventDefault();
      accept(popup.index);
    } else if (event.key === "Escape") {
      // Close only the popup, not a surrounding dialog.
      event.preventDefault();
      event.stopPropagation();
      event.nativeEvent.stopImmediatePropagation();
      close();
    } else if (["ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"].includes(event.key)) {
      close();
    }
  };

  const sync = () => {
    if (textarea.current && layer.current) {
      layer.current.scrollTop = textarea.current.scrollTop;
      layer.current.scrollLeft = textarea.current.scrollLeft;
    }
    if (popup) measure();
  };
  const status = !value.trim() ? null : lint ? { ok: lint.ok, text: lint.ok ? lint.message
        : `${lint.line ? `Line ${lint.line}${lint.col ? `:${lint.col}` : ""} — ` : ""}${lint.message}${lint.detail ? ` (${lint.detail})` : ""}` }
      : local ? { ok: false, text: local } : { ok: true, text: "Checking…", pending: true };
  const open = !!popup && popup.items.length > 0;
  const optionId = (index: number) => `${listId}-option-${index}`;
  return (
    <div className="sql-editor">
      <div className="sql-editor-area">
        <pre ref={layer} className="sql-editor-layer join-sql-editor" aria-hidden="true">
          {lines.map((line, i) => (
            <div key={i} className={errorLine === i + 1 ? "sql-line-error" : undefined}>
              {line.length ? line.map((token, j) => <span key={j} className={`sql-${token.kind}`}>{token.text}</span>) : "​"}
            </div>
          ))}
        </pre>
        <div ref={mirror} className="join-sql-editor sql-editor-mirror" aria-hidden="true" />
        <textarea ref={textarea} className="join-sql-editor sql-editor-input" aria-label={label}
                  value={value} disabled={disabled} spellCheck={false} placeholder={placeholder}
                  aria-autocomplete="list"
                  aria-controls={open ? listId : undefined}
                  aria-activedescendant={open ? optionId(popup!.index) : undefined}
                  onScroll={sync} onFocus={ensureCatalog} onBlur={close} onClick={close} onKeyDown={onKeyDown}
                  onChange={(event) => {
                    const el = event.target;
                    const input = event.nativeEvent as InputEvent;
                    const typed = input.inputType === "insertText" && /[A-Za-z0-9_."]$/.test(input.data ?? "");
                    if (popup || typed || (wanted.current && input.inputType?.startsWith("delete"))) {
                      ensureCatalog();
                      suggest(el.value, el.selectionStart);
                    }
                    onChange(el.value);
                  }} />
        {open && (
          <ul ref={list} id={listId} role="listbox" aria-label="SQL suggestions" className="sql-complete"
              style={position ? { top: position.top, left: position.left } : { visibility: "hidden" }}
              onMouseDown={(event) => event.preventDefault()}>
            {popup!.items.map((item, index) => (
              <li key={`${item.kind}:${item.label}`} id={optionId(index)} role="option"
                  aria-selected={index === popup!.index}
                  className={`sql-complete-item sql-complete-${item.kind}`}
                  onMouseMove={() => { if (index !== popup!.index) setPopup({ ...popup!, index }); }}
                  onClick={() => accept(index)}>
                <span className="sql-complete-icon" aria-hidden="true">{ICONS[item.kind]}</span>
                <span className="sql-complete-label">{item.label}</span>
                {item.detail && <span className="sql-complete-detail">{item.detail}</span>}
              </li>
            ))}
          </ul>
        )}
      </div>
      {status && (
        <div className={`sql-editor-status ${status.ok ? "ok" : "error"}`} role="status" aria-label="SQL check">
          <span>{status.ok ? ("pending" in status ? "…" : "✓") : "✗"} {status.text}</span>
          {lint?.ok && lint.formatted && lint.formatted !== value && (
            <button type="button" className="link" disabled={disabled}
                    onClick={() => onChange(lint.formatted!)}>Format SQL</button>
          )}
        </div>
      )}
    </div>
  );
}

const ICONS = { keyword: "K", function: "ƒ", schema: "S", table: "T", column: "C" } as const;
