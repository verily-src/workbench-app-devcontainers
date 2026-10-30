"""Crawl a documentation site, split pages into sections, and search them.

The site is discovered from its sitemap.xml. Each page is split at h2/h3 headings so answers can
link to a specific section. Search is hybrid: cosine similarity on embeddings (when an embedder is
available) plus a small keyword-overlap boost, which helps with exact CLI command names.
"""

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

import numpy as np
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("docs_index")

# Elements that are navigation or metadata, not content.
NOISE_SELECTORS = [
    ".td-page-meta", ".td-toc", "nav", ".taxonomy-terms", ".breadcrumb", ".td-breadcrumbs",
    ".feedback--response", ".td-byline", "script", "style",
]
SECTION_HEADINGS = ("h2", "h3")
CHUNK_CHARS = 1400
MIN_SECTION_CHARS = 40
CRAWL_WORKERS = 4          # keep this modest; doc sites throttle bursts of new connections
_thread_local = threading.local()


def _http():
    """One keep-alive session per thread, with retries on connection errors and 429/5xx."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers["User-Agent"] = "workbench-docs-assistant/1.0"
        retry = Retry(total=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.mount("http://", HTTPAdapter(max_retries=retry))
        _thread_local.session = session
    return session
STOPWORDS = set("a an the and or of to in on for with how do i can is are my what does use using from into".split())


def _tokens(text):
    return [t for t in re.findall(r"[a-z0-9][a-z0-9_\-\.]*", text.lower()) if t not in STOPWORDS]


def parse_page(url, html):
    """Return (title, [section dicts]) for one documentation page."""
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.find("h1") or soup.find("title")
    title = title_el.get_text(" ", strip=True).split(" | ")[0] if title_el else url
    main = soup.select_one(".td-content") or soup.find("main") or soup.body
    if main is None:
        return title, []
    for selector in NOISE_SELECTORS:
        for tag in main.select(selector):
            tag.decompose()

    sections = []
    current = {"heading": "", "anchor": "", "parts": []}

    def flush():
        text = "\n".join(current["parts"]).strip()
        if len(text) >= MIN_SECTION_CHARS:
            sections.append({"heading": current["heading"], "anchor": current["anchor"], "text": text})

    for el in main.children:
        name = getattr(el, "name", None)
        if name is None:
            text = str(el).strip()
            if text:
                current["parts"].append(text)
        elif name in SECTION_HEADINGS:
            flush()
            current = {"heading": el.get_text(" ", strip=True), "anchor": el.get("id", ""), "parts": []}
        elif name == "h1":
            continue
        else:
            # Keep line breaks inside code blocks so commands stay readable.
            text = el.get_text("\n", strip=True) if (name == "pre" or el.find("pre")) else el.get_text(" ", strip=True)
            if text:
                current["parts"].append(text)
    flush()
    return title, sections


def split_section(text, limit=CHUNK_CHARS):
    """Split long sections on paragraph boundaries."""
    if len(text) <= limit:
        return [text]
    chunks, buf = [], ""
    for para in text.split("\n"):
        if buf and len(buf) + len(para) + 1 > limit:
            chunks.append(buf)
            buf = para
        else:
            buf = f"{buf}\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks


class DocsIndex:
    def __init__(self, base_url, path_prefix="/docs/", cache_dir=None, refresh_hours=24, embedder=None):
        self.base_url = base_url.rstrip("/") + "/"
        self.path_prefix = path_prefix
        self.cache_dir = cache_dir
        self.refresh_seconds = refresh_hours * 3600
        self.embedder = embedder          # callable(list[str], task_type) -> np.ndarray, or None
        self.chunks = []
        self.vectors = None
        self.status = {"state": "empty", "pages": 0, "skipped": 0, "chunks": 0, "embeddings": "pending",
                       "built_at": None, "progress": "", "error": None}
        self._lock = threading.Lock()

    # ----- crawling -----

    def list_pages(self):
        resp = _http().get(urljoin(self.base_url, "sitemap.xml"), timeout=(15, 30))
        resp.raise_for_status()
        urls = []
        for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", resp.text):
            url = urljoin(self.base_url, loc.strip())
            path = url[len(self.base_url) - 1:]
            if path.startswith(self.path_prefix):
                urls.append(url)
        return sorted(set(urls))

    def fetch_and_parse(self, url):
        """Return the page's chunks, or None if it could not be fetched."""
        try:
            resp = _http().get(url, timeout=(15, 30))
            resp.raise_for_status()
        except requests.RequestException as e:
            log.warning("fetch failed %s: %s", url, str(e)[:160])
            return None
        title, sections = parse_page(url, resp.text)
        chunks = []
        for section in sections:
            for text in split_section(section["text"]):
                chunks.append({
                    "url": url + (f"#{section['anchor']}" if section["anchor"] else ""),
                    "page_url": url,
                    "title": title,
                    "heading": section["heading"],
                    "text": text,
                })
        return chunks

    # ----- building -----

    def build(self):
        started = time.time()
        with self._lock:
            self.status.update(state="indexing", error=None, progress="listing pages")
        try:
            urls = self.list_pages()
            chunks, failed, done = [], [], 0
            with ThreadPoolExecutor(max_workers=CRAWL_WORKERS) as pool:
                for url, page_chunks in zip(urls, pool.map(self.fetch_and_parse, urls)):
                    done += 1
                    if page_chunks is None:
                        failed.append(url)
                    else:
                        chunks.extend(page_chunks)
                    if done % 25 == 0:
                        self.status["progress"] = f"{done}/{len(urls)} pages"
            if failed:                       # second, gentler pass for anything the site throttled
                self.status["progress"] = f"retrying {len(failed)} pages"
                time.sleep(5)
                still_failed = []
                for url in failed:
                    page_chunks = self.fetch_and_parse(url)
                    if page_chunks is None:
                        still_failed.append(url)
                    else:
                        chunks.extend(page_chunks)
                failed = still_failed
            if not chunks:
                raise RuntimeError("no content found; check DOCS_BASE_URL and the sitemap")

            vectors, embed_state = None, "unavailable (no embedder configured)"
            if self.embedder:
                self.status["progress"] = f"embedding {len(chunks)} sections"
                try:
                    vectors = self._embed_chunks(chunks)
                    embed_state = "ok"
                except Exception as e:          # keyword search still works without embeddings
                    log.exception("embedding failed; falling back to keyword search")
                    embed_state = f"unavailable ({type(e).__name__}: {str(e)[:200]})"

            with self._lock:
                self.chunks, self.vectors = chunks, vectors
                self.status.update(state="ready", pages=len(urls) - len(failed), skipped=len(failed),
                                   chunks=len(chunks), embeddings=embed_state, built_at=time.time(), progress="")
            self._save_cache()
            log.info("indexed %d pages, %d sections in %.0fs (embeddings: %s)",
                     len(urls), len(chunks), time.time() - started, embed_state)
        except Exception as e:
            log.exception("index build failed")
            with self._lock:
                self.status.update(state="error" if not self.chunks else "ready", error=f"{type(e).__name__}: {e}",
                                   progress="")

    def _embed_chunks(self, chunks, batch_size=40):
        texts = [f"{c['title']} > {c['heading']}\n{c['text']}" if c["heading"] else f"{c['title']}\n{c['text']}"
                 for c in chunks]
        batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            parts = list(pool.map(lambda b: self.embedder(b, "RETRIEVAL_DOCUMENT"), batches))
        vectors = np.vstack(parts).astype(np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.clip(norms, 1e-8, None)

    # ----- cache -----

    def _save_cache(self):
        if not self.cache_dir:
            return
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(os.path.join(self.cache_dir, "index.json"), "w") as f:
                json.dump({"base_url": self.base_url, "status": self.status, "chunks": self.chunks}, f)
            vec_path = os.path.join(self.cache_dir, "vectors.npy")
            if self.vectors is not None:
                np.save(vec_path, self.vectors)
            elif os.path.exists(vec_path):
                os.remove(vec_path)
        except OSError as e:
            log.warning("could not write index cache: %s", e)

    def load_cache(self):
        """Load a cached index. Returns True if it was loaded and is still fresh."""
        if not self.cache_dir:
            return False
        try:
            with open(os.path.join(self.cache_dir, "index.json")) as f:
                data = json.load(f)
            if data.get("base_url") != self.base_url:
                return False
            vec_path = os.path.join(self.cache_dir, "vectors.npy")
            vectors = np.load(vec_path) if os.path.exists(vec_path) else None
            if vectors is not None and len(vectors) != len(data["chunks"]):
                return False
            with self._lock:
                self.chunks, self.vectors = data["chunks"], vectors
                self.status.update(data["status"], state="ready", error=None, progress="")
            age = time.time() - (self.status.get("built_at") or 0)
            log.info("loaded cached index: %d sections, %.1f h old", len(self.chunks), age / 3600)
            return age < self.refresh_seconds
        except (OSError, ValueError, KeyError):
            return False

    def start_background(self):
        def run():
            fresh = self.load_cache()
            while True:
                if not fresh:
                    self.build()
                fresh = False
                time.sleep(self.refresh_seconds)
        threading.Thread(target=run, name="docs-index", daemon=True).start()

    # ----- search -----

    def search(self, query, k=8, per_page=3):
        with self._lock:
            chunks, vectors = self.chunks, self.vectors
        if not chunks:
            return []
        terms = set(_tokens(query))
        keyword = np.array([
            (len(terms & set(_tokens(c["title"] + " " + c["heading"] + " " + c["text"]))) / len(terms)) if terms else 0.0
            for c in chunks
        ])
        scores = keyword
        if vectors is not None and self.embedder:
            try:
                q = self.embedder([query], "RETRIEVAL_QUERY")[0]
                q = q / max(np.linalg.norm(q), 1e-8)
                scores = vectors @ q + 0.15 * keyword
            except Exception:
                log.exception("query embedding failed; using keyword scores")
        results, seen = [], {}
        for i in np.argsort(-scores):
            c = chunks[i]
            if seen.get(c["page_url"], 0) >= per_page:
                continue
            seen[c["page_url"]] = seen.get(c["page_url"], 0) + 1
            results.append((float(scores[i]), c))
            if len(results) >= k:
                break
        return results
