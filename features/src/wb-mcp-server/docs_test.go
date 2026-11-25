package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

const docsTestPage = `<html><head><title>Share a workspace | Verily Workbench</title></head><body>
<nav class="td-sidebar">Sidebar links about buckets and billing</nav>
<main role="main"><nav class="breadcrumb">Documentation &gt; Workspaces</nav>
<div class="td-content">
<h1>Access control &amp; sharing</h1>
<header class="article-meta">Tags: workspaces</header>
<p>Workspaces can be shared with
collaborators, who get a role.</p>
<h2 id="share-a-workspace">Share a workspace</h2>
<p>Open the workspace and choose <strong>Share</strong>. Pick a role: reader, writer or owner.</p>
<pre><code>wb workspace add-user --email=someone@example.com
  --role=READER</code></pre>
<h3 id="roles">Roles</h3>
<ul><li>Readers see everything.</li><li>Writers add resources and run apps.</li></ul>
<button>Copy</button><script>var x = "share share share";</script>
</div></main><footer>Footer about sharing</footer></body></html>`

const docsOtherPage = `<html><main><div class="td-content"><h1>Buckets</h1>
<h2 id="create">Create a bucket</h2><p>Run wb resource create gcs-bucket --name=mine to add a bucket to the workspace.</p>
</div></main></html>`

// fakeDocsSite serves a sitemap (relative and absolute locations, an off-site and a non-docs
// page), two docs pages with ETags, and counts the full page reads.
func fakeDocsSite(t *testing.T) (*httptest.Server, *int32) {
	var fullReads int32
	mux := http.NewServeMux()
	srv := httptest.NewServer(mux)
	mux.HandleFunc("/sitemap.xml", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, `<urlset><url><loc>/docs/guides/sharing/</loc></url><url><loc>%s/docs/guides/buckets/</loc></url>
<url><loc>/blog/news/</loc></url><url><loc>https://elsewhere.example/docs/x/</loc></url></urlset>`, srv.URL)
	})
	page := func(body, etag string) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			if r.Header.Get("If-None-Match") == etag {
				w.WriteHeader(http.StatusNotModified)
				return
			}
			atomic.AddInt32(&fullReads, 1)
			w.Header().Set("ETag", etag)
			fmt.Fprint(w, body)
		}
	}
	mux.HandleFunc("/docs/guides/sharing/", page(docsTestPage, `"s1"`))
	mux.HandleFunc("/docs/guides/buckets/", page(docsOtherPage, `"b1"`))
	t.Cleanup(srv.Close)
	return srv, &fullReads
}

func freshDocsIndex(base string) *docsIndex {
	return &docsIndex{base: base, state: "empty"}
}

func TestDocsSitemapKeepsOnlyTheSitesDocsPages(t *testing.T) {
	got := docsPageURLs("https://site.example", `<loc>/docs/a/</loc><loc>https://site.example/docs/b/</loc>
<loc>/docs/a/</loc><loc>/about/</loc><loc>https://other.example/docs/c/</loc><loc>/docs/d/?x=1#top</loc>`)
	want := []string{"https://site.example/docs/a/", "https://site.example/docs/b/", "https://site.example/docs/d/"}
	if strings.Join(got, " ") != strings.Join(want, " ") {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestDocsPageIsSplitAtItsHeadingsWithoutTheChrome(t *testing.T) {
	p := parseDocPage("https://site.example/docs/guides/sharing/", docsTestPage)
	if p.Title != "Access control & sharing" {
		t.Errorf("title %q", p.Title)
	}
	var anchors []string
	for _, s := range p.Sections {
		anchors = append(anchors, strings.TrimPrefix(s.URL, "https://site.example/docs/guides/sharing/"))
	}
	if strings.Join(anchors, ",") != ",#share-a-workspace,#roles" {
		t.Fatalf("sections %v", anchors)
	}
	all := ""
	for _, s := range p.Sections {
		all += s.Text + "\n"
	}
	for _, gone := range []string{"Sidebar", "breadcrumb", "Documentation >", "Tags:", "Copy", "var x", "Footer"} {
		if strings.Contains(all, gone) {
			t.Errorf("kept %q in %q", gone, all)
		}
	}
	if !strings.Contains(p.Sections[0].Text, "Workspaces can be shared with collaborators, who get a role.") {
		t.Errorf("a paragraph's source line break should be a space: %q", p.Sections[0].Text)
	}
	if !strings.Contains(p.Sections[1].Text, "wb workspace add-user --email=someone@example.com\n--role=READER") {
		t.Errorf("code keeps its lines: %q", p.Sections[1].Text)
	}
	if p.Sections[2].Heading != "Roles" || !strings.Contains(p.Sections[2].Text, "- Readers see everything.\n- Writers") {
		t.Errorf("list: %+v", p.Sections[2])
	}
}

func TestDocsLongSectionsAreSplitAtLines(t *testing.T) {
	text := strings.Repeat("a line of text that is long enough\n", 100)
	chunks := splitChunks(strings.TrimSpace(text), 200)
	if len(chunks) < 10 {
		t.Fatalf("%d chunks", len(chunks))
	}
	for _, c := range chunks {
		if len(c) > 200 {
			t.Fatalf("chunk of %d chars", len(c))
		}
	}
}

func TestDocsCrawlSearchAndRevalidate(t *testing.T) {
	srv, fullReads := fakeDocsSite(t)
	ix := freshDocsIndex(srv.URL)
	path := filepath.Join(t.TempDir(), "docs-index.json")
	if err := ix.refresh(path); err != nil {
		t.Fatal(err)
	}
	if ix.unavailable() != "" || len(ix.pages) != 2 || atomic.LoadInt32(fullReads) != 2 {
		t.Fatalf("state %q, %d pages, %d reads", ix.state, len(ix.pages), *fullReads)
	}
	hits := ix.search("How do I share a workspace?", 5)
	if len(hits) == 0 || hits[0].section.URL != srv.URL+"/docs/guides/sharing/#share-a-workspace" {
		t.Fatalf("hits %+v", hits)
	}
	if len(hits) > docsPerPage {
		t.Errorf("%d hits from one page", len(hits))
	}
	if h := ix.search("wb resource create gcs-bucket", 1); len(h) != 1 || h[0].page.Title != "Buckets" {
		t.Errorf("command search %+v", h)
	}
	if h := ix.search("the of and", 5); len(h) != 0 {
		t.Errorf("stopwords alone match %+v", h)
	}

	// A second refresh revalidates: the pages answer 304 and are kept.
	if err := ix.refresh(path); err != nil {
		t.Fatal(err)
	}
	if atomic.LoadInt32(fullReads) != 2 || len(ix.pages) != 2 {
		t.Errorf("revalidation read %d pages in full, kept %d", *fullReads-2, len(ix.pages))
	}

	// The saved file loads into a new index.
	f, err := readDocsFile(path)
	if err != nil || f.BaseURL != srv.URL || len(f.Pages) != 2 {
		t.Fatalf("saved %+v, %v", f, err)
	}
	again := freshDocsIndex(srv.URL)
	again.setPages(f.Pages, f.BuiltAt)
	if len(again.search("roles readers writers", 1)) != 1 {
		t.Error("the loaded index does not search")
	}
}

func TestDocsReadServesIndexedPagesOnly(t *testing.T) {
	ix := freshDocsIndex("https://site.example")
	ix.setPages([]docPage{parseDocPage("https://site.example/docs/guides/sharing/", docsTestPage)}, time.Now())
	read := func(u string) (map[string]string, error) {
		out, err := ix.read(u)
		if err != nil {
			return nil, err
		}
		var m map[string]string
		return m, json.Unmarshal([]byte(out), &m)
	}
	whole, err := read("https://site.example/docs/guides/sharing/")
	if err != nil || !strings.Contains(whole["text"], "## Roles") || !strings.Contains(whole["text"], "## Share a workspace") {
		t.Fatalf("whole page %v, %v", whole, err)
	}
	one, err := read("/docs/guides/sharing#roles")
	if err != nil || strings.Contains(one["text"], "Share a workspace") || !strings.Contains(one["text"], "Readers") {
		t.Fatalf("one section %v, %v", one, err)
	}
	if one["url"] != "https://site.example/docs/guides/sharing/#roles" {
		t.Errorf("url %q", one["url"])
	}
	for u, msg := range map[string]string{
		"https://evil.example/docs/guides/sharing/": "only pages of https://site.example/docs/",
		"/docs/not/indexed/":                        "not a page of the Workbench documentation index",
		"/docs/guides/sharing/#nope":                "no section #nope",
	} {
		if _, err := read(u); err == nil || !strings.Contains(err.Error(), msg) {
			t.Errorf("%s: %v", u, err)
		}
	}
}

func TestDocsToolsSayWhyTheyCannotAnswer(t *testing.T) {
	saved := docs
	t.Cleanup(func() { docs = saved })
	cases := []struct {
		ix   *docsIndex
		want string
	}{
		{&docsIndex{state: "off"}, "tools are off"},
		{&docsIndex{state: "building", progress: "120/375 pages"}, "still being built (120/375 pages)"},
		{&docsIndex{state: "empty", base: "https://site.example", lastErr: "dial tcp: i/o timeout"},
			"could not be read from https://site.example (dial tcp: i/o timeout)"},
	}
	for _, c := range cases {
		docs = c.ix
		if _, err := docsSearchResult(map[string]interface{}{"query": "share"}); err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: %v", c.ix.state, err)
		}
	}
	docs = freshDocsIndex("https://site.example")
	docs.setPages([]docPage{parseDocPage("https://site.example/docs/guides/sharing/", docsTestPage)}, time.Now())
	for _, args := range []map[string]interface{}{{}, {"query": " "}, {"query": "share", "limit": float64(11)}} {
		if _, err := docsSearchResult(args); err == nil {
			t.Errorf("%v accepted", args)
		}
	}
	out, err := docsSearchResult(map[string]interface{}{"query": "share a workspace", "limit": float64(2)})
	if err != nil || !strings.Contains(out, "#share-a-workspace") || !strings.Contains(out, "cite their URLs") {
		t.Fatalf("%s, %v", out, err)
	}
}

func TestDocsToolsAreReadOnlyAndInTheDocsGroup(t *testing.T) {
	for _, tool := range docsTools {
		if toolGroups[tool.Name] != groupDocs || !readOnlyTools[tool.Name] || !hasNoCLIEquivalent(tool.Name) {
			t.Errorf("%s: group %q, read-only %v", tool.Name, toolGroups[tool.Name], readOnlyTools[tool.Name])
		}
	}
	enabled, _ := parseToolsets("core,docs")
	listed := map[string]bool{}
	for _, tool := range listTools(enabled, "GCP") {
		listed[tool.Name] = true
	}
	if !listed["wb_docs_search"] || !listed["wb_docs_read"] {
		t.Error("the docs group does not list its tools")
	}
	core, _ := parseToolsets("core")
	for _, tool := range listTools(core, "GCP") {
		if toolGroups[tool.Name] == groupDocs {
			t.Errorf("%s listed without the docs group", tool.Name)
		}
	}
}
