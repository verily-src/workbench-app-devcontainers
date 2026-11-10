package org.broadinstitute.variantinterpretation.datasource;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.stream.Collectors;
import java.util.stream.IntStream;
import org.broadinstitute.variantinterpretation.model.BreakdownSegment;
import org.broadinstitute.variantinterpretation.model.CohortVariant;
import org.broadinstitute.variantinterpretation.model.FilteredVariant;

/**
 * Stand-in phenotype/participant data for the phenotype-matched half of the search results.
 *
 * <p>None of this is real. The VAT is a variant-transcript aggregate table with no participant,
 * phenotype, ancestry, or age data in it at all -- and per the VAT design doc it never will have
 * (see docs/vat_schema_mapping.md), so the phenotype-matched panels need a genotype-level data
 * source that doesn't exist yet. Until it does, this makes those panels demo-able: the picked
 * condition's real participant count is split across made-up ancestry and age groups, and each
 * searched variant gets synthetic stats for a cohort of that size.
 *
 * <p>The stats are derived from the variant's real (well, synthetic-VAT) cohort-wide AoU frequency
 * and seeded off its vid, so a given variant always comes back with the same numbers and its AF
 * ratio stays consistent with the frequency shown for it in the all-participants table.
 *
 * <p>For the demo use cases, curated counts (see PhenotypeFixtures) can stand in for the random
 * ones; everything derived from them -- AN, AF, the zygosity split, the ratio, the breakdowns'
 * colors and percents -- is still worked out here, the same way.
 */
public final class MockPhenotypeData {

  // An AF ratio at or above this is what the UI flags as an enrichment worth a look, so the
  // generated data deliberately puts some variants over the line and keeps the rest under it.
  private static final double ELEVATED_AF_RATIO = 2.0;

  // Leaves room for a reference allele or two even in the most enriched case -- an AF of exactly
  // 1.0 in the phenotype-matched cohort would read as a data error rather than a signal.
  private static final double MAX_COHORT_AF = 0.98;

  private record Weight(String label, int weight, String color) {}

  // Proportions from the design mock-ups, as weights. They're rescaled to however many
  // participants the picked condition really matched, so the donut agrees with that count.
  private static final List<Weight> ANCESTRY =
      List.of(
          new Weight("EUR", 469, "#F9C854"),
          new Weight("AFR", 192, "#2078B4"),
          new Weight("AMR", 174, "#6DACE4"),
          new Weight("OTH", 87, "#B3AEAD"),
          new Weight("EAS", 32, "#A27BD7"),
          new Weight("SAS", 19, "#8CCA90"),
          new Weight("MID", 5, "#CB2D4C"));

  private static final List<Weight> AGE =
      List.of(
          new Weight("18–29", 78, "#B8DCEF"),
          new Weight("30–39", 137, "#8DC6E5"),
          new Weight("40–49", 210, "#5FAEDA"),
          new Weight("50–59", 256, "#3B8FC4"),
          new Weight("60–69", 215, "#2569A0"),
          new Weight("70+", 82, "#17456F"));

  /** A use case's hand-picked counts for one variant among its matched participants. */
  public record CuratedCounts(int cohortAc, int homozygotes, int plpInTrans) {}

  private MockPhenotypeData() {}

  /** Ancestry makeup of the matched participants. Counts sum to {@code participants}. */
  public static List<BreakdownSegment> ancestryBreakdown(int participants) {
    return breakdown(ANCESTRY, participants);
  }

  /** Age makeup of the same matched participants, so it sums to {@code participants} too. */
  public static List<BreakdownSegment> ageBreakdown(int participants) {
    return breakdown(AGE, participants);
  }

  /** A use case's own ancestry counts, in the usual group order and colors. */
  public static List<BreakdownSegment> ancestryBreakdown(List<PhenotypeFixtures.Group> counts, int participants) {
    return breakdown(ANCESTRY, counts, participants);
  }

  /** A use case's own age counts, in the usual group order and colors. */
  public static List<BreakdownSegment> ageBreakdown(List<PhenotypeFixtures.Group> counts, int participants) {
    return breakdown(AGE, counts, participants);
  }

  private static List<BreakdownSegment> breakdown(
      List<Weight> groups, List<PhenotypeFixtures.Group> counts, int participants) {
    Map<String, Integer> byLabel =
        counts.stream().collect(Collectors.toMap(PhenotypeFixtures.Group::label, PhenotypeFixtures.Group::count));
    if (!groups.stream().map(Weight::label).toList().containsAll(byLabel.keySet())) {
      throw new IllegalArgumentException("Unknown breakdown groups in " + byLabel.keySet());
    }
    if (byLabel.values().stream().mapToInt(Integer::intValue).sum() != participants) {
      throw new IllegalArgumentException("Breakdown " + byLabel + " doesn't sum to " + participants);
    }
    List<BreakdownSegment> segments = new ArrayList<>();
    for (Weight group : groups) {
      int count = byLabel.getOrDefault(group.label(), 0);
      if (count > 0) {
        segments.add(segment(group.label(), count, group.color(), participants));
      }
    }
    return segments;
  }

  /**
   * Splits {@code participants} across the weights by largest remainder, so the counts are whole
   * numbers that sum exactly to it -- plain rounding can land one or two off. A group that gets
   * nobody, which small cohorts make likely, is left out rather than listed with a 0.
   */
  private static List<BreakdownSegment> breakdown(List<Weight> weights, int participants) {
    int totalWeight = weights.stream().mapToInt(Weight::weight).sum();
    int[] counts = new int[weights.size()];
    double[] remainders = new double[weights.size()];
    int assigned = 0;
    for (int i = 0; i < weights.size(); i++) {
      double exact = (double) participants * weights.get(i).weight() / totalWeight;
      counts[i] = (int) exact;
      remainders[i] = exact - counts[i];
      assigned += counts[i];
    }
    // Truncating leaves fewer than weights.size() participants unassigned; they go to the largest
    // remainders, with ties broken toward the bigger group.
    List<Integer> byRemainder =
        IntStream.range(0, weights.size())
            .boxed()
            .sorted(
                Comparator.comparingDouble((Integer i) -> -remainders[i])
                    .thenComparingInt(i -> -weights.get(i).weight()))
            .toList();
    for (int k = 0; k < participants - assigned; k++) {
      counts[byRemainder.get(k)]++;
    }

    List<BreakdownSegment> segments = new ArrayList<>();
    for (int i = 0; i < weights.size(); i++) {
      if (counts[i] > 0) {
        Weight weight = weights.get(i);
        segments.add(segment(weight.label(), counts[i], weight.color(), participants));
      }
    }
    return segments;
  }

  // Percent is derived from the count rather than carried alongside it, so the donut and its
  // legend can't disagree.
  private static BreakdownSegment segment(String label, int count, String color, int participants) {
    BigDecimal percent =
        BigDecimal.valueOf(100L * count).divide(BigDecimal.valueOf(participants), 1, RoundingMode.HALF_UP);
    return new BreakdownSegment().label(label).count(count).percent(percent).color(color);
  }

  /**
   * Synthetic phenotype-matched stats for each searched variant, in the order searched -- one
   * FilteredVariant per CohortVariant, so the two tables line up row for row. Generated against a
   * cohort of {@code participants}, the picked condition's real count: two alleles each and no
   * missing calls, so every variant with stats reports an AN of twice that.
   *
   * <p>A variant that isn't annotated, or that the VAT has no cohort-wide AoU frequency for, comes
   * back as {@code hasStats: false}: having no participants at all in the full cohort is the one
   * case where inventing a phenotype-matched count would contradict what the other table shows.
   */
  public static List<FilteredVariant> filteredVariants(List<CohortVariant> cohortVariants, int participants) {
    return filteredVariants(cohortVariants, participants, Map.of());
  }

  /**
   * As above, but a variant with an entry in {@code curated} gets those counts instead of random
   * ones -- the demo use cases' hand-picked numbers.
   */
  public static List<FilteredVariant> filteredVariants(
      List<CohortVariant> cohortVariants, int participants, Map<String, CuratedCounts> curated) {
    if (participants <= 0) {
      throw new IllegalArgumentException("participants must be positive, got " + participants);
    }
    List<FilteredVariant> filtered = new ArrayList<>();
    for (CohortVariant cohortVariant : cohortVariants) {
      filtered.add(filteredVariant(cohortVariant, participants, curated.get(cohortVariant.getVariant())));
    }
    return filtered;
  }

  private static FilteredVariant filteredVariant(
      CohortVariant cohortVariant, int participants, CuratedCounts curated) {
    String variant = cohortVariant.getVariant();
    if (!Boolean.TRUE.equals(cohortVariant.getAnnotated())) {
      return withoutStats(variant, null, null);
    }

    String gene = cohortVariant.getGene().orElse(null);
    String consequence = cohortVariant.getConsequence().orElse(null);
    BigDecimal aouAllAf = cohortVariant.getAouAllAf().orElse(null);
    if (aouAllAf == null || aouAllAf.signum() <= 0) {
      return withoutStats(variant, gene, consequence);
    }

    int cohortAn = 2 * participants;
    // The matched cohort is part of All of Us, so it can't hold more alleles of either kind than
    // the variant table counts cohort-wide. The UI refuses to compare counts that don't nest.
    Integer aouAllAc = cohortVariant.getAouAllAc().orElse(null);
    Integer aouAllAn = cohortVariant.getAouAllAn().orElse(null);
    if (aouAllAn != null && aouAllAn < cohortAn) {
      return withoutStats(variant, gene, consequence);
    }
    if (curated != null) {
      if (curated.cohortAc() < 0 || curated.cohortAc() > cohortAn || 2 * curated.homozygotes() > curated.cohortAc()) {
        throw new IllegalArgumentException("Curated counts " + curated + " for " + variant + " don't fit " + participants);
      }
      if (aouAllAc != null && curated.cohortAc() > aouAllAc) {
        throw new IllegalArgumentException(
            "Curated counts " + curated + " for " + variant + " exceed its cohort-wide AC of " + aouAllAc);
      }
      return withStats(cohortVariant, participants, curated.cohortAc(), curated.homozygotes(), curated.plpInTrans());
    }
    Random random = seededRandom(variant);
    double enrichment = enrichment(random);
    double cohortAf = Math.min(aouAllAf.doubleValue() * enrichment, MAX_COHORT_AF);
    int cohortAc = (int) Math.round(cohortAf * cohortAn);
    // A variant rare enough that even an enriched frequency rounds to zero carriers would show up
    // as a 0x ratio, hiding exactly the signal this row is meant to demonstrate.
    if (cohortAc == 0 && enrichment >= ELEVATED_AF_RATIO) {
      cohortAc = 1 + random.nextInt(3);
    }
    // A small cohort can't hold what the bump above, or a high AF, asks for. Keep at least one
    // reference allele, for the same reason as MAX_COHORT_AF.
    cohortAc = Math.min(cohortAc, cohortAn - 1);
    if (aouAllAc != null) {
      cohortAc = Math.min(cohortAc, aouAllAc);
    }
    // Everything below is computed back from the final integer AC, so AF, the zygosity split, and
    // the ratio all agree with each other and with the AoU frequency they were derived from.
    cohortAf = (double) cohortAc / cohortAn;
    int homozygotes = Math.min((int) Math.round(participants * cohortAf * cohortAf), cohortAc / 2);
    // Carriers (homozygotes + heterozygotes) can't outnumber the cohort, which a small one with a
    // high AC otherwise would; each extra homozygote carries two alleles on one participant.
    homozygotes = Math.max(homozygotes, cohortAc - participants);
    int heterozygotes = cohortAc - 2 * homozygotes;
    int plpInTrans = plpInTrans(random, heterozygotes, isPathogenic(cohortVariant));
    return withStats(cohortVariant, participants, cohortAc, homozygotes, plpInTrans);
  }

  // Shared by the random and curated paths, so both derive AN, AF and the ratio the same way.
  private static FilteredVariant withStats(
      CohortVariant cohortVariant, int participants, int cohortAc, int homozygotes, int plpInTrans) {
    int cohortAn = 2 * participants;
    double cohortAf = (double) cohortAc / cohortAn;
    double aouAllAf = cohortVariant.getAouAllAf().orElseThrow().doubleValue();
    return new FilteredVariant()
        .variant(cohortVariant.getVariant())
        .gene(cohortVariant.getGene().orElse(null))
        .consequence(cohortVariant.getConsequence().orElse(null))
        .hasStats(true)
        .cohortAc(cohortAc)
        .cohortAn(cohortAn)
        .cohortAf(BigDecimal.valueOf(cohortAf).setScale(6, RoundingMode.HALF_UP))
        .homozygotes(homozygotes)
        .heterozygotes(cohortAc - 2 * homozygotes)
        .clinvarPlpInTrans(plpInTrans)
        .afRatio(BigDecimal.valueOf(cohortAf / aouAllAf).setScale(2, RoundingMode.HALF_UP));
  }

  private static FilteredVariant withoutStats(String variant, String gene, String consequence) {
    return new FilteredVariant()
        .variant(variant)
        .gene(gene)
        .consequence(consequence)
        .hasStats(false)
        .cohortAc(null)
        .cohortAn(null)
        .cohortAf(null)
        .homozygotes(null)
        .heterozygotes(null)
        .clinvarPlpInTrans(null)
        .afRatio(null);
  }

  // Seeded off the vid so a variant's stats are stable across requests (and across restarts) --
  // the same search has to keep returning the same numbers. String.hashCode is specified, so it's
  // stable across JVMs, but nearby seeds leave java.util.Random's first draws correlated, and vids
  // of neighbouring variants are near-identical strings; the splitmix-style mix decorrelates them.
  private static Random seededRandom(String variant) {
    long seed = variant.hashCode() * 0x9E3779B97F4A7C15L;
    seed = (seed ^ (seed >>> 30)) * 0xBF58476D1CE4E5B9L;
    return new Random(seed ^ (seed >>> 27));
  }

  // How much more common this variant is among phenotype-matched participants than in the cohort
  // as a whole. Most variants sit around 1x (background noise), and roughly one in five is
  // strongly enriched, which is the case the phenotype-matched table exists to surface.
  private static double enrichment(Random random) {
    return random.nextInt(5) == 0
        ? ELEVATED_AF_RATIO + 1 + random.nextDouble() * 22
        : 0.5 + random.nextDouble() * 1.4;
  }

  // Participants carrying a ClinVar P/LP variant on the other allele. Only het carriers can have
  // one, and a variant that's itself P/LP is likelier to turn up as half of a compound het.
  private static int plpInTrans(Random random, int heterozygotes, boolean pathogenic) {
    if (heterozygotes == 0 || random.nextInt(pathogenic ? 2 : 3) != 0) {
      return 0;
    }
    return 1 + random.nextInt(Math.min(heterozygotes, 3));
  }

  private static boolean isPathogenic(CohortVariant cohortVariant) {
    CohortVariant.ClinvarSignificanceEnum significance = cohortVariant.getClinvarSignificance().orElse(null);
    return significance == CohortVariant.ClinvarSignificanceEnum.PATHOGENIC
        || significance == CohortVariant.ClinvarSignificanceEnum.LIKELY_PATHOGENIC;
  }
}
