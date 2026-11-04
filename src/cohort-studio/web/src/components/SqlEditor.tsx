import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import "./SqlEditor.css";

const KEYWORDS = new Set(("select from where and or not in is null as group by order having limit offset with "
  + "union all distinct case when then else end join inner left right full outer cross on exists between "
  + "like ilike asc desc cast over partition using natural lateral filter within interval true false "
  + "except intersect nulls first last coalesce").split(" "));

type Token = { text: string; kind: "kw" | "fn" | "str" | "ident" | "num" | "comment" | "op" | "plain" };

// PostgreSQL strings: dollar-quoted ($$…$$, $tag$…$tag$), escape (E'…\''…'), standard ('…''…').
const TOKEN = /(--[^\n]*|\/\*[\s\S]*?(?:\*\/|$))|(\$([A-Za-z_][A-Za-z0-9_]*)?\$[\s\S]*?(?:\$\3\$|$)|[Ee]'(?:\\[\s\S]|''|[^'\\])*'?|'(?:[^']|'')*'?)|("(?:[^"]|"")*"?)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_$]*)|([<>=!]+|[-+*/%|(),.;:])|(\s+|.)/g;

export function tokenize(sql: string): Token[] {
  const tokens: Token[] = [];
  let match: RegExpExecArray | null;
  TOKEN.lastIndex = 0;
  while ((match = TOKEN.exec(sql)) !== null) {
    const [text, comment, str, , ident, num, word, op] = match;
    if (comment) tokens.push({ text, kind: "comment" });
    else if (str) tokens.push({ text, kind: "str" });
    else if (ident) tokens.push({ text, kind: "ident" });
    else if (num) tokens.push({ text, kind: "num" });
    else if (word) {
      const next = sql.slice(TOKEN.lastIndex).match(/^\s*\(/);
      tokens.push({ text, kind: KEYWORDS.has(word.toLowerCase()) ? "kw" : next ? "fn" : "plain" });
    } else if (op) tokens.push({ text, kind: "op" });
    else tokens.push({ text, kind: "plain" });
  }
  return tokens;
}

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

export function SqlEditor({ value, onChange, disabled, placeholder, label = "SQL query" }: {
  value: string; onChange: (value: string) => void; disabled?: boolean;
  placeholder?: string; label?: string;
}) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const layer = useRef<HTMLPreElement>(null);
  const [lint, setLint] = useState<Lint | null>(null);
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
  const sync = () => {
    if (textarea.current && layer.current) {
      layer.current.scrollTop = textarea.current.scrollTop;
      layer.current.scrollLeft = textarea.current.scrollLeft;
    }
  };
  const status = !value.trim() ? null : lint ? { ok: lint.ok, text: lint.ok ? lint.message
        : `${lint.line ? `Line ${lint.line}${lint.col ? `:${lint.col}` : ""} — ` : ""}${lint.message}${lint.detail ? ` (${lint.detail})` : ""}` }
      : local ? { ok: false, text: local } : { ok: true, text: "Checking…", pending: true };
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
        <textarea ref={textarea} className="join-sql-editor sql-editor-input" aria-label={label}
                  value={value} disabled={disabled} spellCheck={false} placeholder={placeholder}
                  onScroll={sync} onChange={(event) => onChange(event.target.value)} />
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
