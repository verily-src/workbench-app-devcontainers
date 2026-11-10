package org.broadinstitute.variantinterpretation.controller;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import org.broadinstitute.variantinterpretation.datasource.ConditionLookupService;
import org.broadinstitute.variantinterpretation.datasource.MockPhenotypeData;
import org.broadinstitute.variantinterpretation.datasource.PhenotypeFixtures;
import org.broadinstitute.variantinterpretation.datasource.QueryUsageMeter;
import org.broadinstitute.variantinterpretation.datasource.VatLookupService;
import org.broadinstitute.variantinterpretation.api.SearchApi;
import org.broadinstitute.variantinterpretation.model.CohortVariant;
import org.broadinstitute.variantinterpretation.model.ConditionSearch;
import org.broadinstitute.variantinterpretation.model.MatchedConcept;
import org.broadinstitute.variantinterpretation.model.SearchResultsResponse;
import org.broadinstitute.variantinterpretation.model.SearchSummary;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class SearchResultsController implements SearchApi {

  // In early discussions we agreed on a limit of 50 candidate variants, but that could change in the future.
  private static final int VARIANTS_LIMIT = 50;

  private final VatLookupService vatLookup;
  private final ConditionLookupService conditionLookup;
  private final PhenotypeFixtures phenotypeFixtures;
  private final QueryUsageMeter usage;

  public SearchResultsController(
      VatLookupService vatLookup,
      ConditionLookupService conditionLookup,
      PhenotypeFixtures phenotypeFixtures,
      QueryUsageMeter usage) {
    this.vatLookup = vatLookup;
    this.conditionLookup = conditionLookup;
    this.phenotypeFixtures = phenotypeFixtures;
    this.usage = usage;
  }

  // cohortVariants and conditionSearch are the parts of this response backed by real queries:
  // cohortVariants against the VAT, conditionSearch against cb_criteria / concept_ancestor /
  // condition_occurrence. The VAT holds only variant-level annotation -- no phenotype,
  // participant, ancestry or age data -- so the breakdowns and filteredVariants are still served
  // from MockPhenotypeData until a genotype-level data source exists. They're scaled to the
  // picked conditions' real participant count -- participants with any of them -- standing in
  // for data about those participants, and left empty when they matched nobody. A demo use
  // case's condition, picked on its own, gets its own curated breakdowns and per-variant counts
  // instead (PhenotypeFixtures).
  @Override
  public ResponseEntity<SearchResultsResponse> searchResults(
      List<String> variants, List<Long> conditionConceptIds) {
    List<String> requested = normalizeVariants(variants);
    usage.beginSearch(requested);
    try {
      return ResponseEntity.ok(search(requested, conditionConceptIds));
    } finally {
      usage.endSearch();
    }
  }

  private SearchResultsResponse search(List<String> requested, List<Long> conditionConceptIds) {
    List<CohortVariant> cohortVariants = vatLookup.lookup(requested);
    ConditionSearch conditionSearch = conditionLookup.search(conditionConceptIds);
    if (conditionSearch != null) {
      usage.describeSearchPhenotypes(conditionSearch.getConcepts().stream().map(MatchedConcept::getName).toList());
    }
    // Null both when no condition was picked and when none of the picked concepts was found.
    Integer participants = conditionSearch == null ? null : conditionSearch.getParticipantCount().orElse(null);
    boolean phenotypeFiltered = participants != null && participants > 0;
    SearchResultsResponse response =
        new SearchResultsResponse()
            .searchSummary(searchSummary(requested))
            .conditionSearch(conditionSearch)
            .cohortVariants(cohortVariants);
    if (!phenotypeFiltered) {
      return response.ancestryBreakdown(List.of()).ageBreakdown(List.of()).filteredVariants(List.of());
    }

    List<Long> matchedIds = conditionSearch.getConcepts().stream().map(MatchedConcept::getConceptId).toList();
    Optional<PhenotypeFixtures.UseCase> useCase = phenotypeFixtures.forConditions(matchedIds, participants);
    Map<String, MockPhenotypeData.CuratedCounts> curated =
        useCase.map(PhenotypeFixtures.UseCase::variants).orElse(Map.of());
    return response
        .ancestryBreakdown(
            useCase
                .map(u -> MockPhenotypeData.ancestryBreakdown(u.ancestry(), participants))
                .orElseGet(() -> MockPhenotypeData.ancestryBreakdown(participants)))
        .ageBreakdown(
            useCase
                .map(u -> MockPhenotypeData.ageBreakdown(u.age(), participants))
                .orElseGet(() -> MockPhenotypeData.ageBreakdown(participants)))
        .filteredVariants(MockPhenotypeData.filteredVariants(cohortVariants, participants, curated));
  }

  // Trims, drops blanks, dedupes (keeping the first occurrence's position), and caps num
  // entries at VARIANTS_LIMIT.
  private static List<String> normalizeVariants(List<String> variants) {
    if (variants == null) {
      return List.of();
    }
    return variants.stream()
        .map(String::trim)
        .filter(v -> !v.isEmpty())
        .distinct()
        .limit(VARIANTS_LIMIT)
        .toList();
  }

  private static SearchSummary searchSummary(List<String> variantsRaw) {
    return new SearchSummary()
        .variantsRaw(String.join("\n", variantsRaw))
        .variantsEnteredCount(variantsRaw.size())
        .variantsLimit(VARIANTS_LIMIT);
  }
}
