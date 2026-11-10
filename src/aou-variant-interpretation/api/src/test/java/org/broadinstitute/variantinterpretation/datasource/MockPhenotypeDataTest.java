package org.broadinstitute.variantinterpretation.datasource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.tuple;

import java.math.BigDecimal;
import java.util.List;
import java.util.stream.IntStream;
import org.broadinstitute.variantinterpretation.model.BreakdownSegment;
import org.broadinstitute.variantinterpretation.model.CohortVariant;
import org.broadinstitute.variantinterpretation.model.FilteredVariant;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class MockPhenotypeDataTest {

  /** The point of scaling: the donut has to total the real count shown beside it, exactly. */
  @ParameterizedTest
  @ValueSource(ints = {1, 2, 7, 49, 978, 12_345})
  void breakdowns_sumToTheParticipantCount(int participants) {
    assertThat(total(MockPhenotypeData.ancestryBreakdown(participants))).isEqualTo(participants);
    assertThat(total(MockPhenotypeData.ageBreakdown(participants))).isEqualTo(participants);
  }

  /** The design mock-ups' own numbers come back unchanged at the size they were drawn for. */
  @Test
  void ancestryBreakdown_keepsTheMockupCountsAt978() {
    assertThat(MockPhenotypeData.ancestryBreakdown(978))
        .extracting(BreakdownSegment::getLabel, BreakdownSegment::getCount)
        .containsExactly(
            tuple("EUR", 469), tuple("AFR", 192), tuple("AMR", 174), tuple("OTH", 87),
            tuple("EAS", 32), tuple("SAS", 19), tuple("MID", 5));
  }

  /** A small cohort can't populate every group; empty ones are dropped, not listed as 0. */
  @Test
  void breakdowns_leaveOutGroupsThatGetNobody() {
    List<BreakdownSegment> segments = MockPhenotypeData.ancestryBreakdown(3);

    assertThat(segments).allMatch(segment -> segment.getCount() > 0);
    assertThat(segments).extracting(BreakdownSegment::getLabel).contains("EUR");
    assertThat(segments).extracting(BreakdownSegment::getLabel).doesNotContain("MID");
  }

  /**
   * Every variant's stats have to fit in the cohort they were generated for: AN is two alleles per
   * participant, at least one allele stays reference, and carriers never outnumber participants.
   * Small cohorts are where those would otherwise break.
   */
  @ParameterizedTest
  @ValueSource(ints = {1, 2, 5, 49, 978})
  void filteredVariants_fitInTheCohort(int participants) {
    List<CohortVariant> variants =
        IntStream.range(0, 200)
            .mapToObj(i -> annotated("1-" + (1000 + i) + "-A-G", i % 2 == 0 ? "0.4" : "0.0005"))
            .toList();

    List<FilteredVariant> filtered = MockPhenotypeData.filteredVariants(variants, participants);

    assertThat(filtered).hasSize(variants.size());
    for (FilteredVariant variant : filtered) {
      int an = variant.getCohortAn().orElseThrow();
      int ac = variant.getCohortAc().orElseThrow();
      int homozygotes = variant.getHomozygotes().orElseThrow();
      int heterozygotes = variant.getHeterozygotes().orElseThrow();
      assertThat(an).isEqualTo(2 * participants);
      assertThat(ac).isBetween(0, an - 1);
      assertThat(2 * homozygotes + heterozygotes).isEqualTo(ac);
      assertThat(homozygotes + heterozygotes).isLessThanOrEqualTo(participants);
      assertThat(heterozygotes).isNotNegative();
    }
  }

  /**
   * The matched cohort is part of All of Us, so its counts have to nest inside the cohort-wide
   * ones from the variant table; the UI makes no comparison for counts that don't. A rare variant
   * (three carriers cohort-wide) stays at or below three however enriched the mock would like it.
   */
  @Test
  void filteredVariants_neverExceedTheCohortWideAlleleCount() {
    List<CohortVariant> variants =
        IntStream.range(0, 200)
            .mapToObj(i -> annotated("1-" + (1000 + i) + "-A-G", "0.4").aouAllAc(3).aouAllAn(480_000))
            .toList();

    List<FilteredVariant> filtered = MockPhenotypeData.filteredVariants(variants, 978);

    assertThat(filtered).allMatch(variant -> variant.getCohortAc().orElseThrow() <= 3);
    assertThat(filtered).anyMatch(variant -> variant.getCohortAc().orElseThrow() > 0);
  }

  /** A cohort larger than the whole table's allele number can't exist, so it gets no statistics. */
  @Test
  void filteredVariants_giveNoStatsWhenTheCohortOutgrowsTheTable() {
    CohortVariant variant = annotated("1-1000-A-G", "0.4").aouAllAc(300).aouAllAn(1_000);

    List<FilteredVariant> filtered = MockPhenotypeData.filteredVariants(List.of(variant), 978);

    assertThat(filtered.get(0).getHasStats()).isFalse();
  }

  /** Hand-picked demo counts that don't nest fail loudly rather than reaching the UI. */
  @Test
  void filteredVariants_rejectCuratedCountsAboveTheCohortWideCount() {
    CohortVariant variant = annotated("1-1000-A-G", "0.0005").aouAllAc(3).aouAllAn(480_000);
    var curated = java.util.Map.of("1-1000-A-G", new MockPhenotypeData.CuratedCounts(5, 0, 0));

    assertThatThrownBy(() -> MockPhenotypeData.filteredVariants(List.of(variant), 978, curated))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("exceed its cohort-wide AC");
  }

  @Test
  void filteredVariants_rejectsAnEmptyCohort() {
    assertThatThrownBy(() -> MockPhenotypeData.filteredVariants(List.of(), 0))
        .isInstanceOf(IllegalArgumentException.class);
  }

  private static int total(List<BreakdownSegment> segments) {
    return segments.stream().mapToInt(BreakdownSegment::getCount).sum();
  }

  private static CohortVariant annotated(String vid, String aouAllAf) {
    return new CohortVariant().variant(vid).annotated(true).aouAllAf(new BigDecimal(aouAllAf));
  }
}
