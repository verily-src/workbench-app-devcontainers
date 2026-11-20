package main

import (
	"encoding/json"
	"sync"
	"sync/atomic"
	"time"
)

// Cached lookups behind the tools agents call first: wb_status, and the data collections' display
// names for workspace_list_data_collections. Uncached, each took about 7 s (wb status runs the
// CLI; the names come from a listing of every data collection on the platform, 400 KB for 89).

const (
	// collectionNamesTTL is how long the names are kept; a collection a workspace references that
	// is not among them is fetched again, at most every collectionNamesRetry.
	collectionNamesTTL   = time.Hour
	collectionNamesRetry = time.Minute
	// statusStaleMax is how long past statusTTL a wb_status result is still answered at once,
	// while a fresh one is fetched in the background.
	statusStaleMax = 24 * time.Hour
)

var (
	collectionNamesMu      sync.Mutex
	collectionNamesCache   map[string]string
	collectionNamesFetched time.Time
	statusRefreshing       atomic.Bool
)

// statusResult is wb_status: the cached result while it is fresh, the stale one (with a refresh
// started in the background) for statusStaleMax after that, otherwise `wb status` now.
func statusResult() (string, error) {
	cacheMu.Lock()
	r, ok := toolResultCache["wb_status"]
	cacheMu.Unlock()
	now := time.Now()
	if ok && now.Before(r.expires) {
		return r.output, nil
	}
	if ok && now.Before(r.expires.Add(statusStaleMax)) {
		if statusRefreshing.CompareAndSwap(false, true) {
			go func() {
				defer statusRefreshing.Store(false)
				refreshStatus()
			}()
		}
		return r.output, nil
	}
	return refreshStatus()
}

// lineageSource is the workspace a resource was cloned from (a data collection), or "".
func lineageSource(resource map[string]interface{}) string {
	metadata, _ := resource["metadata"].(map[string]interface{})
	lineage, _ := metadata["resourceLineage"].([]interface{})
	if len(lineage) == 0 {
		return ""
	}
	first, _ := lineage[0].(map[string]interface{})
	id, _ := first["sourceWorkspaceId"].(string)
	return id
}

// dataCollectionNames maps data collection UUIDs to display names, from the cache unless it is
// older than collectionNamesTTL or lacks one of needed. A failed fetch keeps what was cached.
func dataCollectionNames(needed []string) map[string]string {
	collectionNamesMu.Lock()
	defer collectionNamesMu.Unlock()
	age := time.Since(collectionNamesFetched)
	stale := collectionNamesCache == nil || age >= collectionNamesTTL
	if !stale && age >= collectionNamesRetry {
		for _, id := range needed {
			if _, ok := collectionNamesCache[id]; !ok {
				stale = true
				break
			}
		}
	}
	if stale {
		if names, err := fetchCollectionNames(); err == nil {
			collectionNamesCache, collectionNamesFetched = names, time.Now()
		}
	}
	names := make(map[string]string, len(collectionNamesCache))
	for id, name := range collectionNamesCache {
		names[id] = name
	}
	return names
}

// fetchCollectionNames lists every data collection the user can read (workspaces with the
// property terra-type=data-collection) in one call. A variable so tests can replace it.
var fetchCollectionNames = func() (map[string]string, error) {
	body := map[string]interface{}{
		"limit":  1000,
		"offset": 0,
		"properties": []map[string]string{
			{"key": "terra-type", "value": "data-collection"},
		},
	}
	resp, err := makeAPIRequest("POST", workspaceBaseURL+"/api/workspaces/v2/filtered", body)
	if err != nil {
		return nil, err
	}
	var data struct {
		Workspaces []struct {
			ID           string `json:"id"`
			DisplayName  string `json:"displayName"`
			UserFacingID string `json:"userFacingId"`
		} `json:"workspaces"`
	}
	if err := json.Unmarshal(resp, &data); err != nil {
		return nil, err
	}
	names := map[string]string{}
	for _, w := range data.Workspaces {
		name := w.DisplayName
		if name == "" {
			name = w.UserFacingID
		}
		if w.ID != "" && name != "" {
			names[w.ID] = name
		}
	}
	return names, nil
}

// warmRetry and warmTries bound warmCaches' retries.
var (
	warmRetry = 20 * time.Second
	warmTries = 45
)

// warmCaches fills the wb_status cache (if statusFailed, the startup attempt failed) and the data
// collections' names, retrying until both are fetched or warmTries run out.
func warmCaches(statusFailed bool) {
	for try := 0; try < warmTries; try++ {
		if try > 0 {
			time.Sleep(warmRetry)
		}
		if statusFailed {
			if _, err := refreshStatus(); err != nil {
				continue
			}
			statusFailed = false
		}
		collectionNamesMu.Lock()
		have := collectionNamesCache != nil
		collectionNamesMu.Unlock()
		if !have {
			dataCollectionNames(nil)
			collectionNamesMu.Lock()
			have = collectionNamesCache != nil
			collectionNamesMu.Unlock()
		}
		if have {
			return
		}
	}
}
