import { useEffect, useState } from "react";

type Document = { id: string; title: string };
type Passage = { citation: string; title: string; text: string };

async function call<T>(path = "", body?: unknown, method = "GET"): Promise<T> {
  const response = await fetch(`/api/knowledge${path}`, {
    method, ...(body === undefined ? {} : {
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "Invalid knowledge-base request");
  return value;
}

export function KnowledgeBase() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Passage[]>([]);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = async () => setDocuments(await call<Document[]>());
  useEffect(() => { refresh().catch(e => setError(e.message)); }, []);
  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await action(); } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  return <section className="settings-card" aria-label="Knowledge base">
    <h2>Knowledge base</h2>
    <p>Shared within this app. Relevant passages are sent to your selected AI provider when you ask the assistant.</p>
    <label>Document title<input value={title} maxLength={200} onChange={e => setTitle(e.target.value)} /></label>
    <label>Document text<textarea value={text} maxLength={200000} rows={5} style={{ display: "block", width: "100%" }} onChange={e => setText(e.target.value)} /></label>
    <label>Upload text file<input type="file" accept=".txt,.md,.csv,.tsv" disabled={busy} onChange={e => {
      const file = e.target.files?.[0];
      if (file) void run(async () => {
        if (file.size > 200000) throw new Error("File limit is 200 KB.");
        const content = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
        setTitle(file.name); setText(content);
      });
      e.target.value = "";
    }} /></label>
    <button disabled={busy || !title.trim() || !text.trim()} onClick={() => void run(async () => {
      await call("", { title, text }, "POST"); setTitle(""); setText(""); await refresh();
    })}>Add document</button>
    <ul>{documents.map(document => <li key={document.id}>{document.title} <button disabled={busy}
      aria-label={`Remove ${document.title}`} onClick={() => void run(async () => {
        await call(`/${document.id}`, undefined, "DELETE"); setResults([]); await refresh();
      })}>Remove</button></li>)}</ul>
    <label>Search knowledge<input value={query} maxLength={1000} onChange={e => setQuery(e.target.value)} /></label>
    <button disabled={busy || !query.trim()} onClick={() => void run(async () => {
      setResults(await call<Passage[]>("/search", { query }, "POST")); setSearched(true);
    })}>Search documents</button>
    {searched && results.length === 0 && <p role="status">No matching passages.</p>}
    {results.map(p => <article key={p.citation}><h3>{p.title}</h3><code>{p.citation}</code><p style={{ whiteSpace: "pre-wrap" }}>{p.text}</p></article>)}
    {error && <p role="alert">{error}</p>}
  </section>;
}
