package org.broadinstitute.variantinterpretation;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.tuple;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.IntStream;
import org.broadinstitute.variantinterpretation.controller.SearchResultsController;
import org.broadinstitute.variantinterpretation.datasource.ConditionLookupService;
import org.broadinstitute.variantinterpretation.datasource.MockPhenotypeData;
import org.broadinstitute.variantinterpretation.datasource.PhenotypeFixtures;
import org.broadinstitute.variantinterpretation.datasource.QueryUsageMeter;
import org.broadinstitute.variantinterpretation.datasource.VatLookupService;
import org.broadinstitute.variantinterpretation.model.BreakdownSegment;
import org.broadinstitute.variantinterpretation.model.CohortVariant;
import org.broadinstitute.variantinterpretation.model.ConditionOverlapCell;
import org.broadinstitute.variantinterpretation.model.ConditionSearch;
import org.broadinstitute.variantinterpretation.model.FilteredVariant;
import org.broadinstitute.variantinterpretation.model.MatchedConcept;
import org.broadinstitute.variantinterpretation.model.SearchResultsResponse;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;

/**
 * The search endpoint's orchestration, with the two lookups and the fixtures mocked: how the
 * variant list is normalized, when the phenotype-matched half of the response is filled in and
 * from what, and how the request is bracketed in the usage meter.
 */
class SearchResultsControllerTest {

  private static final long HCM = 9000040L;
  private static final long TETRALOGY = 9000010L;

  private final VatLookupService vatLookup = mock(VatLookupService.class);
  private final ConditionLookupService conditionLookup = mock(ConditionLookupService.class);
  private final PhenotypeFixtures fixtures = mock(PhenotypeFixtures.class);
  private final QueryUsageMeter usage = mock(QueryUsageMeter.class);
  private final SearchResultsController controller =
      new SearchResultsController(vatLookup, conditionLookup, fixtures, usage);

  private static CohortVariant annotated(String vid) {
    return new CohortVariant().variant(vid).annotated(true).gene("MYH7").aouAllAf(new BigDecimal("0.001")).aouAllAc(200).aouAllAn(200_000);
  }

  private static MatchedConcept concept(long id, String name, int participants) {
    return new MatchedConcept().conceptId(id).name(name).estimatedParticipantCount(participants).participantCount(participants);
  }

  /** A search that resolved these concepts to this many participants, as the lookup returns it. */
  private static ConditionSearch resolved(int participants, MatchedConcept... concepts) {
    List<MatchedConcept> matched = List.of(concepts);
    return new ConditionSearch()
        .conceptIds(matched.stream().map(MatchedConcept::getConceptId).toList())
        .concepts(matched)
        .participantCount(participants)
        .conditionOverlap(
            matched.stream()
                .map(c -> new ConditionOverlapCell().conceptIds(List.of(c.getConceptId())).count(c.getParticipantCount()))
                .toList());
  }

  private SearchResultsResponse search(List<String> variants, List<Long> conceptIds) {
    when(vatLookup.lookup(anyList()))
        .thenAnswer(invocation -> invocation.<List<String>>getArgument(0).stream().map(SearchResultsControllerTest::annotated).toList());
    when(fixtures.forConditions(anyList(), anyInt())).thenReturn(Optional.empty());
    return controller.searchResults(variants, conceptIds).getBody();
  }

  /** Trimmed, blanks dropped, duplicates collapsed to their first position; the summary reports what was kept. */
  @Test
  void normalizesTheVariantListBeforeLookingItUp() {
    SearchResultsResponse response =
        search(Arrays.asList(" 1-1-A-G ", "", "2-2-C-T", "1-1-A-G", "   ", "3-3-G-A"), null);

    verify(vatLookup).lookup(List.of("1-1-A-G", "2-2-C-T", "3-3-G-A"));
    assertThat(response.getCohortVariants()).extracting(CohortVariant::getVariant).containsExactly("1-1-A-G", "2-2-C-T", "3-3-G-A");
    assertThat(response.getSearchSummary().getVariantsRaw()).isEqualTo("1-1-A-G\n2-2-C-T\n3-3-G-A");
    assertThat(response.getSearchSummary().getVariantsEnteredCount()).isEqualTo(3);
    assertThat(response.getSearchSummary().getVariantsLimit()).isEqualTo(50);
  }

  /** The 51st variant and beyond are dropped, which is why the UI disables Search above 50. */
  @Test
  void capsTheVariantListAtTheLimit() {
    List<String> variants = IntStream.rangeClosed(1, 55).mapToObj(i -> "1-" + i + "-A-G").toList();

    SearchResultsResponse response = search(variants, null);

    verify(vatLookup).lookup(variants.subList(0, 50));
    assertThat(response.getSearchSummary().getVariantsEnteredCount()).isEqualTo(50);
    assertThat(response.getCohortVariants()).hasSize(50);
  }

  @Test
  void treatsNoVariantsAsAnEmptySearch() {
    SearchResultsResponse response = search(null, null);

    verify(vatLookup).lookup(List.of());
    assertThat(response.getCohortVariants()).isEmpty();
    assertThat(response.getSearchSummary().getVariantsRaw()).isEmpty();
    assertThat(response.getSearchSummary().getVariantsEnteredCount()).isZero();
  }

  /**
   * The phenotype-matched half stays empty in three cases the UI treats alike (it decides "is
   * there a phenotype filter" from whether the ancestry breakdown has anything in it): no
   * condition picked, none of the picked ids resolved, and a resolved condition nobody has.
   */
  @Test
  void leavesThePhenotypeHalfEmptyWhenNoParticipantsMatched() {
    when(conditionLookup.search(null)).thenReturn(null);
    SearchResultsResponse none = search(List.of("1-1-A-G"), null);
    assertThat(none.getConditionSearch().orElse(null)).isNull();
    assertThat(none.getAncestryBreakdown()).isEmpty();
    assertThat(none.getAgeBreakdown()).isEmpty();
    assertThat(none.getFilteredVariants()).isEmpty();

    when(conditionLookup.search(List.of(123L)))
        .thenReturn(new ConditionSearch().conceptIds(List.of(123L)).concepts(List.of()).participantCount(null));
    SearchResultsResponse unresolved = search(List.of("1-1-A-G"), List.of(123L));
    assertThat(unresolved.getConditionSearch().orElseThrow().getConceptIds()).containsExactly(123L);
    assertThat(unresolved.getAncestryBreakdown()).isEmpty();
    assertThat(unresolved.getFilteredVariants()).isEmpty();

    when(conditionLookup.search(List.of(HCM))).thenReturn(resolved(0, concept(HCM, "Hypertrophic cardiomyopathy", 0)));
    SearchResultsResponse nobody = search(List.of("1-1-A-G"), List.of(HCM));
    assertThat(nobody.getConditionSearch().orElseThrow().getParticipantCount().orElse(null)).isZero();
    assertThat(nobody.getAncestryBreakdown()).isEmpty();
    assertThat(nobody.getFilteredVariants()).isEmpty();

    verify(fixtures, never()).forConditions(anyList(), anyInt());
  }

  /** Matched participants with no demo fixture: generated breakdowns at that count, stats for every variant. */
  @Test
  void fillsThePhenotypeHalfFromGeneratedDataScaledToTheMatchedCount() {
    when(conditionLookup.search(List.of(HCM, TETRALOGY)))
        .thenReturn(resolved(260, concept(HCM, "Hypertrophic cardiomyopathy", 214), concept(TETRALOGY, "Tetralogy of Fallot", 49)));

    SearchResultsResponse response = search(List.of("1-1-A-G", "2-2-C-T"), List.of(HCM, TETRALOGY));

    verify(fixtures).forConditions(List.of(HCM, TETRALOGY), 260);
    assertThat(response.getAncestryBreakdown().stream().mapToInt(BreakdownSegment::getCount).sum()).isEqualTo(260);
    assertThat(response.getAgeBreakdown().stream().mapToInt(BreakdownSegment::getCount).sum()).isEqualTo(260);
    assertThat(response.getFilteredVariants())
        .extracting(FilteredVariant::getVariant, FilteredVariant::getHasStats)
        .containsExactly(tuple("1-1-A-G", true), tuple("2-2-C-T", true));
    assertThat(response.getFilteredVariants()).allSatisfy(v -> assertThat(v.getCohortAn().orElseThrow()).isEqualTo(520));
  }

  /** A demo use case's condition on its own gets its curated breakdowns and per-variant counts instead. */
  @Test
  void prefersADemoFixtureWhenOneAppliesToTheSearch() {
    when(conditionLookup.search(List.of(HCM))).thenReturn(resolved(10, concept(HCM, "Hypertrophic cardiomyopathy", 10)));
    PhenotypeFixtures.UseCase useCase =
        new PhenotypeFixtures.UseCase(
            HCM,
            10,
            List.of(new PhenotypeFixtures.Group("AFR", 3), new PhenotypeFixtures.Group("EUR", 7)),
            List.of(new PhenotypeFixtures.Group("70+", 4), new PhenotypeFixtures.Group("18–29", 6)),
            Map.of("1-1-A-G", new MockPhenotypeData.CuratedCounts(4, 1, 1)));
    when(fixtures.forConditions(List.of(HCM), 10)).thenReturn(Optional.of(useCase));
    when(vatLookup.lookup(anyList())).thenReturn(List.of(annotated("1-1-A-G"), annotated("2-2-C-T")));

    SearchResultsResponse response = controller.searchResults(List.of("1-1-A-G", "2-2-C-T"), List.of(HCM)).getBody();

    assertThat(response.getAncestryBreakdown())
        .extracting(BreakdownSegment::getLabel, BreakdownSegment::getCount)
        .containsExactly(tuple("EUR", 7), tuple("AFR", 3));
    assertThat(response.getAgeBreakdown()).extracting(BreakdownSegment::getLabel).containsExactly("18–29", "70+");
    FilteredVariant curated = response.getFilteredVariants().get(0);
    assertThat(curated.getCohortAc().orElseThrow()).isEqualTo(4);
    assertThat(curated.getHomozygotes().orElseThrow()).isEqualTo(1);
    assertThat(curated.getClinvarPlpInTrans().orElseThrow()).isEqualTo(1);
    // The other variant isn't in the use case, so it gets generated stats for the same cohort.
    assertThat(response.getFilteredVariants().get(1).getCohortAn().orElseThrow()).isEqualTo(20);
  }

  /** The request is bracketed in the meter with the normalized variants, and named by its resolved conditions. */
  @Test
  void bracketsTheRequestInTheUsageMeter() {
    when(conditionLookup.search(List.of(HCM, TETRALOGY)))
        .thenReturn(resolved(260, concept(HCM, "Hypertrophic cardiomyopathy", 214), concept(TETRALOGY, "Tetralogy of Fallot", 49)));

    search(List.of(" 1-1-A-G ", "1-1-A-G"), List.of(HCM, TETRALOGY));

    InOrder order = inOrder(usage, vatLookup);
    order.verify(usage).beginSearch(List.of("1-1-A-G"));
    order.verify(vatLookup).lookup(List.of("1-1-A-G"));
    order.verify(usage).describeSearchPhenotypes(List.of("Hypertrophic cardiomyopathy", "Tetralogy of Fallot"));
    order.verify(usage).endSearch();
  }

  /** No condition: the meter still opens and closes the search, and isn't told a phenotype. */
  @Test
  void leavesTheMeterUnnamedWithoutACondition() {
    search(List.of("1-1-A-G"), null);

    verify(usage).beginSearch(List.of("1-1-A-G"));
    verify(usage, never()).describeSearchPhenotypes(any());
    verify(usage).endSearch();
  }

  /** A failed lookup still closes the search, so its jobs can't be attributed to the next request on the thread. */
  @Test
  void endsTheMeterSearchEvenWhenTheLookupFails() {
    when(vatLookup.lookup(anyList())).thenThrow(new IllegalStateException("BigQuery is down"));

    assertThatThrownBy(() -> controller.searchResults(List.of("1-1-A-G"), null)).hasMessage("BigQuery is down");

    verify(usage).beginSearch(List.of("1-1-A-G"));
    verify(usage).endSearch();
  }
}
