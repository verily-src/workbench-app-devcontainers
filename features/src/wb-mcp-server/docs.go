package main

// The Workbench documentation, searchable by the docs tools (wb_docs_search, wb_docs_read).
//
// The index is the site's /docs/ pages, listed by its sitemap.xml and split at their h2 and h3
// headings into sections, ranked with BM25. It is read from a cache file, else from the snapshot
// the feature's install wrote into the image, and refreshed in the background once a day with
// conditional requests, so an unchanged page costs a 304. Nothing is fetched for a question: a
// question searches the index in memory, and wb_docs_read serves a page from it. No model or
// embedding service is needed, so the tools work wherever the server runs, and from the snapshot
// even where the docs site can't be reached.

import (
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"io"
	"log"
	"math"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	defaultDocsURL   = "https://support.workbench.verily.com"
	docsPathPrefix   = "/docs/"
	docsSnapshotPath = "/opt/wb-mcp-server/docs-index.json"
	docsRefreshEvery = 24 * time.Hour
	// The site throttles bursts of new connections; four keep-alive workers read it in about a minute.
	docsCrawlWorkers = 4
	docsChunkChars   = 1400
	docsMaxResults   = 10
	docsPerPage      = 2
	docsExcerptChars = 700
	docsReadMaxChars = 24000
)

type docSection struct {
	URL     string `json:"url"` // the page URL with the section's #anchor
	Heading string `json:"heading"`
	Text    string `json:"text"`
}

type docPage struct {
	URL          string       `json:"url"`
	Title        string       `json:"title"`
	ETag         string       `json:"etag,omitempty"`
	LastModified string       `json:"last_modified,omitempty"`
	Sections     []docSection `json:"sections"`
}

type docsFile struct {
	BaseURL string    `json:"base_url"`
	BuiltAt time.Time `json:"built_at"`
	Pages   []docPage `json:"pages"`
}

type docsHit struct {
	page    *docPage
	section docSection
	score   float64
}

// docsIndex is the searchable index. Every field is guarded by mu.
type docsIndex struct {
	mu       sync.RWMutex
	base     string
	pages    map[string]*docPage // by page URL
	order    []string            // page URLs, sorted
	entries  []docsEntry
	df       map[string]int
	avgLen   float64
	builtAt  time.Time
	state    string // "off", "empty", "building", "ready"
	progress string
	lastErr  string
}

type docsEntry struct {
	page    string
	section int
	tf      map[string]int
	length  int
	lower   string
}

// docs is the server's index; startDocs fills it.
var docs = &docsIndex{state: "off"}

var docsHTTP = &http.Client{
	Timeout:   30 * time.Second,
	Transport: &http.Transport{MaxIdleConnsPerHost: docsCrawlWorkers, IdleConnTimeout: 90 * time.Second},
}

// ---- tools ---------------------------------------------------------------------------------------

var docsTools = []Tool{
	{
		Name: "wb_docs_search",
		Description: "Search the Verily Workbench documentation (support.workbench.verily.com) for how Workbench works: " +
			"workspaces, sharing, resources, apps, workflows, data collections, policies and the wb CLI. Returns the most " +
			"relevant sections with their URLs; cite the URLs. Use plain words or a wb command as the query.",
		InputSchema: InputSchema{
			Type: "object",
			Properties: map[string]interface{}{
				"query": map[string]interface{}{"type": "string"},
				"limit": map[string]interface{}{"type": "integer", "description": "Sections to return, 1 to 10 (default 5)"},
			},
			Required: []string{"query"},
		},
	},
	{
		Name:        "wb_docs_read",
		Description: "Read one page of the Verily Workbench documentation, or one section of it, by the URL wb_docs_search gave (with its #anchor for one section).",
		InputSchema: InputSchema{
			Type:       "object",
			Properties: map[string]interface{}{"url": map[string]interface{}{"type": "string"}},
			Required:   []string{"url"},
		},
	},
}

func init() {
	wbTools = append(wbTools, docsTools...)
}

func docsSearchResult(args map[string]interface{}) (string, error) {
	query, _ := args["query"].(string)
	if strings.TrimSpace(query) == "" {
		return "", errors.New("'query' required")
	}
	limit := 5
	if l, ok := args["limit"].(float64); ok {
		limit = int(l)
	}
	if limit < 1 || limit > docsMaxResults {
		return "", fmt.Errorf("'limit' is 1 to %d", docsMaxResults)
	}
	if msg := docs.unavailable(); msg != "" {
		return "", errors.New(msg)
	}
	hits := docs.search(query, limit)
	type result struct {
		Title   string `json:"title"`
		Section string `json:"section,omitempty"`
		URL     string `json:"url"`
		Excerpt string `json:"excerpt"`
	}
	out := struct {
		Results []result `json:"results"`
		Source  string   `json:"source"`
		Indexed string   `json:"indexed"`
		Note    string   `json:"note"`
	}{Results: []result{}, Source: docs.base + docsPathPrefix, Indexed: docs.summary(),
		Note: "Answer from these excerpts and cite their URLs. wb_docs_read gives a whole page or section."}
	for _, h := range hits {
		out.Results = append(out.Results, result{Title: h.page.Title, Section: h.section.Heading, URL: h.section.URL,
			Excerpt: excerpt(h.section.Text, docsExcerptChars)})
	}
	if len(hits) == 0 {
		out.Note = "No section matches. Try other words, or say the documentation does not cover it."
	}
	b, err := json.MarshalIndent(out, "", "  ")
	return string(b), err
}

func docsReadResult(args map[string]interface{}) (string, error) {
	raw, _ := args["url"].(string)
	if strings.TrimSpace(raw) == "" {
		return "", errors.New("'url' required")
	}
	if msg := docs.unavailable(); msg != "" {
		return "", errors.New(msg)
	}
	return docs.read(raw)
}

// ---- lifecycle -----------------------------------------------------------------------------------

// startDocs loads the index (cache, else snapshot) and keeps it fresh in the background. An empty
// base URL turns the docs tools off.
func startDocs(base string) {
	base = strings.TrimRight(strings.TrimSpace(base), "/")
	if base == "" {
		log.Printf("Docs tools off (no docs URL)")
		return
	}
	docs.mu.Lock()
	docs.base, docs.state = base, "empty"
	docs.mu.Unlock()
	cache := docsCachePath()
	loaded := false
	for _, path := range []string{cache, docsSnapshotPath} {
		if f, err := readDocsFile(path); err == nil && f.BaseURL == base && len(f.Pages) > 0 {
			docs.setPages(f.Pages, f.BuiltAt)
			log.Printf("Docs index loaded from %s: %d pages, built %s", path, len(f.Pages), f.BuiltAt.Format(time.RFC3339))
			loaded = true
			break
		}
	}
	go func() {
		for {
			docs.mu.RLock()
			age := time.Since(docs.builtAt)
			docs.mu.RUnlock()
			if !loaded || age >= docsRefreshEvery {
				if err := docs.refresh(cache); err != nil {
					log.Printf("Docs index refresh failed: %v", err)
				}
				loaded = true
				age = 0
			}
			time.Sleep(docsRefreshEvery - age)
		}
	}()
}

func docsCachePath() string {
	dir, err := os.UserCacheDir()
	if err != nil {
		dir = os.TempDir()
	}
	return filepath.Join(dir, "wb-mcp-server", "docs-index.json")
}

// buildDocsSnapshot crawls the site and writes the index to path, for the feature's install.
func buildDocsSnapshot(base, path string) error {
	docs.mu.Lock()
	docs.base, docs.state = strings.TrimRight(base, "/"), "empty"
	docs.mu.Unlock()
	return docs.refresh(path)
}

// refresh crawls the site, revalidating the pages already held, and saves the result to path.
func (ix *docsIndex) refresh(path string) error {
	ix.mu.Lock()
	base, prev := ix.base, ix.pages
	if ix.state != "ready" {
		ix.state = "building"
	}
	ix.progress = "listing pages"
	ix.mu.Unlock()
	pages, err := crawlDocs(base, prev, func(done, total int) {
		ix.mu.Lock()
		ix.progress = fmt.Sprintf("%d/%d pages", done, total)
		ix.mu.Unlock()
	})
	ix.mu.Lock()
	ix.progress = ""
	if err != nil {
		ix.lastErr = err.Error()
		if ix.state == "building" {
			ix.state = "empty"
		}
		ix.mu.Unlock()
		return err
	}
	ix.lastErr = ""
	ix.mu.Unlock()
	now := time.Now().UTC()
	ix.setPages(pages, now)
	return writeDocsFile(path, docsFile{BaseURL: base, BuiltAt: now, Pages: pages})
}

func (ix *docsIndex) unavailable() string {
	ix.mu.RLock()
	defer ix.mu.RUnlock()
	switch ix.state {
	case "ready":
		return ""
	case "off":
		return "The documentation tools are off on this server (no docs URL is set)."
	case "building":
		return fmt.Sprintf("The documentation index is still being built (%s); try again in a minute.", ix.progress)
	}
	if ix.lastErr != "" {
		return fmt.Sprintf("The Workbench documentation could not be read from %s (%s). The app may not be allowed "+
			"to reach it. The documentation is at %s%s.", ix.base, ix.lastErr, ix.base, docsPathPrefix)
	}
	return "The documentation index is not loaded yet; try again in a minute."
}

func (ix *docsIndex) summary() string {
	ix.mu.RLock()
	defer ix.mu.RUnlock()
	return fmt.Sprintf("%d pages, %s", len(ix.pages), ix.builtAt.Format("2006-01-02"))
}

func readDocsFile(path string) (docsFile, error) {
	var f docsFile
	b, err := os.ReadFile(path)
	if err != nil {
		return f, err
	}
	err = json.Unmarshal(b, &f)
	return f, err
}

func writeDocsFile(path string, f docsFile) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	b, err := json.Marshal(f)
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".docs-index-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := tmp.Write(b); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Chmod(tmp.Name(), 0o644); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), path)
}

// ---- crawling ------------------------------------------------------------------------------------

var sitemapLoc = regexp.MustCompile(`<loc>\s*([^<\s]+)\s*</loc>`)

// docsPageURLs lists the sitemap's pages under /docs/ on the site's own host, as absolute URLs.
func docsPageURLs(base, sitemap string) []string {
	root, err := url.Parse(base + "/")
	if err != nil {
		return nil
	}
	seen := map[string]bool{}
	var urls []string
	for _, m := range sitemapLoc.FindAllStringSubmatch(sitemap, -1) {
		ref, err := url.Parse(html.UnescapeString(m[1]))
		if err != nil {
			continue
		}
		u := root.ResolveReference(ref)
		u.Fragment, u.RawQuery = "", ""
		if u.Host != root.Host || !strings.HasPrefix(u.Path, docsPathPrefix) || seen[u.String()] {
			continue
		}
		seen[u.String()] = true
		urls = append(urls, u.String())
	}
	sort.Strings(urls)
	return urls
}

func crawlDocs(base string, prev map[string]*docPage, progress func(done, total int)) ([]docPage, error) {
	body, _, err := fetchDoc(base+"/sitemap.xml", nil)
	if err != nil {
		return nil, fmt.Errorf("sitemap: %w", err)
	}
	urls := docsPageURLs(base, body)
	if len(urls) == 0 {
		return nil, fmt.Errorf("the sitemap of %s lists no %s pages", base, docsPathPrefix)
	}
	results := make([]*docPage, len(urls))
	work := make(chan int)
	var wg sync.WaitGroup
	var mu sync.Mutex
	done, failed := 0, 0
	for w := 0; w < docsCrawlWorkers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range work {
				old := prev[urls[i]]
				page, err := fetchDocPage(urls[i], old)
				mu.Lock()
				done++
				if err != nil {
					failed++
					page = old // keep what was held, if anything
					log.Printf("Docs: %s: %v", urls[i], err)
				}
				results[i] = page
				progress(done, len(urls))
				mu.Unlock()
			}
		}()
	}
	for i := range urls {
		work <- i
	}
	close(work)
	wg.Wait()
	var pages []docPage
	for _, p := range results {
		if p != nil && len(p.Sections) > 0 {
			pages = append(pages, *p)
		}
	}
	if len(pages) == 0 {
		return nil, fmt.Errorf("none of the %d pages could be read", len(urls))
	}
	if failed > 0 {
		log.Printf("Docs: %d of %d pages could not be read", failed, len(urls))
	}
	return pages, nil
}

// fetchDocPage reads one page, or keeps old when the server says it has not changed.
func fetchDocPage(pageURL string, old *docPage) (*docPage, error) {
	headers := map[string]string{}
	if old != nil {
		if old.ETag != "" {
			headers["If-None-Match"] = old.ETag
		}
		if old.LastModified != "" {
			headers["If-Modified-Since"] = old.LastModified
		}
	}
	body, resp, err := fetchDoc(pageURL, headers)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode == http.StatusNotModified && old != nil {
		return old, nil
	}
	page := parseDocPage(pageURL, body)
	page.ETag, page.LastModified = resp.Header.Get("ETag"), resp.Header.Get("Last-Modified")
	return &page, nil
}

// fetchDoc GETs a URL, retrying throttling, server errors and network failures.
func fetchDoc(target string, headers map[string]string) (string, *http.Response, error) {
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		if attempt > 0 {
			time.Sleep(time.Duration(attempt*attempt*2) * time.Second)
		}
		req, err := http.NewRequest("GET", target, nil)
		if err != nil {
			return "", nil, err
		}
		req.Header.Set("User-Agent", "wb-mcp-server/"+serverVersion)
		for k, v := range headers {
			req.Header.Set(k, v)
		}
		resp, err := docsHTTP.Do(req)
		if err != nil {
			lastErr = err
			continue
		}
		body, err := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
		resp.Body.Close()
		switch {
		case err != nil:
			lastErr = err
		case resp.StatusCode == http.StatusNotModified, resp.StatusCode == http.StatusOK:
			return string(body), resp, nil
		case resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500:
			lastErr = fmt.Errorf("HTTP %d", resp.StatusCode)
		default:
			return "", nil, fmt.Errorf("HTTP %d", resp.StatusCode)
		}
	}
	return "", nil, lastErr
}

// ---- parsing -------------------------------------------------------------------------------------

var (
	htmlTitle   = regexp.MustCompile(`(?is)<title>(.*?)</title>`)
	htmlH1      = regexp.MustCompile(`(?is)<h1\b[^>]*>(.*?)</h1>`)
	htmlHeading = regexp.MustCompile(`(?is)<h([23])\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</h[23]>`)
	htmlTag     = regexp.MustCompile(`(?s)<[^>]*>`)
	htmlComment = regexp.MustCompile(`(?s)<!--.*?-->`)
	htmlBreak   = regexp.MustCompile(`(?i)<(br|/p|/li|/tr|/h[1-6]|/pre|/div|/table|/ul|/ol|/blockquote|/dt|/dd)\b[^>]*>`)
	htmlItem    = regexp.MustCompile(`(?i)<li\b[^>]*>`)
	htmlCell    = regexp.MustCompile(`(?i)</t[dh]>`)
	spaces      = regexp.MustCompile(`[ \t\x{00a0}]+`)
	newlines    = regexp.MustCompile(`\r?\n`)
	htmlPre     = regexp.MustCompile(`(?is)<pre\b.*?</pre>`)
	// Parts of a page that are not its content: scripts, navigation, buttons, the tags header.
	htmlDrop = func() []*regexp.Regexp {
		var out []*regexp.Regexp
		for _, tag := range []string{"script", "style", "nav", "button", "header", "svg", "form", "noscript", "aside", "footer"} {
			out = append(out, regexp.MustCompile(`(?is)<`+tag+`\b.*?</`+tag+`>`))
		}
		return out
	}()
)

// parseDocPage splits a docs page into sections at its h2 and h3 headings: the text before the
// first heading, then one section per heading (long ones split at paragraphs).
func parseDocPage(pageURL, page string) docPage {
	content := page
	if i := strings.Index(content, `<div class="td-content"`); i >= 0 {
		content = content[i:]
	} else if i := strings.Index(content, "<main"); i >= 0 {
		content = content[i:]
	}
	if j := strings.Index(content, "</main>"); j >= 0 {
		content = content[:j]
	}
	content = htmlComment.ReplaceAllString(content, "")
	for _, re := range htmlDrop {
		content = re.ReplaceAllString(content, "")
	}
	title := ""
	if m := htmlH1.FindStringSubmatch(content); m != nil {
		title = htmlText(m[1])
		content = strings.Replace(content, m[0], "", 1)
	} else if m := htmlTitle.FindStringSubmatch(page); m != nil {
		title = strings.TrimSuffix(htmlText(m[1]), " | Verily Workbench")
	}
	p := docPage{URL: pageURL, Title: title}
	add := func(anchor, heading, body string) {
		text := htmlText(body)
		if len(text) < 40 {
			return
		}
		u := pageURL
		if anchor != "" {
			u += "#" + anchor
		}
		for _, chunk := range splitChunks(text, docsChunkChars) {
			p.Sections = append(p.Sections, docSection{URL: u, Heading: heading, Text: chunk})
		}
	}
	marks := htmlHeading.FindAllStringSubmatchIndex(content, -1)
	start, anchor, heading := 0, "", ""
	for _, m := range marks {
		add(anchor, heading, content[start:m[0]])
		anchor, heading, start = content[m[4]:m[5]], htmlText(content[m[6]:m[7]]), m[1]
	}
	add(anchor, heading, content[start:])
	return p
}

// htmlText is the text of an HTML fragment: tags dropped, entities decoded, one line per block.
// Line breaks in the source count only inside <pre> (code); elsewhere they are spaces.
func htmlText(fragment string) string {
	var flat strings.Builder
	last := 0
	for _, m := range htmlPre.FindAllStringIndex(fragment, -1) {
		flat.WriteString(newlines.ReplaceAllString(fragment[last:m[0]], " "))
		flat.WriteString(fragment[m[0]:m[1]])
		last = m[1]
	}
	flat.WriteString(newlines.ReplaceAllString(fragment[last:], " "))
	s := htmlBreak.ReplaceAllString(flat.String(), "\n")
	s = htmlItem.ReplaceAllString(s, "\n- ")
	s = htmlCell.ReplaceAllString(s, " | ")
	s = htmlTag.ReplaceAllString(s, "")
	s = html.UnescapeString(s)
	var lines []string
	for _, line := range strings.Split(s, "\n") {
		line = strings.TrimSpace(spaces.ReplaceAllString(line, " "))
		if line == "" || line == "-" {
			continue
		}
		lines = append(lines, line)
	}
	return strings.Join(lines, "\n")
}

func splitChunks(text string, limit int) []string {
	var chunks []string
	var buf strings.Builder
	for _, line := range strings.Split(text, "\n") {
		if buf.Len() > 0 && buf.Len()+len(line)+1 > limit {
			chunks = append(chunks, buf.String())
			buf.Reset()
		}
		if buf.Len() > 0 {
			buf.WriteString("\n")
		}
		buf.WriteString(line)
	}
	if buf.Len() > 0 {
		chunks = append(chunks, buf.String())
	}
	return chunks
}

func excerpt(text string, limit int) string {
	if len(text) <= limit {
		return text
	}
	cut := strings.LastIndexAny(text[:limit], " \n")
	if cut < limit/2 {
		cut = limit
	}
	return text[:cut] + " …"
}

// ---- search --------------------------------------------------------------------------------------

var (
	docsWord      = regexp.MustCompile(`[a-z0-9_]+`)
	docsStopwords = map[string]bool{}
)

func init() {
	for _, w := range strings.Fields("a an the and or of to in on for with how do does i can is are my what " +
		"use using from into it this that be by as at me you your we our which when where why who will would " +
		"should could there their they them about") {
		docsStopwords[w] = true
	}
}

func docsTokens(text string) []string {
	var out []string
	for _, w := range docsWord.FindAllString(strings.ToLower(text), -1) {
		if !docsStopwords[w] {
			out = append(out, w)
		}
	}
	return out
}

// setPages replaces the index's pages and recomputes the ranking statistics. A section's title
// and heading count three times, so a match there outranks one in passing.
func (ix *docsIndex) setPages(pages []docPage, builtAt time.Time) {
	byURL := make(map[string]*docPage, len(pages))
	var order []string
	var entries []docsEntry
	df := map[string]int{}
	total := 0
	for i := range pages {
		p := &pages[i]
		byURL[p.URL] = p
		order = append(order, p.URL)
		for j, s := range p.Sections {
			tf := map[string]int{}
			n := 0
			for _, field := range []struct {
				text   string
				weight int
			}{{p.Title, 3}, {s.Heading, 3}, {s.Text, 1}} {
				for _, t := range docsTokens(field.text) {
					tf[t] += field.weight
					n += field.weight
				}
			}
			for t := range tf {
				df[t]++
			}
			total += n
			entries = append(entries, docsEntry{page: p.URL, section: j, tf: tf, length: n,
				lower: strings.ToLower(p.Title + "\n" + s.Heading + "\n" + s.Text)})
		}
	}
	sort.Strings(order)
	ix.mu.Lock()
	defer ix.mu.Unlock()
	ix.pages, ix.order, ix.entries, ix.df, ix.builtAt = byURL, order, entries, df, builtAt
	ix.avgLen = 1
	if len(entries) > 0 {
		ix.avgLen = float64(total) / float64(len(entries))
	}
	ix.state = "ready"
}

// search ranks sections by BM25, with a bonus for the query's words in a row (a wb command), and
// returns at most limit, no more than docsPerPage from one page.
func (ix *docsIndex) search(query string, limit int) []docsHit {
	ix.mu.RLock()
	defer ix.mu.RUnlock()
	terms := map[string]bool{}
	for _, t := range docsTokens(query) {
		terms[t] = true
	}
	if len(terms) == 0 {
		return nil
	}
	phrase := strings.Join(strings.Fields(strings.ToLower(query)), " ")
	const k1, b = 1.2, 0.75
	n := float64(len(ix.entries))
	var hits []docsHit
	for _, e := range ix.entries {
		score := 0.0
		for t := range terms {
			tf := float64(e.tf[t])
			if tf == 0 {
				continue
			}
			idf := math.Log(1 + (n-float64(ix.df[t])+0.5)/(float64(ix.df[t])+0.5))
			score += idf * tf * (k1 + 1) / (tf + k1*(1-b+b*float64(e.length)/ix.avgLen))
		}
		if score == 0 {
			continue
		}
		if len(terms) > 1 && strings.Contains(e.lower, phrase) {
			score *= 1.5
		}
		p := ix.pages[e.page]
		hits = append(hits, docsHit{page: p, section: p.Sections[e.section], score: score})
	}
	sort.SliceStable(hits, func(i, j int) bool { return hits[i].score > hits[j].score })
	var out []docsHit
	perPage := map[string]int{}
	for _, h := range hits {
		if perPage[h.page.URL] >= docsPerPage {
			continue
		}
		perPage[h.page.URL]++
		out = append(out, h)
		if len(out) == limit {
			break
		}
	}
	return out
}

// read gives a page of the index, or the sections under one anchor, by URL or /docs/ path.
func (ix *docsIndex) read(raw string) (string, error) {
	ix.mu.RLock()
	defer ix.mu.RUnlock()
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil {
		return "", fmt.Errorf("%q is not a URL", raw)
	}
	root, _ := url.Parse(ix.base + "/")
	if u.Host != "" && u.Host != root.Host {
		return "", fmt.Errorf("only pages of %s%s can be read", ix.base, docsPathPrefix)
	}
	path := u.Path
	if !strings.HasSuffix(path, "/") {
		path += "/"
	}
	page := ix.pages[root.ResolveReference(&url.URL{Path: path}).String()]
	if page == nil {
		return "", fmt.Errorf("%s is not a page of the Workbench documentation index; use a URL from wb_docs_search", raw)
	}
	var parts []string
	prev := ""
	for _, s := range page.Sections {
		if u.Fragment != "" && s.URL != page.URL+"#"+u.Fragment {
			continue
		}
		text := s.Text
		if s.Heading != "" && s.URL != prev {
			text = "## " + s.Heading + "\n" + s.Text
		}
		prev = s.URL
		parts = append(parts, text)
	}
	if len(parts) == 0 {
		return "", fmt.Errorf("the page has no section #%s", u.Fragment)
	}
	text := strings.Join(parts, "\n\n")
	truncated := len(text) > docsReadMaxChars
	if truncated {
		text = excerpt(text, docsReadMaxChars)
	}
	out := map[string]interface{}{"title": page.Title, "url": page.URL, "text": text}
	if u.Fragment != "" {
		out["url"] = page.URL + "#" + u.Fragment
	}
	if truncated {
		out["note"] = "The page is long and was cut; read one section with its #anchor from wb_docs_search."
	}
	b, err := json.MarshalIndent(out, "", "  ")
	return string(b), err
}
