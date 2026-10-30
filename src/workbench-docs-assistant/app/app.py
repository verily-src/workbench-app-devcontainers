"""Workbench Docs Assistant: a chat UI over a documentation site, answered by Gemini on Vertex AI.

Everything runs inside the workspace's Google Cloud project: the docs are indexed in memory, and
model calls go to Vertex AI in that project using the app's default credentials.
"""

import html
import logging
import os
import re
import time

import google.auth
import markdown
from flask import Flask, jsonify, request, send_from_directory
from google.auth.transport.requests import AuthorizedSession

from docs_index import DocsIndex

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("app")

# ----- configuration (all optional) -----
# Precedence: per-instance VM metadata (wb app create gcp -M key=value) > environment variable
# (template option in docker-compose.yaml) > built-in default. Metadata lets one app config serve
# several deployments, each with its own title, model, or support contacts.
METADATA_URL = "http://metadata.google.internal/computeMetadata/v1/instance/attributes/"


def setting(env_name, default):
    metadata_key = env_name.lower().replace("_", "-")
    try:
        import requests
        resp = requests.get(METADATA_URL + metadata_key, headers={"Metadata-Flavor": "Google"}, timeout=1)
        if resp.status_code == 200 and resp.text.strip():
            return resp.text.strip()
    except Exception:
        pass
    return os.environ.get(env_name) or default


DOCS_BASE_URL = setting("DOCS_BASE_URL", "https://support.workbench.verily.com")
DOCS_PATH_PREFIX = setting("DOCS_PATH_PREFIX", "/docs/")
GEMINI_MODEL = setting("GEMINI_MODEL", "gemini-3.5-flash")
VERTEX_LOCATION = setting("VERTEX_LOCATION", "global")
EMBEDDING_MODEL = setting("EMBEDDING_MODEL", "text-embedding-005")
EMBEDDING_LOCATION = setting("EMBEDDING_LOCATION", "us-central1")
ASSISTANT_TITLE = setting("ASSISTANT_TITLE", "Workbench Docs Assistant")
SUPPORT_CONTACTS = setting("SUPPORT_CONTACTS", "Email workbench-support@verily.com")
INDEX_CACHE_DIR = setting("INDEX_CACHE_DIR", "/data/index")
INDEX_REFRESH_HOURS = float(setting("INDEX_REFRESH_HOURS", "24"))
TOP_K = int(setting("TOP_K", "8"))
MAX_HISTORY = int(setting("MAX_HISTORY", "8"))
MAX_QUESTION_CHARS = 2000

# ----- Google Cloud credentials: the app's default identity in the workspace project -----
credentials, adc_project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT") or adc_project
session = AuthorizedSession(credentials)


def _vertex_url(location, model, method):
    host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
    return f"https://{host}/v1/projects/{PROJECT}/locations/{location}/publishers/google/models/{model}:{method}"


def embed(texts, task_type):
    import numpy as np
    resp = session.post(_vertex_url(EMBEDDING_LOCATION, EMBEDDING_MODEL, "predict"),
                        json={"instances": [{"content": t, "task_type": task_type} for t in texts]}, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"embedding request failed ({resp.status_code}): {resp.text[:300]}")
    return np.array([p["embeddings"]["values"] for p in resp.json()["predictions"]], dtype="float32")


def generate(system_text, contents):
    body = {
        "systemInstruction": {"parts": [{"text": system_text}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1500},
    }
    resp = session.post(_vertex_url(VERTEX_LOCATION, GEMINI_MODEL, "generateContent"), json=body, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini request failed ({resp.status_code}): {resp.text[:400]}")
    data = resp.json()
    candidate = (data.get("candidates") or [{}])[0]
    parts = candidate.get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return text.strip(), data.get("usageMetadata", {})


SYSTEM_PROMPT = """You are the documentation assistant for Verily Workbench. You answer questions using ONLY the
documentation excerpts provided with each question.

Rules:
- Base every statement on the excerpts. Do not use outside knowledge about Workbench, and never invent
  CLI flags, menu names, or URLs.
- Cite the excerpts you used with bracketed numbers like [1] or [2][4], placed right after the sentence
  they support. Only cite excerpt numbers that exist.
- If the excerpts do not answer the question, say that the documentation you searched does not cover
  it, mention the closest related topic if there is one, and tell the user how to get help:
  {contacts}
- Be concise. Use numbered steps for procedures and code blocks for commands, copied exactly from the
  excerpts. Prefer the UI steps unless the user asks about the CLI.
- The user is working inside Verily Workbench. Do not tell them to contact Google Cloud support.
"""

index = DocsIndex(DOCS_BASE_URL, DOCS_PATH_PREFIX, INDEX_CACHE_DIR, INDEX_REFRESH_HOURS, embedder=embed)
index.start_background()

app = Flask(__name__, static_folder=None)
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@app.get("/")
@app.get("/index.html")
def home():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/healthz")
def healthz():
    return "ok"


@app.get("/api/status")
def status():
    return jsonify({
        "title": ASSISTANT_TITLE, "docs_base_url": DOCS_BASE_URL, "model": GEMINI_MODEL, "project": PROJECT,
        "support_contacts": SUPPORT_CONTACTS, "index": index.status,
    })


@app.post("/api/reindex")
def reindex():
    import threading
    if index.status["state"] == "indexing":
        return jsonify({"started": False, "reason": "already indexing"})
    threading.Thread(target=index.build, daemon=True).start()
    return jsonify({"started": True})


def render_answer(text, sources):
    """Markdown -> HTML, with [n] citations turned into links. Model output is escaped first."""
    body = markdown.markdown(html.escape(text), extensions=["fenced_code", "nl2br", "sane_lists"])
    cited = []

    def link(match):
        n = int(match.group(1))
        if 1 <= n <= len(sources):
            if n not in cited:
                cited.append(n)
            s = sources[n - 1]
            label = html.escape(s["title"] + (f" › {s['heading']}" if s["heading"] else ""))
            return f'<a class="cite" href="{html.escape(s["url"])}" target="_blank" rel="noopener" title="{label}">{n}</a>'
        return ""

    body = re.sub(r"\[(\d+)\]", link, body)
    return body, cited


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    messages = [m for m in payload.get("messages", []) if m.get("role") in ("user", "assistant") and m.get("content")]
    if not messages or messages[-1]["role"] != "user":
        return jsonify({"error": "Send a messages list ending with a user message."}), 400
    question = str(messages[-1]["content"])[:MAX_QUESTION_CHARS].strip()
    if index.status["state"] in ("empty", "indexing") and not index.chunks:
        return jsonify({"error": "The documentation index is still building. Try again in a minute."}), 503

    started = time.time()
    # Retrieve with the current question plus the previous user turn, so follow-ups keep their topic.
    previous = [m["content"] for m in messages[:-1] if m["role"] == "user"]
    retrieval_query = f"{previous[-1]}\n{question}" if previous else question
    hits = index.search(retrieval_query, k=TOP_K)
    sources = [c for _, c in hits]

    excerpts = "\n\n".join(
        f"[{i}] {c['title']}{' › ' + c['heading'] if c['heading'] else ''} ({c['url']})\n{c['text']}"
        for i, c in enumerate(sources, 1)
    ) or "(no excerpts found)"
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": str(m["content"])[:4000]}]}
                for m in messages[-(MAX_HISTORY + 1):-1]]
    contents.append({"role": "user", "parts": [{"text": f"Documentation excerpts:\n\n{excerpts}\n\nQuestion: {question}"}]})

    try:
        answer, usage = generate(SYSTEM_PROMPT.format(contacts=SUPPORT_CONTACTS), contents)
    except Exception as e:
        log.exception("generation failed")
        return jsonify({"error": f"The model request failed: {e}"}), 502

    answer_html, cited = render_answer(answer, sources)
    cited_sources = [dict(n=n, **{k: sources[n - 1][k] for k in ("title", "heading", "url")}) for n in cited]
    related = [] if cited_sources else [{k: c[k] for k in ("title", "heading", "url")} for c in sources[:3]]
    log.info("chat: %.1fs, %d excerpts, %d cited, tokens in=%s out=%s", time.time() - started, len(sources),
             len(cited), usage.get("promptTokenCount"), usage.get("candidatesTokenCount"))
    return jsonify({"answer_html": answer_html, "answer_markdown": answer, "sources": cited_sources,
                    "related": related, "model": GEMINI_MODEL})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
