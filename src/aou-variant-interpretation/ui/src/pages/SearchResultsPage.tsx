import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchProfile } from "../api/profile";
import { fetchSearchResults, type SearchResults } from "../api/searchResults";
import { describeError } from "../api/client";
import colors from "../libs/colors";
import Footer from "../components/results/Footer";
import PhenotypeSummaryStrip from "../components/results/PhenotypeSummaryStrip";
import ReviewView from "../components/results/ReviewView";
import SearchPopover from "../components/results/SearchPopover";
import SectionLoadingPanel from "../components/results/SectionLoadingPanel";
import TopBar from "../components/results/TopBar";
import VariantsPanel, { VARIANTS_TABLE_MIN_HEIGHT } from "../components/results/VariantsPanel";
import type { ResultsView } from "../components/results/ViewSwitcher";
import type { ConditionConcept } from "../api/conditions";
import { searchConceptIds } from "../utils/phenotypes";
import { recordRecentSearch } from "../utils/recentSearches";
import { parseVariantsText } from "../utils/variants";

export default function SearchResultsPage() {
  const [userEmail, setUserEmail] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Table or Review, chosen from the summary strip. Review opens on reviewVariant when a row asked
  // for it, otherwise on the best-supported signal.
  const [view, setView] = useState<ResultsView>("table");
  const [reviewVariant, setReviewVariant] = useState<string | undefined>(undefined);
  const [drawerVariants, setDrawerVariants] = useState("");
  // The phenotypes the search was run with, as the drawer's starting point; only picked
  // concepts are ever here, so re-running filters by exactly what the user chose.
  const [drawerPhenotypes, setDrawerPhenotypes] = useState<ConditionConcept[]>([]);
  // Remounts the popover on cancel, so anything typed into its condition field is dropped
  // along with the rest of the edit.
  const [drawerKey, setDrawerKey] = useState(0);
  const [searchParams, setSearchParams] = useSearchParams();

  useEffect(() => {
    fetchProfile()
      .then((profile) => setUserEmail(profile.userEmail))
      .catch((err: Error) => console.error("Failed to load profile", err));
  }, []);

  // Keyed on just the search criteria, not the whole URL -- other params unrelated to what to
  // fetch could otherwise end up in the URL (e.g. UI state some other component tracks there).
  // Depending on searchParams.toString() would re-run this on every such change, wiping results
  // and flashing every section's loading state for a fetch that's a cache hit anyway.
  const variantsKey = searchParams.getAll("variants").join("\n");
  const conditionConceptIdsKey = searchParams.getAll("conditionConceptIds").join("\n");

  // Re-runs whenever the URL's search criteria change -- both the initial load (e.g. arriving
  // from SearchEntryPage with ?variants=...) and an edit-search re-search (which updates the URL rather
  // than fetching directly) go through this one path.
  useEffect(() => {
    setResults(null);
    setError(null);
    setView("table");
    setReviewVariant(undefined);
    fetchSearchResults({
      variants: variantsKey ? variantsKey.split("\n") : [],
      conditionConceptIds: conditionConceptIdsKey ? conditionConceptIdsKey.split("\n").map(Number) : undefined,
    })
      .then((data) => {
        setResults(data);
        resetDrawer(data);
        // Only searches that actually loaded go into the entry page's history, and only the
        // concepts that resolved: an id the CDR doesn't have isn't worth re-running.
        recordRecentSearch({
          variants: parseVariantsText(data.searchSummary.variantsRaw),
          conditions: (data.conditionSearch?.concepts ?? []).map(({ conceptId, name, estimatedParticipantCount, hpo }) => ({
            conceptId,
            name,
            estimatedParticipantCount,
            hpo,
          })),
        });
      })
      .catch((err: unknown) => setError(describeError(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [variantsKey, conditionConceptIdsKey]);

  function resetDrawer(data: SearchResults) {
    setDrawerVariants(data.searchSummary.variantsRaw);
    setDrawerPhenotypes(data.conditionSearch?.concepts ?? []);
    setDrawerKey((key) => key + 1);
  }

  function handleCancelDrawer() {
    if (results) {
      resetDrawer(results);
    }
    setDrawerOpen(false);
  }

  function handleRerunSearch() {
    const variants = parseVariantsText(drawerVariants);
    const nextParams = new URLSearchParams();
    for (const variant of variants) {
      nextParams.append("variants", variant);
    }
    for (const conceptId of searchConceptIds(drawerPhenotypes)) {
      nextParams.append("conditionConceptIds", String(conceptId));
    }
    setSearchParams(nextParams);
    setDrawerOpen(false);
  }

  // One rule for "there are matched participants to compare with": it shows the table's matched
  // columns, enables Review in the strip, and offers each row's Review button.
  const hasPhenotypeFilter = (results?.ancestryBreakdown.length ?? 0) > 0;
  // The resolved conditions' names, for every line that says who the matched participants are.
  // Empty when no phenotype was picked, and when none of the picked ids was found.
  const phenotypeNames = (results?.conditionSearch?.concepts ?? []).map((concept) => concept.name);

  function openReview(variant?: string) {
    setReviewVariant(variant);
    setView("review");
  }

  if (error) {
    return (
      <p style={{ padding: "32px 20px", textAlign: "center", color: colors.textSecondary, fontSize: 13 }}>
        Failed to load search results: {error}
      </p>
    );
  }

  return (
    // A column that fills the window, so the footer sits at the bottom even on a short result.
    <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <TopBar
        loading={!results}
        variantsEnteredCount={results?.searchSummary.variantsEnteredCount ?? 0}
        phenotypes={phenotypeNames}
        userEmail={userEmail}
        onModifySearch={() => setDrawerOpen((open) => !open)}
        modifyOpen={drawerOpen}
        editSearchPanel={
          results && (
            <SearchPopover
              key={drawerKey}
              open={drawerOpen}
              variantsText={drawerVariants}
              phenotypes={drawerPhenotypes}
              variantsLimit={results.searchSummary.variantsLimit}
              onVariantsChange={setDrawerVariants}
              onPhenotypesChange={setDrawerPhenotypes}
              onCancel={handleCancelDrawer}
              onSearch={handleRerunSearch}
            />
          )
        }
      />

      <main style={{ flex: 1, padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>
        <PhenotypeSummaryStrip
          loading={!results}
          conditionSearch={results?.conditionSearch}
          ancestryBreakdown={results?.ancestryBreakdown ?? []}
          ageBreakdown={results?.ageBreakdown ?? []}
          onAddPhenotypeFilter={() => setDrawerOpen(true)}
          view={view}
          onViewChange={(next) => (next === "review" ? openReview() : setView("table"))}
          canReview={hasPhenotypeFilter}
        />

        {view === "review" && results?.conditionSearch && hasPhenotypeFilter ? (
          <ReviewView
            initialVariant={reviewVariant}
            cohortVariants={results.cohortVariants}
            filteredVariants={results.filteredVariants}
            phenotypes={phenotypeNames}
            participantCount={results.conditionSearch.participantCount ?? 0}
            ancestryBreakdown={results.ancestryBreakdown}
          />
        ) : (
          <>
            {results ? (
              <VariantsPanel
                cohortVariants={results.cohortVariants}
                filteredVariants={results.filteredVariants}
                hasPhenotypeFilter={hasPhenotypeFilter}
                participantCount={results.conditionSearch?.participantCount ?? 0}
                phenotypes={phenotypeNames}
                onReview={hasPhenotypeFilter ? openReview : undefined}
                onAddPhenotypeFilter={() => setDrawerOpen(true)}
              />
            ) : (
              <SectionLoadingPanel
                title="Candidate variants"
                message="Loading variants…"
                minHeight={VARIANTS_TABLE_MIN_HEIGHT}
              />
            )}
          </>
        )}
      </main>
      <Footer />
    </div>
  );
}
