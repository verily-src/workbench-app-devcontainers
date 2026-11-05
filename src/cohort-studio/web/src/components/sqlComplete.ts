import type { SqlCompletions } from "../types";
import { KEYWORDS, tokenize, type Token } from "./sqlTokens";

/** Completion engine for the SQL editor: plain functions over the text, the
 *  caret and the resource's schema metadata (no parser, no dependencies). */

export type CompletionKind = "keyword" | "function" | "schema" | "table" | "column";
export type Completion = {
  label: string; insert: string; kind: CompletionKind; detail?: string;
  /** Characters to move the caret back after inserting (inside `()`). */
  caretBack?: number;
};
export type CompletionResult = { start: number; end: number; items: Completion[] };

const KEYWORD_ITEMS = [...KEYWORDS].filter((word) => word !== "coalesce" && word !== "by")
  .concat(["group by", "order by", "partition by", "left join", "inner join"]);
// Mirrors sql_source._SAFE_FUNCTIONS: only functions the server accepts.
const FUNCTIONS = ("abs array_agg array_to_string avg btrim ceil coalesce concat concat_ws count "
  + "date_part date_trunc extract floor greatest json_agg json_build_object jsonb_agg jsonb_build_object "
  + "least left length ln log lower ltrim max min mod nullif power regexp_match regexp_replace replace "
  + "right round rtrim sign split_part sqrt stddev stddev_pop stddev_samp string_agg sum to_char "
  + "to_date to_number to_timestamp trim unnest upper var_pop var_samp variance").split(" ");
// PostgreSQL reserved words: identifiers spelled like these need quotes.
const RESERVED = new Set(("all analyse analyze and any array as asc asymmetric both case cast check "
  + "collate column constraint create current_catalog current_date current_role current_time "
  + "current_timestamp current_user default deferrable desc distinct do else end except false fetch "
  + "for foreign from grant group having in initially intersect into lateral leading limit localtime "
  + "localtimestamp not null offset on only or order placing primary references returning select "
  + "session_user some symmetric system_user table then to trailing true union unique user using "
  + "variadic when where window with authorization binary collation concurrently cross current_schema "
  + "freeze full ilike inner is isnull join left like natural notnull outer overlaps right similar "
  + "tablesample verbose").split(" "));
const CLAUSES = new Set(["select", "from", "join", "where", "on", "by", "having", "using", "limit",
  "offset", "union", "intersect", "except", "with", "returning", "set", "values", "window"]);
const COLUMN_CLAUSES = new Set(["select", "where", "on", "by", "having", "using"]);
const FROM_END = new Set(["where", "group", "order", "having", "limit", "offset", "union", "intersect",
  "except", "window", "select", "on", "using", "returning", "fetch", "for"]);
const AFTER_TABLE = new Set(["as", "join", "inner join", "left join", "inner", "left", "right", "full",
  "outer", "cross", "natural", "lateral", "on", "using", "where", "group by", "order by", "having", "limit",
  "offset", "union", "except", "intersect"]);
const MAX_ITEMS = 50;

export function quoteIdent(name: string, force = false): string {
  if (!force && /^[a-z_][a-z0-9_$]*$/.test(name) && !RESERVED.has(name)) return name;
  return `"${name.replace(/"/g, '""')}"`;
}

type Positioned = Token & { start: number; end: number };

function positioned(sql: string): Positioned[] {
  let at = 0;
  return tokenize(sql).map((token) => {
    const item = { ...token, start: at, end: at + token.text.length };
    at = item.end;
    return item;
  });
}

const isWord = (t: Positioned | undefined) =>
  !!t && (t.kind === "kw" || t.kind === "fn" || t.kind === "plain") && /^[A-Za-z_]/.test(t.text);
const isName = (t: Positioned | undefined) => !!t && (isWord(t) || t.kind === "ident");
const lower = (t: Positioned | undefined) => (t && isWord(t) ? t.text.toLowerCase() : "");
/** PostgreSQL identifier semantics: unquoted names fold to lower case. */
const identName = (t: Positioned) => t.kind === "ident"
  ? t.text.replace(/^"|"$/g, "").replace(/""/g, '"') : t.text.toLowerCase();

function closedString(token: Positioned): boolean {
  if (token.kind === "comment") return token.text.startsWith("/*") && token.text.length > 3
    && token.text.endsWith("*/");
  if (token.text.startsWith("$")) {
    const tag = token.text.match(/^\$[A-Za-z0-9_]*\$/)?.[0] ?? "$$";
    return token.text.length >= tag.length * 2 && token.text.endsWith(tag);
  }
  return token.text.length >= 2 && token.text.endsWith("'") && !/^[Ee]'$/.test(token.text);
}

type TableRef = { schema?: string; table: string; alias?: string };

/** FROM/JOIN table references and their aliases anywhere in the query. */
export function tableRefs(sql: string): TableRef[] {
  const sig = positioned(sql).filter((t) => t.kind !== "comment" && !/^\s+$/.test(t.text));
  const refs: TableRef[] = [];
  let inFrom = false;
  for (let i = 0; i < sig.length; i++) {
    const word = lower(sig[i]);
    if (FROM_END.has(word)) inFrom = false;
    const starts = word === "from" || word === "join" || (inFrom && sig[i].text === ",");
    if (word === "from") inFrom = true;
    if (!starts || !isName(sig[i + 1])) continue;
    const parts = [sig[i + 1]];
    let j = i + 2;
    while (sig[j]?.text === "." && isName(sig[j + 1])) { parts.push(sig[j + 1]); j += 2; }
    if (parts.length > 3) continue;
    const ref: TableRef = { table: identName(parts[parts.length - 1]) };
    if (parts.length >= 2) ref.schema = identName(parts[parts.length - 2]);
    if (lower(sig[j]) === "as") j += 1;
    const alias = sig[j];
    if (alias && (alias.kind === "ident" || (isWord(alias) && alias.kind !== "kw"
        && !FROM_END.has(lower(alias)) && !["join", "inner", "left", "right", "full", "cross",
          "natural", "lateral"].includes(lower(alias))))) ref.alias = identName(alias);
    refs.push(ref);
  }
  return refs;
}

type Table = SqlCompletions["tables"][number];

function findTable(catalog: SqlCompletions | null, ref: { schema?: string; table: string }): Table | undefined {
  if (!catalog) return undefined;
  const matches = catalog.tables.filter((t) => t.name === ref.table && (!ref.schema || t.schema === ref.schema));
  return matches.find((t) => t.schema === "public") ?? matches[0];
}

function matchCase(word: string, prefix: string) {
  return prefix && prefix === prefix.toLowerCase() ? word : word.toUpperCase();
}

function columnItems(tables: Table[], quoted: boolean): Completion[] {
  const seen = new Map<string, { type: string; tables: string[] }>();
  for (const table of tables) {
    for (const column of table.columns) {
      const known = seen.get(column.name);
      if (known) known.tables.push(table.name);
      else seen.set(column.name, { type: column.type, tables: [table.name] });
    }
  }
  return [...seen].map(([name, { type, tables: owners }]) => ({
    label: name, insert: quoteIdent(name, quoted), kind: "column" as const,
    detail: `${type} · ${owners.length > 2 ? `${owners.length} tables` : owners.join(", ")}`,
  }));
}

function tableItems(tables: Table[], qualified: boolean, quoted: boolean): Completion[] {
  return tables.map((t) => ({
    label: qualified ? `${t.schema}.${t.name}` : t.name,
    insert: qualified ? `${quoteIdent(t.schema)}.${quoteIdent(t.name)}` : quoteIdent(t.name, quoted),
    kind: "table" as const,
    detail: [t.kind, t.omop ? "OMOP" : "", `${t.columns.length} col${t.columns.length === 1 ? "" : "s"}`]
      .filter(Boolean).join(" · "),
  }));
}

function schemaItems(catalog: SqlCompletions, quoted: boolean): Completion[] {
  return catalog.schemas.map((s) => ({
    label: s.name, insert: quoteIdent(s.name, quoted), kind: "schema" as const,
    detail: s.omop ? (s.omop.role === "cdm" ? `schema · OMOP CDM${s.omop.default ? " (default)" : ""}`
      : "schema · OMOP vocabulary") : "schema",
  }));
}

function keywordItems(prefix: string): Completion[] {
  return KEYWORD_ITEMS.map((word) => ({ label: matchCase(word, prefix), insert: matchCase(word, prefix),
                                        kind: "keyword" as const }));
}

function functionItems(prefix: string): Completion[] {
  return FUNCTIONS.map((name) => {
    const text = matchCase(name, prefix);
    return { label: `${text}()`, insert: `${text}()`, kind: "function" as const, caretBack: 1, detail: "function" };
  });
}

function rank(items: Completion[], prefix: string): Completion[] {
  const needle = prefix.toLowerCase();
  if (!needle) return items.slice(0, MAX_ITEMS);
  const starts: Completion[] = [], contains: Completion[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    const label = item.label.toLowerCase();
    const key = `${item.kind}:${label}`;
    if (seen.has(key) || item.insert.toLowerCase() === needle) continue;
    const short = label.includes(".") ? label.slice(label.lastIndexOf(".") + 1) : label;
    if (label.startsWith(needle) || short.startsWith(needle)) { starts.push(item); seen.add(key); }
    else if (needle.length >= 2 && label.includes(needle)) { contains.push(item); seen.add(key); }
  }
  return starts.concat(contains).slice(0, MAX_ITEMS);
}

/** Suggestions for the caret position, or null when none apply (inside a
 *  string or comment, after a number, or nothing typed and not forced). */
export function complete(sql: string, caret: number, catalog: SqlCompletions | null,
                         force = false): CompletionResult | null {
  const tokens = positioned(sql);
  const at = tokens.findIndex((t) => t.start < caret && caret <= t.end);
  const current = at >= 0 ? tokens[at] : undefined;
  if (current && (current.kind === "comment" || current.kind === "str")
      && (caret < current.end || current.text.startsWith("--") || !closedString(current))) return null;
  let start = caret, end = caret, prefix = "", quoted = false;
  if (current && isWord(current)) {
    start = current.start; end = current.end; prefix = sql.slice(start, caret);
  } else if (current && current.kind === "ident" && (current.text.length < 2 || !current.text.endsWith('"'))) {
    // An unclosed quoted identifier runs to the end of the text: complete up to the caret only.
    start = current.start; end = caret; prefix = current.text.slice(1, caret - current.start); quoted = true;
  } else if (current && current.kind === "ident" && caret === current.end) {
    return null; // just closed a quoted identifier
  } else if (current && (current.kind === "num" || (current.kind === "plain" && /[A-Za-z0-9_$]/.test(current.text)))) {
    return null;
  }
  const before = tokens.filter((t) => t.end <= start && t.kind !== "comment" && !/^\s+$/.test(t.text));
  const prev = before[before.length - 1];

  // Qualifier: `name.` or `schema.table.` right before the word.
  const qualifier: Positioned[] = [];
  for (let i = before.length - 1; before[i]?.text === "." && isName(before[i - 1]); i -= 2) {
    qualifier.unshift(before[i - 1]);
  }
  if (!prefix && !force && !qualifier.length) return null;
  const refs = tableRefs(sql);
  let items: Completion[];

  if (qualifier.length) {
    const names = qualifier.map(identName);
    const last = names[names.length - 1];
    const aliased = names.length === 1 ? refs.find((r) => r.alias === last) : undefined;
    const schema = names.length === 1 && !aliased ? catalog?.schemas.find((s) => s.name === last) : undefined;
    if (schema) {
      items = tableItems(catalog!.tables.filter((t) => t.schema === schema.name), false, quoted);
    } else {
      const ref = aliased ?? (names.length >= 2 ? { schema: names[names.length - 2], table: last }
        : refs.find((r) => r.table === last && !r.alias) ?? { table: last });
      const table = findTable(catalog, ref);
      items = table ? columnItems([table], quoted) : [];
    }
    const ranked = rank(items, prefix);
    return ranked.length ? { start, end, items: ranked } : null;
  }

  // Clause the caret is in: the nearest clause keyword at this paren depth.
  let clause = "", depth = 0;
  for (let i = before.length - 1; i >= 0; i--) {
    const token = before[i];
    if (token.text === ")") depth += 1;
    else if (token.text === "(") { if (depth > 0) depth -= 1; }
    else if (depth === 0 && CLAUSES.has(lower(token))) { clause = lower(token); break; }
  }
  const prevWord = lower(prev);
  const tableContext = prevWord === "from" || prevWord === "join"
    || (prev?.text === "," && clause === "from");
  if (tableContext) {
    items = catalog ? [...schemaItems(catalog, quoted), ...tableItems(catalog.tables, true, quoted)] : [];
  } else if (COLUMN_CLAUSES.has(clause) && !quoted) {
    const scoped = refs.map((r) => findTable(catalog, r)).filter((t): t is Table => !!t);
    const columns = columnItems(scoped.length ? [...new Set(scoped)] : catalog?.tables ?? [], quoted);
    const aliases: Completion[] = refs.filter((r) => r.alias).map((r) => ({
      label: r.alias!, insert: quoteIdent(r.alias!), kind: "table", detail: `alias · ${r.table}` }));
    items = [...columns, ...aliases, ...keywordItems(prefix), ...functionItems(prefix)];
  } else if (COLUMN_CLAUSES.has(clause)) {
    const scoped = refs.map((r) => findTable(catalog, r)).filter((t): t is Table => !!t);
    items = columnItems(scoped.length ? [...new Set(scoped)] : catalog?.tables ?? [], quoted);
  } else if (clause === "from" || clause === "join") {
    // After a table reference: an alias or what can follow it.
    items = quoted ? [] : keywordItems(prefix).filter((k) => AFTER_TABLE.has(k.label.toLowerCase()));
  } else {
    items = quoted ? [] : keywordItems(prefix);
  }
  const ranked = rank(items, prefix);
  return ranked.length ? { start, end, items: ranked } : null;
}
