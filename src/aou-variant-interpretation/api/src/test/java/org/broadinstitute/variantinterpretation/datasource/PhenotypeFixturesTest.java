package org.broadinstitute.variantinterpretation.datasource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.tuple;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import org.broadinstitute.variantinterpretation.model.BreakdownSegment;
import org.broadinstitute.variantinterpretation.model.CohortVariant;
import org.broadinstitute.variantinterpretation.model.FilteredVariant;
import org.junit.jupiter.api.Test;

class PhenotypeFixturesTest {

  private static final PhenotypeFixtures.UseCase USE_CASE =
      new PhenotypeFixtures.UseCase(
          9000040L,
          10,
          List.of(new PhenotypeFixtures.Group("AFR", 3), new PhenotypeFixtures.Group("EUR", 7)),
          List.of(new PhenotypeFixtures.Group("70+", 4), new PhenotypeFixtures.Group("18–29", 6)),
          Map.of("1-100-A-G", new MockPhenotypeData.CuratedCounts(4, 1, 1)));

  /** The generated fixture that ships in the jar parses, and every use case in it adds up. */
  @Test
  void bundledFixture_loadsAndEveryUseCaseAddsUp() {
    PhenotypeFixtures fixtures = new PhenotypeFixtures();

    for (long conceptId : List.of(9000010L, 9000040L, 9000050L, 9000060L)) {
      assertThat(fixtures.forCondition(conceptId, participantsFor(conceptId))).isPresent();
    }
    PhenotypeFixtures.UseCase fh = fixtures.forCondition(9000050L, 391).orElseThrow();
    assertThat(fh.ancestry().stream().mapToInt(PhenotypeFixtures.Group::count).sum()).isEqualTo(391);
    assertThat(fh.age().stream().mapToInt(PhenotypeFixtures.Group::count).sum()).isEqualTo(391);
    assertThat(fh.variants()).containsKey("19-11116928-G-A");
  }

  @Test
  void forCondition_skipsAConditionWithNoUseCase() {
    assertThat(new PhenotypeFixtures(List.of(USE_CASE)).forCondition(9000030L, 1200)).isEmpty();
  }

  /** A use case describes one condition's participants, so it applies to a search for that condition alone. */
  @Test
  void forConditions_appliesToExactlyOneResolvedCondition() {
    PhenotypeFixtures fixtures = new PhenotypeFixtures(List.of(USE_CASE));

    assertThat(fixtures.forConditions(List.of(9000040L), 10)).isPresent();
    // The union of two conditions isn't the use case's cohort, even when one of them is its condition.
    assertThat(fixtures.forConditions(List.of(9000040L, 9000030L), 10)).isEmpty();
    assertThat(fixtures.forConditions(List.of(9000040L, 9000030L), 20)).isEmpty();
    assertThat(fixtures.forConditions(List.of(), 10)).isEmpty();
  }

  /** Written for a different count than the tables return: its numbers wouldn't add up, so skip it. */
  @Test
  void forCondition_skipsAUseCaseWrittenForADifferentParticipantCount() {
    assertThat(new PhenotypeFixtures(List.of(USE_CASE)).forCondition(9000040L, 11)).isEmpty();
  }

  /** Curated counts keep the usual group order and colors, whatever order they're written in. */
  @Test
  void curatedBreakdowns_useTheUsualOrderAndColors() {
    assertThat(MockPhenotypeData.ancestryBreakdown(USE_CASE.ancestry(), 10))
        .extracting(BreakdownSegment::getLabel, BreakdownSegment::getCount, BreakdownSegment::getColor)
        .containsExactly(tuple("EUR", 7, "#F9C854"), tuple("AFR", 3, "#2078B4"));
    assertThat(MockPhenotypeData.ageBreakdown(USE_CASE.age(), 10))
        .extracting(BreakdownSegment::getLabel)
        .containsExactly("18–29", "70+");
  }

  @Test
  void curatedBreakdowns_mustSumToTheParticipantCount() {
    assertThatThrownBy(() -> MockPhenotypeData.ancestryBreakdown(USE_CASE.ancestry(), 11))
        .isInstanceOf(IllegalArgumentException.class);
  }

  /** Curated counts replace the random ones; AN, AF, the het split and the ratio are derived as usual. */
  @Test
  void curatedCounts_replaceTheRandomStats() {
    CohortVariant variant =
        new CohortVariant().variant("1-100-A-G").annotated(true).gene("MYH7").aouAllAf(new BigDecimal("0.001"));

    FilteredVariant filtered =
        MockPhenotypeData.filteredVariants(List.of(variant), 10, USE_CASE.variants()).get(0);

    assertThat(filtered.getHasStats()).isTrue();
    assertThat(filtered.getCohortAc().orElseThrow()).isEqualTo(4);
    assertThat(filtered.getCohortAn().orElseThrow()).isEqualTo(20);
    assertThat(filtered.getCohortAf().orElseThrow()).isEqualTo(new BigDecimal("0.200000"));
    assertThat(filtered.getHomozygotes().orElseThrow()).isEqualTo(1);
    assertThat(filtered.getHeterozygotes().orElseThrow()).isEqualTo(2);
    assertThat(filtered.getClinvarPlpInTrans().orElseThrow()).isEqualTo(1);
    assertThat(filtered.getAfRatio().orElseThrow()).isEqualTo(new BigDecimal("200.00"));
  }

  private static int participantsFor(long conceptId) {
    return Map.of(9000010L, 214, 9000040L, 214, 9000050L, 391, 9000060L, 131).get(conceptId);
  }
}
