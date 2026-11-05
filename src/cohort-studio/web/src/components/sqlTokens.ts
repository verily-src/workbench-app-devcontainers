export const KEYWORDS = new Set(("select from where and or not in is null as group by order having limit offset with "
  + "union all distinct case when then else end join inner left right full outer cross on exists between "
  + "like ilike asc desc cast over partition using natural lateral filter within interval true false "
  + "except intersect nulls first last coalesce").split(" "));

export type Token = { text: string; kind: "kw" | "fn" | "str" | "ident" | "num" | "comment" | "op" | "plain" };

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
